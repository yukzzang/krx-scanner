import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pykrx import stock

# ==========================================
# 🔧 환경 변수 (GitHub Secrets)
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print(f"\n📢 [텔레그램 미설정]\n{message}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=15)
    except: pass

# ==========================================
# 📊 티커 및 종목명 확보
# ==========================================
def get_tickers_info():
    # 안전하게 2~3일 전 영업일 데이터 확인
    for i in range(1, 6):
        target_date = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
        try:
            nm_k = stock.get_market_ticker_name("KOSPI")
            nm_q = stock.get_market_ticker_name("KOSDAQ")
            if not nm_k: continue
            
            ticker_to_name = {**nm_k, **nm_q}
            list_k = stock.get_market_ticker_list(market="KOSPI")[:500]
            list_q = stock.get_market_ticker_list(market="KOSDAQ")[:700]
            
            combined = []
            for t in list_k: combined.append({"ticker": t, "name": ticker_to_name.get(t, t)})
            for t in list_q: combined.append({"ticker": t, "name": ticker_to_name.get(t, t)})
            
            print(f"📡 분석 대상 {len(combined)}개 로드 완료 (기준일: {target_date})")
            return combined, target_date
        except: continue
    return [], ""

# ==========================================
# 📊 점수 계산 (완화 및 안정화)
# ==========================================
def calculate_score(df):
    if len(df) < 60: return 0, 0, 0
    
    close = df['종가'].values
    vol = df['거래량'].values
    curr = float(close[-1])
    score = 0

    # 1. 거래량 (대폭 완화)
    avg_vol = np.mean(vol[-21:-1]) + 1e-9
    v_ratio = vol[-1] / avg_vol
    if 0.1 < v_ratio < 1.8: score += 25
    elif v_ratio < 2.5: score += 15

    # 2. 이평선 수렴 (폭 10% 완화)
    m5, m20, m60 = np.mean(close[-5:]), np.mean(close[-20:]), np.mean(close[-60:])
    gap = max(m5, m20, m60) / (min(m5, m20, m60) + 1e-9)
    if gap < 1.06: score += 20
    elif gap < 1.10: score += 10

    # 3. 추세 및 위치
    if m60 >= np.mean(close[-65:-5]): score += 15
    h60 = np.max(close[-60:])
    if curr > h60 * 0.65: score += 15
    elif curr > h60 * 0.50: score += 10

    # 4. 변동성 (VCP 완화)
    r10 = (np.max(close[-10:]) - np.min(close[-10:])) / (curr + 1e-9)
    if r10 < 0.20: score += 15
    elif r10 < 0.35: score += 10

    # 5. 상승 압력
    if close[-1] >= close[-5]: score += 10

    entry = float(np.max(close[-10:]) * 1.005)
    stop = float(np.min(close[-10:]) * 0.98)
    return score, entry, stop

# ==========================================
# 🔍 개별 종목 분석 (pykrx 엔진)
# ==========================================
def analyze_ticker(item, target_date):
    try:
        # 데이터 차단 방지를 위한 미세 지연
        time.sleep(0.05)
        
        start_date = (datetime.strptime(target_date, "%Y%m%d") - timedelta(days=150)).strftime("%Y%m%d")
        df = stock.get_market_ohlcv_by_date(start_date, target_date, item['ticker'])
        
        if df.empty or len(df) < 60: return None

        score, entry, stop = calculate_score(df)
        curr = float(df['종가'].iloc[-1])
        
        # 돌파 조건 완화
        h5 = float(df['종가'].iloc[-5:].max())
        is_break = curr >= h5 * 0.92

        return {
            "name": item['name'], "ticker": item['ticker'],
            "price": curr, "score": score, "entry": entry, "stop": stop, "breakout": is_break
        }
    except: return None

# ==========================================
# 🚀 메인 실행
# ==========================================
def run_scanner():
    start_time = time.time()
    items, target_date = get_tickers_info()
    
    if not items:
        send_telegram("❌ 종목 정보를 가져오지 못했습니다.")
        return

    print(f"🚀 {len(items)}개 종목 전수 스캔 시작 (엔진: pykrx)")
    A, B, C = [], [], []

    # 병렬 처리 (서버 부하 방지를 위해 max_workers 조절)
    with ThreadPoolExecutor(max_workers=15) as executor:
        futures = [executor.submit(analyze_ticker, it, target_date) for it in items]
        
        for idx, future in enumerate(as_completed(futures)):
            res = future.result()
            if not res: continue

            if res["score"] >= 65 and res["breakout"]: A.append(res)
            elif res["score"] >= 55: B.append(res)
            elif res["score"] >= 45: C.append(res)

            if (idx + 1) % 100 == 0:
                print(f"📊 분석 중... {idx + 1}/{len(items)} 완료")

    # 정렬
    A = sorted(A, key=lambda x: x['score'], reverse=True)
    B = sorted(B, key=lambda x: x['score'], reverse=True)
    C = sorted(C, key=lambda x: x['score'], reverse=True)

    # 📢 결과 리포트
    msg = f"<b>📊 [1200종목 전수 리포트]</b>\n📅 기준일: {target_date}\n\n"
    
    msg += "<b>🔥 A급 (강력추천)</b>\n"
    if A:
        for i in A[:7]:
            msg += f"• <b>{i['name']}</b> ({i['score']}점)\n  현재: {int(i['price']):,} | 🚀 {int(i['entry']):,}\n\n"
    else: msg += "없음\n\n"

    msg += "<b>👀 B급 (관찰대상)</b>\n"
    msg += ", ".join([f"<b>{x['name']}</b>" for x in B[:12]]) if B else "없음"
    msg += "\n\n"

    msg += "<b>🌱 C급 (매집초기)</b>\n"
    msg += ", ".join([x['name'] for x in C[:15]]) if C else "없음"

    send_telegram(msg)
    
    total_time = int(time.time() - start_time)
    print(f"✅ 완료 (소요시간: {total_time}초) | A:{len(A)} B:{len(B)} C:{len(C)}")

if __name__ == "__main__":
    run_scanner()
