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
        print(message)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=15)
    except: pass

# ==========================================
# 📊 1000개 티커 및 종목명 로드
# ==========================================
def get_tickers_info():
    # 안전하게 영업일 기준 어제 날짜 사용
    date = (datetime.today() - timedelta(days=1)).strftime("%Y%m%d")
    try:
        nm_k = stock.get_market_ticker_name("KOSPI")
        nm_q = stock.get_market_ticker_name("KOSDAQ")
        ticker_to_name = {**nm_k, **nm_q}

        # 시총 순으로 코스피 400개, 코스닥 600개 -> 총 1000개
        cap_k = stock.get_market_cap(date, market="KOSPI")
        cap_q = stock.get_market_cap(date, market="KOSDAQ")

        list_k = cap_k.sort_values('시가총액', ascending=False).head(400).index.tolist()
        list_q = cap_q.sort_values('시가총액', ascending=False).head(600).index.tolist()

        combined = []
        for t in list_k: combined.append({"ticker": f"{t}.KS", "name": ticker_to_name.get(t, t)})
        for t in list_q: combined.append({"ticker": f"{t}.KQ", "name": ticker_to_name.get(t, t)})
        
        print(f"📡 분석 대상 1,000개 추출 완료 (K:{len(list_k)}, Q:{len(list_q)})")
        return combined
    except Exception as e:
        print(f"⚠️ 티커 수집 중 오류: {e}")
        return [{"ticker": "005930.KS", "name": "삼성전자"}]

# ==========================================
# 📊 점수 계산 로직
# ==========================================
def calculate_score(df):
    try:
        # yfinance 멀티인덱스 방어
        df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]
        close = df['Close'].astype(float)
        vol = df['Volume'].astype(float)
        
        if len(close) < 70: return 0, 0, 0
        curr_p = float(close.iloc[-1])
        score = 0

        # 1. 거래량 (25점)
        avg_v = vol.iloc[-21:-1].mean() + 1e-9
        v_ratio = vol.iloc[-1] / avg_v
        if 0.1 < v_ratio < 1.3: score += 25
        elif v_ratio < 1.8: score += 15

        # 2. 이평선 수렴 (20점)
        m5, m20, m60 = close.rolling(5).mean().iloc[-1], close.rolling(20).mean().iloc[-1], close.rolling(60).mean().iloc[-1]
        gap = max(m5, m20, m60) / (min(m5, m20, m60) + 1e-9)
        if gap < 1.04: score += 20
        elif gap < 1.07: score += 10

        # 3. 추세 (15점)
        if close.rolling(60).mean().iloc[-1] >= close.rolling(60).mean().iloc[-5]: score += 15
        
        # 4. 위치 (15점)
        h60 = close.iloc[-60:].max()
        if curr_p > h60 * 0.75: score += 15
        elif curr_p > h60 * 0.60: score += 10

        # 5. 변동성 (15점)
        r10 = (close.iloc[-10:].max() - close.iloc[-10:].min()) / (curr_p + 1e-9)
        if r10 < 0.12: score += 15
        elif r10 < 0.18: score += 10

        # 6. 상승압력 (10점)
        if close.iloc[-1] >= close.iloc[-3]: score += 10

        entry = float(close.iloc[-10:].max() * 1.005)
        stop = float(close.iloc[-10:].min() * 0.98)
        return score, entry, stop
    except: return 0, 0, 0

# ==========================================
# 🔍 개별 분석 (Thread)
# ==========================================
def analyze_ticker(item):
    try:
        df = yf.download(item['ticker'], period="7mo", interval="1d", progress=False, show_errors=False)
        if df.empty: return None
        
        score, entry, stop = calculate_score(df)
        df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]
        curr_p = float(df['Close'].iloc[-1])
        
        # 돌파 조건
        h5 = float(df['Close'].iloc[-5:].max())
        is_break = curr_p >= h5 * 0.94

        return {
            "name": item['name'], "ticker": item['ticker'].split('.')[0],
            "price": curr_p, "score": score, "entry": entry, "stop": stop, "breakout": is_break
        }
    except: return None

# ==========================================
# 🚀 메인 실행
# ==========================================
def run_scanner():
    print("🚀 1,000종목 전수 스캔 시작...")
    items = get_tickers_info()
    A, B, C = [], [], []

    # 병렬 처리 (30개 스레드)
    with ThreadPoolExecutor(max_workers=30) as executor:
        futures = [executor.submit(analyze_ticker, it) for it in items]
        
        for idx, future in enumerate(as_completed(futures)):
            res = future.result()
            if not res: continue

            # 등급 분류
            if res["score"] >= 70 and res["breakout"]: A.append(res)
            elif res["score"] >= 60: B.append(res)
            elif res["score"] >= 50: C.append(res)

            if (idx + 1) % 100 == 0:
                print(f"📊 진행률: {idx + 1}/1000 완료...")

    # 정렬
    A = sorted(A, key=lambda x: x['score'], reverse=True)
    B = sorted(B, key=lambda x: x['score'], reverse=True)
    C = sorted(C, key=lambda x: x['score'], reverse=True)

    # 📢 리포트 작성
    msg = f"<b>📊 [1000종목 전수 리포트]</b>\n📅 {datetime.now().strftime('%Y-%m-%d')}\n\n"
    
    msg += "<b>🔥 A급 (즉시공략)</b>\n"
    if A:
        for i in A[:6]:
            msg += f"• <b>{i['name']}</b> ({i['score']}점)\n  현재: {int(i['price']):,} | 🚀 {int(i['entry']):,}\n\n"
    else: msg += "대상 없음\n\n"

    msg += "<b>👀 B급 (관찰)</b>\n"
    msg += ", ".join([f"<b>{x['name']}</b>" for x in B[:10]]) if B else "없음"
    msg += "\n\n"

    msg += "<b>🌱 C급 (매집초기)</b>\n"
    msg += ", ".join([f"{x['name']}" for x in C[:12]]) if C else "없음"

    send_telegram(msg)
    print(f"✅ 스캔 완료 | A:{len(A)} B:{len(B)} C:{len(C)}")

if __name__ == "__main__":
    run_scanner()
