import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pykrx import stock

# ==========================================
# 🔧 환경 변수
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
# 📊 티커 수집 (확실한 날짜 기준)
# ==========================================
def get_tickers_info():
    # 최근 7일 중 데이터가 있는 가장 가까운 날짜 탐색
    for i in range(1, 8):
        target_date = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
        try:
            # 해당 날짜에 상장되어 있던 종목 리스트를 가져옴 (date 인자 추가가 핵심)
            list_k = stock.get_market_ticker_list(date=target_date, market="KOSPI")
            list_q = stock.get_market_ticker_list(date=target_date, market="KOSDAQ")

            if len(list_k) == 0:
                continue

            # 종목명 매핑
            nm_k = stock.get_market_ticker_name("KOSPI")
            nm_q = stock.get_market_ticker_name("KOSDAQ")
            ticker_to_name = {**nm_k, **nm_q}

            combined = []
            # 상위 500/700개 (필요시 조절)
            for t in list_k[:500]:
                combined.append({"ticker": t, "name": ticker_to_name.get(t, t)})
            for t in list_q:
                combined.append({"ticker": t, "name": ticker_to_name.get(t, t)})

            print(f"📡 {len(combined)}개 종목 로드 완료 (기준일: {target_date})")
            return combined, target_date

        except:
            print(f"날짜 {target_date} 조회 실패, 이전 날짜 시도...")
            continue

    return [], ""

# ==========================================
# 📊 점수 계산 (동일)
# ==========================================
def calculate_score(df):
    if len(df) < 60: return 0, 0, 0
    close = df['종가'].values
    vol = df['거래량'].values
    curr = float(close[-1])
    score = 0

    # 거래량 비율
    avg_vol = np.mean(vol[-21:-1]) + 1e-9
    v_ratio = vol[-1] / avg_vol
    if 0.1 < v_ratio < 1.8: score += 25
    elif v_ratio < 2.5: score += 15

    # 이평선 수렴
    m5, m20, m60 = np.mean(close[-5:]), np.mean(close[-20:]), np.mean(close[-60:])
    gap = max(m5, m20, m60) / (min(m5, m20, m60) + 1e-9)
    if gap < 1.06: score += 20
    elif gap < 1.10: score += 10

    # 추세 및 위치/변동성
    if m60 >= np.mean(close[-65:-5]): score += 15
    h60 = np.max(close[-60:])
    if curr > h60 * 0.65: score += 15
    elif curr > h60 * 0.50: score += 10
    
    r10 = (np.max(close[-10:]) - np.min(close[-10:])) / (curr + 1e-9)
    if r10 < 0.20: score += 15
    elif r10 < 0.35: score += 10
    if close[-1] >= close[-5]: score += 10

    entry = float(np.max(close[-10:]) * 1.005)
    stop = float(np.min(close[-10:]) * 0.98)
    return score, entry, stop

# ==========================================
# 🔍 종목 분석
# ==========================================
def analyze_ticker(item, target_date):
    try:
        # 차단 방지를 위한 미세 지연
        time.sleep(0.05)
        start_date = (datetime.strptime(target_date, "%Y%m%d") - timedelta(days=160)).strftime("%Y%m%d")
        df = stock.get_market_ohlcv_by_date(start_date, target_date, item['ticker'])

        if df.empty or len(df) < 60:
            return None

        score, entry, stop = calculate_score(df)
        curr = float(df['종가'].iloc[-1])
        h5 = float(df['종가'].iloc[-5:].max())
        is_break = curr >= h5 * 0.92

        return {
            "name": item['name'], "ticker": item['ticker'],
            "price": curr, "score": score, "entry": entry, "stop": stop, "breakout": is_break
        }
    except:
        return None

# ==========================================
# 🚀 메인 실행
# ==========================================
def run_scanner():
    start_time = time.time()
    items, target_date = get_tickers_info()

    if not items:
        send_telegram("❌ 종목 데이터를 가져오지 못했습니다. 날짜 설정을 확인하세요.")
        return

    print(f"🚀 {len(items)}개 종목 분석 시작...")
    A, B, C = [], [], []

    # max_workers를 너무 높이면 거래소 서버에서 차단할 수 있음 (8~12 권장)
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(analyze_ticker, it, target_date) for it in items]

        for idx, future in enumerate(as_completed(futures)):
            res = future.result()
            if not res: continue

            if res["score"] >= 65 and res["breakout"]: A.append(res)
            elif res["score"] >= 55: B.append(res)
            elif res["score"] >= 45: C.append(res)

            if (idx + 1) % 100 == 0:
                print(f"📊 진행 상황: {idx+1}/{len(items)} 완료")

    # 정렬 및 메시지 생성
    A.sort(key=lambda x: x['score'], reverse=True)
    B.sort(key=lambda x: x['score'], reverse=True)
    C.sort(key=lambda x: x['score'], reverse=True)

    msg = f"<b>📊 [실전 매집 스캐너]</b>\n📅 기준일: {target_date}\n\n"
    msg += "<b>🔥 A급 (강력 추천)</b>\n"
    if A:
        for i in A[:7]:
            msg += f"• <b>{i['name']}</b> ({i['score']}점)\n  현재: {int(i['price']):,} | 🚀 {int(i['entry']):,}\n"
    else: msg += "없음\n"

    msg += "\n<b>👀 B급 (관찰)</b>\n"
    msg += ", ".join([x['name'] for x in B[:12]]) if B else "없음"

    msg += "\n\n<b>🌱 C급 (매집)</b>\n"
    msg += ", ".join([x['name'] for x in C[:15]]) if C else "없음"

    send_telegram(msg)
    print(f"✅ 완료 | A:{len(A)} B:{len(B)} C:{len(C)} | 소요시간: {int(time.time()-start_time)}초")

if __name__ == "__main__":
    run_scanner()