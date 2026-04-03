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
# 📢 텔레그램
# ==========================================
def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print(f"\n📢 [로컬 출력]\n{message}")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        res = requests.post(url, json={
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }, timeout=10)

        if res.status_code != 200:
            print(f"❌ 텔레그램 응답 오류: {res.text}")

    except Exception as e:
        print(f"❌ 텔레그램 전송 실패: {e}")

# ==========================================
# 📅 최근 영업일 (강화)
# ==========================================
def get_recent_business_day():
    for i in range(0, 10):
        d = (datetime.today() - timedelta(days=i)).strftime("%Y%m%d")
        try:
            df = stock.get_market_cap(d)
            if df is not None and not df.empty:
                return d
        except:
            continue
    return (datetime.today() - timedelta(days=1)).strftime("%Y%m%d")

# ==========================================
# 📡 시장 데이터 로딩 (재시도 포함)
# ==========================================
def load_market_data(date, max_retry=3):
    for attempt in range(max_retry):
        try:
            kospi_df = stock.get_market_cap(date, market="KOSPI")
            kosdaq_df = stock.get_market_cap(date, market="KOSDAQ")

            if (kospi_df is not None and not kospi_df.empty and '시가총액' in kospi_df.columns and
                kosdaq_df is not None and not kosdaq_df.empty and '시가총액' in kosdaq_df.columns):
                
                return kospi_df, kosdaq_df

        except Exception as e:
            print(f"⚠️ 시장 데이터 로딩 실패 (시도 {attempt+1}): {e}")

        time.sleep(5)  # 재시도 대기

    return None, None

# ==========================================
# 📊 점수 계산
# ==========================================
def calculate_score(close, vol):
    score = 0
    curr_close = close.iloc[-1]

    avg_vol_20 = vol.iloc[-21:-1].mean() + 1e-9
    vol_ratio = vol.iloc[-1] / avg_vol_20

    if 0.3 < vol_ratio < 0.7: score += 25
    elif 0.2 < vol_ratio < 1.0: score += 15

    ma5 = close.rolling(5).mean().iloc[-1]
    ma20 = close.rolling(20).mean().iloc[-1]
    ma60 = close.rolling(60).mean().iloc[-1]
    ma_gap = max(ma5, ma20, ma60) / min(ma5, ma20, ma60)

    if ma_gap < 1.03: score += 20
    elif ma_gap < 1.05: score += 10

    if close.rolling(60).mean().iloc[-1] >= close.rolling(60).mean().iloc[-5]:
        score += 15

    high_60 = close.iloc[-60:].max()
    if curr_close > high_60 * 0.85: score += 15
    elif curr_close > high_60 * 0.70: score += 10

    range_10 = (close.iloc[-10:].max() - close.iloc[-10:].min()) / (curr_close + 1e-9)
    if range_10 < 0.05: score += 15
    elif range_10 < 0.08: score += 10

    if close.iloc[-1] >= close.iloc[-2] >= close.iloc[-3]:
        score += 10

    return score

# ==========================================
# 📍 진입/손절
# ==========================================
def get_trade_levels(close):
    high = close.iloc[-10:].max()
    low = close.iloc[-10:].min()
    return high * 1.005, low * 0.98

# ==========================================
# 🚀 메인 실행
# ==========================================
def run_scanner():
    print("🚀 스캐너 시작")

    last_date = get_recent_business_day()
    print(f"📅 기준일: {last_date}")

    kospi_df, kosdaq_df = load_market_data(last_date)

    if kospi_df is None or kosdaq_df is None:
        send_telegram("❌ 시장 데이터 로딩 실패 (재시도 후에도 실패)")
        return

    start_date = (datetime.strptime(last_date, "%Y%m%d") - timedelta(days=150)).strftime("%Y%m%d")

    names = {**stock.get_market_ticker_name("KOSPI"),
             **stock.get_market_ticker_name("KOSDAQ")}

    tickers = kospi_df.sort_values('시가총액', ascending=False).head(300).index.tolist() + \
              kosdaq_df.sort_values('시가총액', ascending=False).head(400).index.tolist()

    A_list, B_list, C_list = [], [], []

    for ticker in tickers:
        try:
            df = stock.get_market_ohlcv_by_date(start_date, last_date, ticker)
            if len(df) < 75:
                continue

            close = df['종가'].astype(float)
            vol = df['거래량'].astype(float)

            score = calculate_score(close, vol)
            entry, stop = get_trade_levels(close)

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

        except Exception:
            continue

    # ==========================================
    # 📢 결과 메시지 (무조건 전송)
    # ==========================================
    msg = f"<b>📊 [등급별 매집 리포트]</b>\n📅 {last_date}\n"
    msg += "━━━━━━━━━━━━━━━━━━\n\n"

    msg += "<b>🔥 A급 (즉시 매매)</b>\n"
    if A_list:
        for i in sorted(A_list, key=lambda x: x['score'], reverse=True)[:5]:
            msg += f"• <b>{i['name']}</b> ({i['score']}점)\n"
            msg += f"  현재: {int(i['price']):,} | 🚀 {int(i['entry']):,} / ⛔ {int(i['stop']):,}\n\n"
    else:
        msg += "없음\n\n"

    msg += "<b>👀 B급 (관찰)</b>\n"
    msg += ", ".join([f"<b>{x['name']}</b>" for x in B_list[:8]]) if B_list else "없음"
    msg += "\n\n"

    msg += "<b>🌱 C급 (매집)</b>\n"
    msg += ", ".join([x['name'] for x in C_list[:10]]) if C_list else "없음"

    if not A_list and not B_list and not C_list:
        msg += "\n\n⚠️ 오늘은 조건 만족 종목이 없습니다."

    send_telegram(msg)

    print(f"✅ 완료 | A:{len(A_list)} B:{len(B_list)} C:{len(C_list)}")

# ==========================================
# ▶ 실행
# ==========================================
if __name__ == "__main__":
    run_scanner()