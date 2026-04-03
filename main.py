import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import os
import time
from pykrx import stock

# ==========================================
# 🔧 환경 변수
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# ==========================================
# 📢 텔레그램 전송
# ==========================================
def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print(f"\n📢 [스캔 리포트]\n{message}")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        })
    except Exception as e:
        print(f"❌ 텔레그램 오류: {e}")

# ==========================================
# 📅 최근 영업일
# ==========================================
def get_recent_business_day():
    for i in range(10):
        d = (datetime.today() - timedelta(days=i)).strftime("%Y%m%d")
        df = stock.get_market_ohlcv(d, d, "005930")
        if not df.empty:
            return d
    return datetime.today().strftime("%Y%m%d")

# ==========================================
# 📊 점수 계산
# ==========================================
def calculate_score(close, vol):
    score = 0
    curr_close = close.iloc[-1]

    avg_vol_20 = vol.iloc[-21:-1].mean() + 1e-9
    vol_ratio = vol.iloc[-1] / avg_vol_20

    # 1️⃣ 거래량 (25점)
    if 0.3 < vol_ratio < 0.7:
        score += 25
    elif 0.2 < vol_ratio < 1.0:
        score += 15

    # 2️⃣ 이평선 수렴 (20점)
    ma5 = close.rolling(5).mean().iloc[-1]
    ma20 = close.rolling(20).mean().iloc[-1]
    ma60 = close.rolling(60).mean().iloc[-1]
    ma_gap = max(ma5, ma20, ma60) / min(ma5, ma20, ma60)

    if ma_gap < 1.03:
        score += 20
    elif ma_gap < 1.05:
        score += 10

    # 3️⃣ 추세 (15점)
    ma60_s = close.rolling(60).mean()
    if ma60_s.iloc[-1] >= ma60_s.iloc[-5]:
        score += 15

    # 4️⃣ 위치 (15점)
    high_60 = close.iloc[-60:].max()
    if curr_close > high_60 * 0.85:
        score += 15
    elif curr_close > high_60 * 0.70:
        score += 10

    # 5️⃣ 변동성 축소 (15점)
    range_10 = (close.iloc[-10:].max() - close.iloc[-10:].min()) / curr_close
    if range_10 < 0.05:
        score += 15
    elif range_10 < 0.08:
        score += 10

    # 6️⃣ 상승 압력 (10점)
    if close.iloc[-1] >= close.iloc[-2] >= close.iloc[-3]:
        score += 10

    return score

# ==========================================
# 📍 진입/손절 계산
# ==========================================
def get_trade_levels(close):
    recent_high = close.iloc[-10:].max()
    recent_low = close.iloc[-10:].min()

    entry = recent_high * 1.005
    stop = recent_low * 0.98

    return entry, stop

# ==========================================
# 🚀 메인 스캐너
# ==========================================
def run_scanner():
    print("🚀 등급형 스캐너 시작")

    last_date = get_recent_business_day()
    start_date = (datetime.strptime(last_date, "%Y%m%d") - timedelta(days=150)).strftime("%Y%m%d")

    # 종목 로드
    names = {**stock.get_market_ticker_name("KOSPI"),
             **stock.get_market_ticker_name("KOSDAQ")}

    kospi = stock.get_market_cap(last_date, market="KOSPI") \
        .sort_values(by='시가총액', ascending=False).head(300).index.tolist()

    kosdaq = stock.get_market_cap(last_date, market="KOSDAQ") \
        .sort_values(by='시가총액', ascending=False).head(400).index.tolist()

    tickers = kospi + kosdaq

    A_list, B_list, C_list = [], [], []

    print(f"🔍 {len(tickers)}개 종목 분석 중...")

    for ticker in tickers:
        try:
            df = stock.get_market_ohlcv_by_date(start_date, last_date, ticker)
            if len(df) < 75:
                continue

            close = df['종가'].astype(float)
            vol = df['거래량'].astype(float)

            score = calculate_score(close, vol)
            entry, stop = get_trade_levels(close)

            # 🔥 돌파 직전 필터 (핵심)
            recent_high_5 = close.iloc[-5:].max()
            is_near_breakout = close.iloc[-1] >= recent_high_5 * 0.98

            item = {
                "name": names.get(ticker, ticker),
                "price": close.iloc[-1],
                "score": score,
                "entry": entry,
                "stop": stop
            }

            if score >= 75 and is_near_breakout:
                A_list.append(item)
            elif score >= 65:
                B_list.append(item)
            elif score >= 55:
                C_list.append(item)

            time.sleep(0.02)

        except:
            continue

    # 정렬
    A_list = sorted(A_list, key=lambda x: x['score'], reverse=True)
    B_list = sorted(B_list, key=lambda x: x['score'], reverse=True)
    C_list = sorted(C_list, key=lambda x: x['score'], reverse=True)

    # ==========================================
    # 📢 리포트 생성
    # ==========================================
    msg = f"<b>📊 [등급별 매집 리포트]</b>\n📅 {last_date}\n"
    msg += "━━━━━━━━━━━━━━━━━━\n\n"

    # A급
    msg += "<b>🔥 A급 (즉시 매매)</b>\n"
    if A_list:
        for i in A_list[:5]:
            msg += f"• <b>{i['name']}</b> ({i['score']}점)\n"
            msg += f"  현재: {int(i['price']):,} | 🚀 {int(i['entry']):,} / ⛔ {int(i['stop']):,}\n\n"
    else:
        msg += "없음\n\n"

    # B급
    msg += "<b>👀 B급 (관찰)</b>\n"
    if B_list:
        msg += ", ".join([f"<b>{x['name']}</b>" for x in B_list[:8]]) + "\n\n"
    else:
        msg += "없음\n\n"

    # C급
    msg += "<b>🌱 C급 (매집)</b>\n"
    if C_list:
        msg += ", ".join([x['name'] for x in C_list[:10]])
    else:
        msg += "없음"

    send_telegram(msg)

    print(f"✅ 완료 | A:{len(A_list)} B:{len(B_list)} C:{len(C_list)}")

# ==========================================
# ▶ 실행
# ==========================================
if __name__ == "__main__":
    run_scanner()