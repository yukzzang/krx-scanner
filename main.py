import pandas as pd
import numpy as np
import requests
from datetime import datetime
import os
import time
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================
# 🔧 환경 변수
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# ==========================================
# 📢 텔레그램
# ==========================================
def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print(message)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }, timeout=10)
    except Exception as e:
        print("텔레그램 오류:", e)

# ==========================================
# 📊 점수 계산
# ==========================================
def calculate_score(df):
    close = df['Close']
    vol = df['Volume']

    if len(df) < 70:
        return 0, None, None

    curr_close = close.iloc[-1]

    avg_vol = vol.iloc[-21:-1].mean() + 1e-9
    vol_ratio = vol.iloc[-1] / avg_vol

    score = 0

    # 거래량
    if 0.3 < vol_ratio < 0.7: score += 25
    elif 0.2 < vol_ratio < 1.0: score += 15

    # 이평선
    ma5 = close.rolling(5).mean().iloc[-1]
    ma20 = close.rolling(20).mean().iloc[-1]
    ma60 = close.rolling(60).mean().iloc[-1]

    ma_gap = max(ma5, ma20, ma60) / min(ma5, ma20, ma60)

    if ma_gap < 1.03: score += 20
    elif ma_gap < 1.05: score += 10

    # 추세
    if close.rolling(60).mean().iloc[-1] >= close.rolling(60).mean().iloc[-5]:
        score += 15

    # 위치
    high_60 = close.iloc[-60:].max()
    if curr_close > high_60 * 0.85: score += 15
    elif curr_close > high_60 * 0.70: score += 10

    # 변동성
    range_10 = (close.iloc[-10:].max() - close.iloc[-10:].min()) / curr_close
    if range_10 < 0.05: score += 15
    elif range_10 < 0.08: score += 10

    # 상승 압력
    if close.iloc[-1] >= close.iloc[-2] >= close.iloc[-3]:
        score += 10

    # 진입/손절
    high = close.iloc[-10:].max()
    low = close.iloc[-10:].min()

    entry = high * 1.005
    stop = low * 0.98

    return score, entry, stop

# ==========================================
# 🔍 개별 종목 분석
# ==========================================
def analyze_ticker(ticker):
    try:
        df = yf.download(ticker, period="6mo", interval="1d", progress=False)

        if df.empty:
            return None

        score, entry, stop = calculate_score(df)

        close = df['Close'].iloc[-1]

        # 돌파 직전
        recent_high_5 = df['Close'].iloc[-5:].max()
        is_breakout = close >= recent_high_5 * 0.98

        return {
            "ticker": ticker,
            "price": close,
            "score": score,
            "entry": entry,
            "stop": stop,
            "breakout": is_breakout
        }

    except:
        return None

# ==========================================
# 🚀 메인 스캐너
# ==========================================
def run_scanner():

    print("🚀 yfinance 병렬 스캐너 시작")

    # 👉 테스트용 (필요하면 확장 가능)
    tickers = [
        "005930.KS", "000660.KS", "035420.KS", "051910.KS",
        "068270.KS", "207940.KS", "035720.KS",
        "091990.KQ", "247540.KQ", "263750.KQ"
    ]

    A, B, C = [], [], []

    # 병렬 처리
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(analyze_ticker, t) for t in tickers]

        for future in as_completed(futures):
            result = future.result()
            if not result:
                continue

            if result["score"] >= 75 and result["breakout"]:
                A.append(result)
            elif result["score"] >= 65:
                B.append(result)
            elif result["score"] >= 55:
                C.append(result)

    # 정렬
    A = sorted(A, key=lambda x: x['score'], reverse=True)
    B = sorted(B, key=lambda x: x['score'], reverse=True)
    C = sorted(C, key=lambda x: x['score'], reverse=True)

    # ==========================================
    # 📢 결과
    # ==========================================
    msg = "<b>📊 [yfinance 매집 스캐너]</b>\n\n"

    msg += "<b>🔥 A급</b>\n"
    if A:
        for i in A[:5]:
            msg += f"{i['ticker']} ({i['score']})\n"
    else:
        msg += "없음\n"

    msg += "\n<b>👀 B급</b>\n"
    msg += ", ".join([x['ticker'] for x in B[:8]]) if B else "없음"

    msg += "\n\n<b>🌱 C급</b>\n"
    msg += ", ".join([x['ticker'] for x in C[:10]]) if C else "없음"

    send_telegram(msg)

    print("✅ 완료")

# ==========================================
# ▶ 실행
# ==========================================
if __name__ == "__main__":
    run_scanner()