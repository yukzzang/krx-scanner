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
        requests.post(url, json={
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }, timeout=10)
    except Exception as e:
        print("텔레그램 오류:", e)

# ==========================================
# 📊 티커 수집 (안정화)
# ==========================================
def get_tickers_info():
    for i in range(1, 7):
        target_date = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
        try:
            nm_k = stock.get_market_ticker_name("KOSPI")
            nm_q = stock.get_market_ticker_name("KOSDAQ")

            if not nm_k:
                continue

            ticker_to_name = {**nm_k, **nm_q}

            list_k = stock.get_market_ticker_list(market="KOSPI")[:500]
            list_q = stock.get_market_ticker_list(market="KOSDAQ")[:700]

            combined = []
            for t in list_k:
                combined.append({"ticker": t, "name": ticker_to_name.get(t, t)})
            for t in list_q:
                combined.append({"ticker": t, "name": ticker_to_name.get(t, t)})

            print(f"📡 {len(combined)}개 종목 로드 완료 (기준일: {target_date})")
            return combined, target_date

        except Exception as e:
            print("날짜 재시도:", target_date)

    return [], ""

# ==========================================
# 📊 점수 계산
# ==========================================
def calculate_score(df):

    if len(df) < 60:
        return 0, 0, 0

    close = df['종가'].values
    vol = df['거래량'].values
    curr = float(close[-1])

    score = 0

    # 거래량
    avg_vol = np.mean(vol[-21:-1]) + 1e-9
    v_ratio = vol[-1] / avg_vol

    if 0.1 < v_ratio < 1.8:
        score += 25
    elif v_ratio < 2.5:
        score += 15

    # 이평선
    m5, m20, m60 = np.mean(close[-5:]), np.mean(close[-20:]), np.mean(close[-60:])
    gap = max(m5, m20, m60) / (min(m5, m20, m60) + 1e-9)

    if gap < 1.06:
        score += 20
    elif gap < 1.10:
        score += 10

    # 추세
    if m60 >= np.mean(close[-65:-5]):
        score += 15

    # 위치
    h60 = np.max(close[-60:])
    if curr > h60 * 0.65:
        score += 15
    elif curr > h60 * 0.50:
        score += 10

    # 변동성
    r10 = (np.max(close[-10:]) - np.min(close[-10:])) / (curr + 1e-9)
    if r10 < 0.20:
        score += 15
    elif r10 < 0.35:
        score += 10

    # 상승 압력
    if close[-1] >= close[-5]:
        score += 10

    entry = float(np.max(close[-10:]) * 1.005)
    stop = float(np.min(close[-10:]) * 0.98)

    return score, entry, stop

# ==========================================
# 🔍 종목 분석 (재시도 포함)
# ==========================================
def analyze_ticker(item, target_date):

    for _ in range(2):  # 재시도 2회
        try:
            start_date = (datetime.strptime(target_date, "%Y%m%d") - timedelta(days=150)).strftime("%Y%m%d")
            df = stock.get_market_ohlcv_by_date(start_date, target_date, item['ticker'])

            if df.empty or len(df) < 60:
                return None

            score, entry, stop = calculate_score(df)
            curr = float(df['종가'].iloc[-1])

            h5 = float(df['종가'].iloc[-5:].max())
            is_break = curr >= h5 * 0.92

            return {
                "name": item['name'],
                "ticker": item['ticker'],
                "price": curr,
                "score": score,
                "entry": entry,
                "stop": stop,
                "breakout": is_break
            }

        except:
            time.sleep(0.2)

    return None

# ==========================================
# 🚀 메인 실행
# ==========================================
def run_scanner():

    start_time = time.time()

    items, target_date = get_tickers_info()

    if not items:
        send_telegram("❌ 종목 로딩 실패")
        return

    print(f"🚀 {len(items)}개 종목 스캔 시작")

    A, B, C = [], [], []

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(analyze_ticker, it, target_date) for it in items]

        for idx, future in enumerate(as_completed(futures)):
            res = future.result()
            if not res:
                continue

            if res["score"] >= 60 and res["breakout"]:
                A.append(res)
            elif res["score"] >= 50:
                B.append(res)
            elif res["score"] >= 40:
                C.append(res)

            if (idx + 1) % 100 == 0:
                print(f"📊 진행률: {idx+1}/{len(items)}")

    # 정렬
    A.sort(key=lambda x: x['score'], reverse=True)
    B.sort(key=lambda x: x['score'], reverse=True)
    C.sort(key=lambda x: x['score'], reverse=True)

    # 결과 메시지
    msg = f"<b>📊 [실전 매집 스캐너]</b>\n📅 {target_date}\n\n"

    msg += "<b>🔥 A급</b>\n"
    if A:
        for i in A[:7]:
            msg += f"• <b>{i['name']}</b> ({i['score']})\n"
    else:
        msg += "없음\n"

    msg += "\n\n<b>👀 B급</b>\n"
    msg += ", ".join([x['name'] for x in B[:12]]) if B else "없음"

    msg += "\n\n<b>🌱 C급</b>\n"
    msg += ", ".join([x['name'] for x in C[:15]]) if C else "없음"

    send_telegram(msg)

    print(f"✅ 완료 | A:{len(A)} B:{len(B)} C:{len(C)} | {int(time.time()-start_time)}초")

# ==========================================
if __name__ == "__main__":
    run_scanner()