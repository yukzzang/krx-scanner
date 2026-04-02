import yfinance as yf
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
# 📊 티커 분리
# ==========================================
def get_tickers_split():
    kospi = stock.get_market_ticker_and_name(market="KOSPI")
    kosdaq = stock.get_market_ticker_and_name(market="KOSDAQ")
    return kospi, kosdaq

# ==========================================
# 💰 기관/외인 수급 (5일)
# ==========================================
def get_institution_flow(ticker):
    try:
        end = datetime.today().strftime("%Y%m%d")
        start = (datetime.today() - timedelta(days=12)).strftime("%Y%m%d")

        df = stock.get_market_trading_value_by_date(start, end, ticker)
        if df.empty:
            return 0, 0

        df = df.tail(5)
        inst = df['기관합계'].sum()
        foreign = df['외국인합계'].sum()

        return inst, foreign
    except:
        return 0, 0

# ==========================================
# 📈 지표
# ==========================================
def compute_indicators(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    c = df['Close'].astype(float)
    h = df['High'].astype(float)
    l = df['Low'].astype(float)
    v = df['Volume'].astype(float)
    o = df['Open'].astype(float)

    val = c * v

    sma20 = c.rolling(20).mean()
    sma50 = c.rolling(50).mean()

    std20 = c.rolling(20).std()
    bb_width = ((sma20 + 2*std20) - (sma20 - 2*std20)) / sma20

    atr = (h - l).rolling(14).mean()
    adr = (atr / c) * 100

    vol_ma20 = v.rolling(20).mean()
    val_ma20 = val.rolling(20).mean()

    return c, h, l, v, o, val, sma20, sma50, bb_width, adr, vol_ma20, val_ma20

# ==========================================
# 🚀 메인 실행
# ==========================================
def run():
    print(f"🚀 실행: {datetime.now()}")

    kospi_map, kosdaq_map = get_tickers_split()

    kospi_tickers = list(kospi_map.keys())[:200]
    kosdaq_tickers = list(kosdaq_map.keys())[:500]

    early_hits = []
    breakout_hits = []

    # ==========================================
    # 🟥 KOSPI (BREAKOUT 중심)
    # ==========================================
    for t in kospi_tickers:
        name = kospi_map[t]

        try:
            df = yf.download(t + ".KS", period="8mo", progress=False, threads=False)
            if df.empty or len(df) < 60:
                continue

            c, h, l, v, o, val, s20, s50, bb_w, adr, v_ma20, val_ma20 = compute_indicators(df)
            inst, foreign = get_institution_flow(t)

            last = c.iloc[-1]
            pivot = h.iloc[-10:-1].max()

            # 🔥 강한 돌파
            if last > pivot * 1.01 and last > o.iloc[-1]:

                if v.iloc[-1] > v_ma20.iloc[-1] * 1.5 and val.iloc[-1] > val_ma20.iloc[-1] * 1.5:

                    if inst > 500_000_000:

                        entry = int(pivot * 1.01)
                        stop = int(l.iloc[-5:].min() * 0.98)
                        target = int(entry + (entry - stop) * 2)

                        breakout_hits.append({
                            "name": name,
                            "entry": entry,
                            "target": target,
                            "stop": stop
                        })

            time.sleep(0.05)

        except:
            continue

    # ==========================================
    # 🟦 KOSDAQ (EARLY 중심)
    # ==========================================
    for t in kosdaq_tickers:
        name = kosdaq_map[t]

        try:
            df = yf.download(t + ".KQ", period="8mo", progress=False, threads=False)
            if df.empty or len(df) < 60:
                continue

            c, h, l, v, o, val, s20, s50, bb_w, adr, v_ma20, val_ma20 = compute_indicators(df)
            inst, foreign = get_institution_flow(t)

            last = c.iloc[-1]

            if val.iloc[-1] >= 2_000_000_000 and last > s50.iloc[-1] and last > s20.iloc[-1]:

                if val.iloc[-1] > val_ma20.iloc[-1] * 1.3:

                    r1 = (h.iloc[-20:-10].max() - l.iloc[-20:-10].min()) / last
                    r2 = (h.iloc[-10:-3].max() - l.iloc[-10:-3].min()) / last

                    if r2 < r1:

                        if (inst > 300_000_000) or (foreign > 300_000_000):

                            score = 0
                            if inst > 0: score += 30
                            if foreign > 0: score += 30
                            if bb_w.iloc[-1] < 0.1: score += 40

                            if score >= 60:
                                early_hits.append({
                                    "name": name,
                                    "price": int(last),
                                    "score": score,
                                    "inst": int(inst // 1_000_000),
                                    "foreign": int(foreign // 1_000_000)
                                })

            time.sleep(0.05)

        except:
            continue

    # ==========================================
    # 📊 정렬
    # ==========================================
    early_hits = sorted(early_hits, key=lambda x: x['score'], reverse=True)[:15]
    breakout_hits = breakout_hits[:10]

    # ==========================================
    # 📩 메시지
    # ==========================================
    msg = f"🇰🇷 국장 스캐너 ({datetime.now().strftime('%m/%d %H:%M')})\n\n"

    msg += "🟥 KOSPI BREAKOUT\n"
    if not breakout_hits:
        msg += "없음\n"
    for b in breakout_hits:
        msg += f"🔥 {b['name']}\n진입:{b['entry']:,} 목표:{b['target']:,} 손절:{b['stop']:,}\n\n"

    msg += "🟦 KOSDAQ EARLY\n"
    if not early_hits:
        msg += "없음\n"
    for e in early_hits:
        msg += f"✨ {e['name']} | {e['price']:,}원\n기관:{e['inst']}M 외인:{e['foreign']}M\n\n"

    # ==========================================
    # 📤 전송
    # ==========================================
    if TELEGRAM_TOKEN and CHAT_ID:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": msg}
        )

    print(msg)
    print("✅ 완료")

# ==========================================
if __name__ == "__main__":
    run()