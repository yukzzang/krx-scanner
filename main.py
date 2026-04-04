import pandas as pd
import numpy as np
import requests
import os
import time
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
from pykrx import stock
from datetime import datetime, timedelta

# ==========================================
# 🔧 환경 변수
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# ==========================================
# 📩 텔레그램
# ==========================================
def send_telegram(message):
    print(message)

    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("❌ 텔레그램 설정 없음")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    try:
        requests.post(url, json={
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }, timeout=10)
    except Exception as e:
        print(f"❌ 텔레그램 오류: {e}")

# ==========================================
# 📅 종목 가져오기
# ==========================================
def get_valid_tickers():
    for i in range(0, 10):
        date = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")

        try:
            kospi = stock.get_market_ticker_list(date, market="KOSPI")
            kosdaq = stock.get_market_ticker_list(date, market="KOSDAQ")

            if len(kospi) > 100:
                ticker_map = {}

                for t in kospi:
                    ticker_map[t] = stock.get_market_ticker_name(t)
                for t in kosdaq:
                    ticker_map[t] = stock.get_market_ticker_name(t)

                combined = []

                for t in kospi[:400]:
                    combined.append({"ticker": t + ".KS", "name": ticker_map.get(t, t)})

                for t in kosdaq[:400]:
                    combined.append({"ticker": t + ".KQ", "name": ticker_map.get(t, t)})

                return combined, date

        except:
            continue

    return [], ""

# ==========================================
# 📊 점수 계산
# ==========================================
def calculate_score(df):
    try:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        close = df['Close'].astype(float)
        vol = df['Volume'].astype(float)

        if len(df) < 60:
            return 0, 0, 0, False

        score = 0
        curr = close.iloc[-1]

        avg_v = vol.iloc[-20:-5].mean() + 1e-9
        recent_v = vol.iloc[-5:].mean()

        if recent_v < avg_v * 0.8:
            score += 25
        elif recent_v < avg_v:
            score += 15

        r20 = (close.iloc[-20:].max() - close.iloc[-20:].min()) / curr
        r5 = (close.iloc[-5:].max() - close.iloc[-5:].min()) / curr

        if r5 < r20 * 0.7:
            score += 25
        elif r5 < r20:
            score += 15

        m20 = close.rolling(20).mean().iloc[-1]
        m60 = close.rolling(60).mean().iloc[-1]

        if curr > m20 > m60:
            score += 20

        pos = curr / (close.iloc[-60:].max() + 1e-9)
        if 0.65 < pos < 0.95:
            score += 20

        if close.iloc[-1] > close.iloc[-3]:
            score += 10

        high5 = close.iloc[-5:].max()
        low5 = close.iloc[-5:].min()

        entry = high5 * 1.01
        stop = low5 * 0.97

        breakout_ready = curr >= high5 * 0.92

        return score, entry, stop, breakout_ready

    except:
        return 0, 0, 0, False

# ==========================================
# 🔥 A급 필터
# ==========================================
def is_strong_A(df):
    try:
        close = df['Close'].astype(float)
        vol = df['Volume'].astype(float)

        vol_past = vol.iloc[-10:-3].mean()
        vol_recent = vol.iloc[-3:].mean()

        vol_signal = vol_recent > vol_past * 1.2
        momentum = close.iloc[-1] > close.iloc[-2] * 1.01

        high20 = close.iloc[-20:].max()
        near_res = close.iloc[-1] >= high20 * 0.90

        prev_low = close.iloc[-20:-5].min()
        recent_low = close.iloc[-5:].min()

        higher_low = recent_low > prev_low

        return vol_signal and momentum and near_res and higher_low

    except:
        return False

# ==========================================
# 🔍 분석
# ==========================================
def analyze(item):
    try:
        time.sleep(0.01)

        df = yf.download(item['ticker'], period="6mo", interval="1d", progress=False)

        if df.empty or len(df) < 60:
            return None, False

        score, entry, stop, ready = calculate_score(df)

        if score < 40:
            return None, True

        strong_A = is_strong_A(df)

        return {
            "name": item['name'],
            "score": score,
            "entry": entry,
            "stop": stop,
            "ready": ready,
            "strong_A": strong_A
        }, True

    except:
        return None, False

# ==========================================
# 🚀 실행
# ==========================================
def run():
    print("🚀 스캐너 시작")

    tickers, date = get_valid_tickers()

    if not tickers:
        send_telegram("❌ 종목 못 가져옴")
        return

    total = len(tickers)
    success = 0
    valid = 0

    A, B, C = [], [], []

    start = time.time()

    with ThreadPoolExecutor(max_workers=15) as ex:
        futures = [ex.submit(analyze, t) for t in tickers]

        for f in as_completed(futures):
            r, ok = f.result()

            if ok:
                success += 1

            if not r:
                continue

            valid += 1

            if r["score"] >= 60 and r["ready"] and r["strong_A"]:
                A.append(r)
            elif r["score"] >= 55 and r["ready"]:
                B.append(r)
            else:
                C.append(r)

    elapsed = round(time.time() - start, 1)

    # ==========================================
    # 📩 결과
    # ==========================================
    msg = f"<b>📊 확률형 + A필터 스캐너</b>\n"
    msg += f"📅 {date}\n"
    msg += f"📈 전체: {total} / 성공: {success} / 유효: {valid}\n"
    msg += f"⏱ {elapsed}초\n\n"

    msg += "<b>🔥 A급 (고확률)</b>\n"
    msg += "\n".join([f"{x['name']} ({x['score']})" for x in A[:5]]) if A else "없음"

    msg += "\n\n<b>👀 B급 (유력)</b>\n"
    msg += ", ".join([x['name'] for x in B[:10]]) if B else "없음"

    msg += "\n\n<b>🌱 C급 (초기)</b>\n"
    msg += ", ".join([x['name'] for x in C[:10]]) if C else "없음"

    send_telegram(msg)

    print(f"✅ 완료 A:{len(A)} B:{len(B)} C:{len(C)}")

# ==========================================
# ▶ 실행
# ==========================================
if __name__ == "__main__":
    run()