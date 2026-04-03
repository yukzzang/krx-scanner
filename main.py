import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import os
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
from pykrx import stock
import time

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
        requests.post(url, json={
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }, timeout=10)
    except Exception as e:
        print("텔레그램 오류:", e)

# ==========================================
# 📊 티커 수집 (1000개)
# ==========================================
def get_tickers_info():
    date = (datetime.now() - timedelta(days=2)).strftime("%Y%m%d")

    nm_k = stock.get_market_ticker_name("KOSPI")
    nm_q = stock.get_market_ticker_name("KOSDAQ")
    ticker_to_name = {**nm_k, **nm_q}

    cap_k = stock.get_market_cap(date, market="KOSPI")
    cap_q = stock.get_market_cap(date, market="KOSDAQ")

    list_k = cap_k.sort_values('시가총액', ascending=False).head(400).index.tolist()
    list_q = cap_q.sort_values('시가총액', ascending=False).head(600).index.tolist()

    combined = []
    for t in list_k:
        combined.append({"ticker": f"{t}.KS", "name": ticker_to_name.get(t, t)})
    for t in list_q:
        combined.append({"ticker": f"{t}.KQ", "name": ticker_to_name.get(t, t)})

    print(f"📡 총 {len(combined)}개 종목 준비 완료")
    return combined

# ==========================================
# 📊 점수 계산
# ==========================================
def calculate_score(close, vol):
    if len(close) < 60:
        return 0, 0, 0

    curr = close[-1]
    score = 0

    avg_vol = np.mean(vol[-21:-1]) + 1e-9
    v_ratio = vol[-1] / avg_vol

    if 0.1 < v_ratio < 1.5: score += 25
    elif v_ratio < 2.5: score += 15

    m5 = np.mean(close[-5:])
    m20 = np.mean(close[-20:])
    m60 = np.mean(close[-60:])

    gap = max(m5, m20, m60) / (min(m5, m20, m60) + 1e-9)
    if gap < 1.05: score += 20
    elif gap < 1.08: score += 10

    if m60 >= np.mean(close[-65:-5]): score += 15

    h60 = np.max(close[-60:])
    if curr > h60 * 0.70: score += 15
    elif curr > h60 * 0.55: score += 10

    r10 = (np.max(close[-10:]) - np.min(close[-10:])) / (curr + 1e-9)
    if r10 < 0.15: score += 15
    elif r10 < 0.25: score += 10

    if close[-1] >= close[-5]: score += 10

    entry = np.max(close[-10:]) * 1.005
    stop = np.min(close[-10:]) * 0.98

    return score, entry, stop

# ==========================================
# 🔥 배치 다운로드
# ==========================================
def fetch_batch(tickers):
    try:
        data = yf.download(
            tickers=tickers,
            period="6mo",
            interval="1d",
            group_by="ticker",
            progress=False,
            threads=False
        )
        return data
    except Exception as e:
        print("배치 실패:", e)
        return None

# ==========================================
# 🔍 배치 분석
# ==========================================
def analyze_batch(batch_items):

    tickers = [x['ticker'] for x in batch_items]
    data = fetch_batch(tickers)

    results = []

    if data is None:
        return results

    for item in batch_items:
        try:
            t = item['ticker']

            if t not in data:
                continue

            df = data[t].dropna()
            if df.empty:
                continue

            close = df['Close'].values
            vol = df['Volume'].values

            score, entry, stop = calculate_score(close, vol)
            curr = close[-1]

            h5 = np.max(close[-5:])
            is_break = curr >= h5 * 0.93

            results.append({
                "name": item['name'],
                "ticker": t.split('.')[0],
                "price": curr,
                "score": score,
                "entry": entry,
                "stop": stop,
                "breakout": is_break
            })

        except:
            continue

    return results

# ==========================================
# 🚀 메인
# ==========================================
def run_scanner():

    print("🚀 배치 스캐너 시작")

    items = get_tickers_info()

    # 🔥 배치 쪼개기 (50개씩)
    batch_size = 50
    batches = [items[i:i+batch_size] for i in range(0, len(items), batch_size)]

    A, B, C = [], [], []

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(analyze_batch, b) for b in batches]

        for future in as_completed(futures):
            results = future.result()

            for res in results:
                if res["score"] >= 65 and res["breakout"]:
                    A.append(res)
                elif res["score"] >= 55:
                    B.append(res)
                elif res["score"] >= 45:
                    C.append(res)

    # 정렬
    A.sort(key=lambda x: x['score'], reverse=True)
    B.sort(key=lambda x: x['score'], reverse=True)
    C.sort(key=lambda x: x['score'], reverse=True)

    # 📢 리포트
    msg = f"<b>📊 [배치 스캐너 결과]</b>\n📅 {datetime.now().strftime('%Y-%m-%d')}\n\n"

    msg += "<b>🔥 A급</b>\n"
    msg += "\n".join([f"{x['name']} ({x['score']})" for x in A[:5]]) if A else "없음"

    msg += "\n\n<b>👀 B급</b>\n"
    msg += ", ".join([x['name'] for x in B[:10]]) if B else "없음"

    msg += "\n\n<b>🌱 C급</b>\n"
    msg += ", ".join([x['name'] for x in C[:15]]) if C else "없음"

    send_telegram(msg)

    print(f"✅ 완료 | A:{len(A)} B:{len(B)} C:{len(C)}")

# ==========================================
# ▶ 실행
# ==========================================
if __name__ == "__main__":
    run_scanner()