import pandas as pd
import numpy as np
import requests
from datetime import datetime
import os
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
from pykrx import stock

# ==========================================
# 🔧 텔레그램
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

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
    except:
        pass

# ==========================================
# 📊 티커 수집 (핵심 안정화)
# ==========================================
def get_tickers():

    try:
        tickers_k = stock.get_market_ticker_list(market="KOSPI")
        tickers_q = stock.get_market_ticker_list(market="KOSDAQ")

        tickers = []

        for t in tickers_k[:500]:
            tickers.append(f"{t}.KS")

        for t in tickers_q[:700]:
            tickers.append(f"{t}.KQ")

        print(f"📡 총 {len(tickers)}개 종목 로드 완료")
        return tickers

    except Exception as e:
        print("❌ 티커 로딩 실패:", e)
        return ["005930.KS"]

# ==========================================
# 📊 점수 계산 (완화 버전)
# ==========================================
def calculate_score(close, vol):

    if len(close) < 60:
        return 0, 0, 0

    curr = close[-1]
    score = 0

    avg_vol = np.mean(vol[-21:-1]) + 1e-9
    v_ratio = vol[-1] / avg_vol

    if 0.1 < v_ratio < 1.8: score += 25
    elif v_ratio < 2.5: score += 15

    m5 = np.mean(close[-5:])
    m20 = np.mean(close[-20:])
    m60 = np.mean(close[-60:])

    gap = max(m5, m20, m60) / (min(m5, m20, m60) + 1e-9)
    if gap < 1.06: score += 20
    elif gap < 1.10: score += 10

    if m60 >= np.mean(close[-65:-5]): score += 15

    h60 = np.max(close[-60:])
    if curr > h60 * 0.65: score += 15
    elif curr > h60 * 0.50: score += 10

    r10 = (np.max(close[-10:]) - np.min(close[-10:])) / curr
    if r10 < 0.18: score += 15
    elif r10 < 0.30: score += 10

    if close[-1] >= close[-5]: score += 10

    entry = np.max(close[-10:]) * 1.005
    stop = np.min(close[-10:]) * 0.98

    return score, entry, stop

# ==========================================
# 🔥 배치 다운로드
# ==========================================
def fetch_batch(tickers):
    try:
        return yf.download(
            tickers=tickers,
            period="6mo",
            interval="1d",
            group_by="ticker",
            progress=False,
            threads=False
        )
    except:
        return None

# ==========================================
# 🚀 실행
# ==========================================
def run_scanner():

    print("🚀 1200종목 실전 스캐너 시작")

    tickers = get_tickers()

    batch_size = 50
    batches = [tickers[i:i+batch_size] for i in range(0, len(tickers), batch_size)]

    A, B, C = [], [], []

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(fetch_batch, b) for b in batches]

        for future in as_completed(futures):
            data = future.result()
            if data is None:
                continue

            for t in data.columns.levels[0]:
                try:
                    df = data[t].dropna()
                    if df.empty:
                        continue

                    close = df['Close'].values
                    vol = df['Volume'].values

                    score, entry, stop = calculate_score(close, vol)
                    curr = close[-1]

                    h5 = np.max(close[-5:])
                    is_break = curr >= h5 * 0.92  # 돌파 완화

                    item = {"ticker": t, "score": score}

                    if score >= 60 and is_break:
                        A.append(item)
                    elif score >= 50:
                        B.append(item)
                    elif score >= 40:
                        C.append(item)

                except:
                    continue

    # 정렬
    A.sort(key=lambda x: x['score'], reverse=True)
    B.sort(key=lambda x: x['score'], reverse=True)
    C.sort(key=lambda x: x['score'], reverse=True)

    # 📢 결과
    msg = f"<b>📊 [1200종목 실전 스캐너]</b>\n📅 {datetime.now().strftime('%Y-%m-%d')}\n\n"

    msg += "<b>🔥 A급</b>\n"
    msg += "\n".join([x['ticker'] for x in A[:7]]) if A else "없음"

    msg += "\n\n<b>👀 B급</b>\n"
    msg += ", ".join([x['ticker'] for x in B[:12]]) if B else "없음"

    msg += "\n\n<b>🌱 C급</b>\n"
    msg += ", ".join([x['ticker'] for x in C[:15]]) if C else "없음"

    send_telegram(msg)

    print(f"✅ 완료 | A:{len(A)} B:{len(B)} C:{len(C)}")

# ==========================================
if __name__ == "__main__":
    run_scanner()