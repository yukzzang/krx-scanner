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
        requests.post(url, json={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=10)
    except: pass

# ==========================================
# 📊 티커 및 종목명 로드
# ==========================================
def get_tickers_info():
    # 안전하게 어제 날짜 사용
    date = (datetime.today() - timedelta(days=1)).strftime("%Y%m%d")
    try:
        # 종목명 사전 구축
        nm_k = stock.get_market_ticker_name("KOSPI")
        nm_q = stock.get_market_ticker_name("KOSDAQ")
        ticker_to_name = {**nm_k, **nm_q}

        cap_k = stock.get_market_cap(date, market="KOSPI")
        cap_q = stock.get_market_cap(date, market="KOSDAQ")

        list_k = cap_k.sort_values('시가총액', ascending=False).head(350).index.tolist()
        list_q = cap_q.sort_values('시가총액', ascending=False).head(650).index.tolist()

        combined = []
        for t in list_k: combined.append({"ticker": f"{t}.KS", "name": ticker_to_name.get(t, t)})
        for t in list_q: combined.append({"ticker": f"{t}.KQ", "name": ticker_to_name.get(t, t)})
        return combined
    except:
        return [{"ticker": "005930.KS", "name": "삼성전자"}]

# ==========================================
# 📊 점수 계산 (완화 및 안정화)
# ==========================================
def calculate_score(df):
    try:
        # yfinance 데이터 구조 방어 (Squeeze)
        close = df['Close'].squeeze()
        vol = df['Volume'].squeeze()
        if len(close) < 70: return 0, 0, 0

        curr_close = float(close.iloc[-1])
        score = 0

        # 거래량 완화 (0.1 ~ 1.5배)
        avg_vol = vol.iloc[-21:-1].mean() + 1e-9
        vol_ratio = vol.iloc[-1] / avg_vol
        if 0.1 < vol_ratio < 1.3: score += 25
        elif vol_ratio < 1.8: score += 15

        # 이평선 수렴 (폭 6%까지 완화)
        ma5 = close.rolling(5).mean().iloc[-1]
        ma20 = close.rolling(20).mean().iloc[-1]
        ma60 = close.rolling(60).mean().iloc[-1]
        ma_gap = max(ma5, ma20, ma60) / (min(ma5, ma20, ma60) + 1e-9)
        if ma_gap < 1.04: score += 20
        elif ma_gap < 1.07: score += 10

        # 추세 (60일선 우상향)
        if close.rolling(60).mean().iloc[-1] >= close.rolling(60).mean().iloc[-5]:
            score += 15

        # 위치 (60일 고가 대비 75% 이상이면 합격)
        high_60 = close.iloc[-60:].max()
        if curr_close > high_60 * 0.75: score += 15
        elif curr_close > high_60 * 0.60: score += 10

        # 변동성 축소 (15%까지 대폭 완화)
        range_10 = (close.iloc[-10:].max() - close.iloc[-10:].min()) / (curr_close + 1e-9)
        if range_10 < 0.12: score += 15
        elif range_10 < 0.18: score += 10

        # 상승 압력
        if close.iloc[-1] >= close.iloc[-3]: score += 10

        entry = float(close.iloc[-10:].max() * 1.005)
        stop = float(close.iloc[-10:].min() * 0.98)

        return score, entry, stop
    except:
        return 0, 0, 0

# ==========================================
# 🔍 종목 분석
# ==========================================
def analyze_ticker(item):
    try:
        ticker = item['ticker']
        df = yf.download(ticker, period="7mo", interval="1d", progress=False)
        if df.empty: return None

        score, entry, stop = calculate_score(df)
        close = float(df['Close'].squeeze().iloc[-1])

        # 돌파 조건 완화 (5일 고가 대비 -5% 이내)
        recent_high_5 = float(df['Close'].squeeze().iloc[-5:].max())
        is_breakout = close >= recent_high_5 * 0.94

        return {
            "name": item['name'], "ticker": ticker.split('.')[0],
            "price": close, "score": score, "entry": entry, "stop": stop, "breakout": is_breakout
        }
    except: return None

# ==========================================
# 🚀 메인 실행
# ==========================================
def run_scanner():
    print("🚀 완화형 병렬 스캐너 가동")
    items = get_tickers_info()
    A, B, C = [], [], []

    with ThreadPoolExecutor(max_workers=30) as executor:
        futures = [executor.submit(analyze_ticker, it) for it in items]
        for future in as_completed(futures):
            res = future.result()
            if not res or res['score'] < 40: continue

            if res["score"] >= 70 and res["breakout"]: A.append(res)
            elif res["score"] >= 60: B.append(res)
            elif res["score"] >= 50: C.append(res)

    A = sorted(A, key=lambda x: x['score'], reverse=True)
    B = sorted(B, key=lambda x: x['score'], reverse=True)

    msg = "<b>📊 [완화형 매집 리포트]</b>\n\n"
    msg += "<b>🔥 A급 (즉시)</b>\n"
    if A:
        for i in A[:6]:
            msg += f"• <b>{i['name']}</b> ({i['score']}점)\n  현재: {int(i['price']):,} | 🚀 {int(i['entry']):,}\n\n"
    else: msg += "없음\n"

    msg += "\n<b>👀 B급 (관찰)</b>\n"
    msg += ", ".join([f"<b>{x['name']}</b>" for x in B[:10]]) if B else "없음"

    send_telegram(msg)
    print(f"✅ 완료 | A:{len(A)} B:{len(B)} C:{len(C)}")

if __name__ == "__main__":
    run_scanner()
