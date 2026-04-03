import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import os
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
from pykrx import stock

# ==========================================
# 🔧 환경 변수
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print(f"\n📢 [메시지]\n{message}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=15)
    except: pass

# ==========================================
# 📊 티커 및 종목명 매핑 (안정화)
# ==========================================
def get_tickers_with_names():
    try:
        # 종목명 딕셔너리 생성
        nm_k = stock.get_market_ticker_name("KOSPI")
        nm_q = stock.get_market_ticker_name("KOSDAQ")
        ticker_to_name = {**nm_k, **nm_q}

        # 시총 순 정렬을 위해 전날 날짜 사용
        target_date = (datetime.now() - timedelta(days=2)).strftime("%Y%m%d")
        
        # 코스피 500개, 코스닥 700개 추출
        tickers_k = stock.get_market_ticker_list(market="KOSPI")[:500]
        tickers_q = stock.get_market_ticker_list(market="KOSDAQ")[:700]

        combined = []
        for t in tickers_k:
            combined.append({"ticker": f"{t}.KS", "name": ticker_to_name.get(t, t)})
        for t in tickers_q:
            combined.append({"ticker": f"{t}.KQ", "name": ticker_to_name.get(t, t)})

        print(f"📡 분석 대상 {len(combined)}개 로드 완료")
        return combined
    except Exception as e:
        print(f"❌ 티커 로딩 실패: {e}")
        return [{"ticker": "005930.KS", "name": "삼성전자"}]

# ==========================================
# 📊 점수 계산 (완화 및 안정화)
# ==========================================
def calculate_score(close, vol):
    if len(close) < 60: return 0, 0, 0
    
    curr = float(close[-1])
    score = 0

    # 1. 거래량 (대폭 완화)
    avg_vol = np.mean(vol[-21:-1]) + 1e-9
    v_ratio = vol[-1] / avg_vol
    if 0.1 < v_ratio < 1.8: score += 25
    elif v_ratio < 2.5: score += 15

    # 2. 이평선 수렴 (폭 10%까지 완화)
    m5, m20, m60 = np.mean(close[-5:]), np.mean(close[-20:]), np.mean(close[-60:])
    gap = max(m5, m20, m60) / (min(m5, m20, m60) + 1e-9)
    if gap < 1.06: score += 20
    elif gap < 1.10: score += 10

    # 3. 추세 및 위치
    if m60 >= np.mean(close[-65:-5]): score += 15
    h60 = np.max(close[-60:])
    if curr > h60 * 0.65: score += 15
    elif curr > h60 * 0.50: score += 10

    # 4. 변동성 (VCP 패턴 완화)
    r10 = (np.max(close[-10:]) - np.min(close[-10:])) / (curr + 1e-9)
    if r10 < 0.20: score += 15
    elif r10 < 0.35: score += 10

    # 5. 상승 압력
    if close[-1] >= close[-5]: score += 10

    entry = float(np.max(close[-10:]) * 1.005)
    stop = float(np.min(close[-10:]) * 0.98)
    return score, entry, stop

# ==========================================
# 🔍 개별 분석 (안정적인 1:1 다운로드)
# ==========================================
def analyze_ticker(item):
    try:
        # 배치 대신 개별 다운로드로 데이터 누락 방지
        df = yf.download(item['ticker'], period="1y", interval="1d", progress=False, show_errors=False)
        if df.empty or len(df) < 60: return None

        # 데이터 구조 정리 (멀티인덱스 방어)
        close = df['Close'].values.flatten()
        vol = df['Volume'].values.flatten()

        score, entry, stop = calculate_score(close, vol)
        curr = float(close[-1])

        # 돌파 조건 (최근 5일 고가 대비 -8% 이내)
        h5 = float(np.max(close[-5:]))
        is_break = curr >= h5 * 0.92

        return {
            "name": item['name'], 
            "ticker": item['ticker'].split('.')[0], 
            "price": curr, 
            "score": score, 
            "entry": entry, 
            "stop": stop, 
            "breakout": is_break
        }
    except: return None

# ==========================================
# 🚀 메인 실행
# ==========================================
def run_scanner():
    print("🚀 [종목명 매핑] 1200종목 전수 스캐너 시작")
    start_time = datetime.now()

    items = get_tickers_with_names()
    A, B, C = [], [], []

    # 병렬 처리 (스레드 20개로 안정적으로)
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(analyze_ticker, it) for it in items]
        
        for idx, future in enumerate(as_completed(futures)):
            res = future.result()
            if not res: continue

            # 점수 및 돌파 조건 필터
            if res["score"] >= 65 and res["breakout"]: A.append(res)
            elif res["score"] >= 55: B.append(res)
            elif res["score"] >= 45: C.append(res)

            if (idx + 1) % 100 == 0:
                print(f"📊 분석 진행 중: {idx + 1}/1200 완료...")

    # 정렬
    A = sorted(A, key=lambda x: x['score'], reverse=True)
    B = sorted(B, key=lambda x: x['score'], reverse=True)
    C = sorted(C, key=lambda x: x['score'], reverse=True)

    # 📢 메시지 구성
    msg = f"<b>📊 [전수조사 리포트]</b>\n📅 {datetime.now().strftime('%Y-%m-%d')}\n"
    msg += f"⏱ 소요시간: {int((datetime.now() - start_time).total_seconds())}초\n\n"

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
    print(f"✅ 완료 | A:{len(A)} B:{len(B)} C:{len(C)}")

if __name__ == "__main__":
    run_scanner()
