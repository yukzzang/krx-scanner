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
# 📊 티커 수집 및 시총 상위 N개
# ==========================================
def get_top_tickers(kospi_count=450, kosdaq_count=550):
    today = datetime.today().strftime("%Y%m%d")

    # KOSPI
    kospi_all = stock.get_market_ohlcv_by_date(today, today, market="KOSPI")
    kospi_all.reset_index(inplace=True)
    kospi_all.rename(columns={'티커':'Ticker','종가':'Close','거래량':'Volume','거래대금':'Value'}, inplace=True)
    kospi_all = kospi_all[['Ticker','Close','Volume','Value']].copy()
    kospi_all['시가총액'] = kospi_all['Close'] * kospi_all['Volume']
    kospi_top = kospi_all.sort_values(by='시가총액', ascending=False).head(kospi_count)

    # KOSDAQ
    kosdaq_all = stock.get_market_ohlcv_by_date(today, today, market="KOSDAQ")
    kosdaq_all.reset_index(inplace=True)
    kosdaq_all.rename(columns={'티커':'Ticker','종가':'Close','거래량':'Volume','거래대금':'Value'}, inplace=True)
    kosdaq_all = kosdaq_all[['Ticker','Close','Volume','Value']].copy()
    kosdaq_all['시가총액'] = kosdaq_all['Close'] * kosdaq_all['Volume']
    kosdaq_top = kosdaq_all.sort_values(by='시가총액', ascending=False).head(kosdaq_count)

    return kospi_top, kosdaq_top

# ==========================================
# 📈 지표 계산
# ==========================================
def compute_indicators(df):
    close = df['종가'].astype(float)
    high = df['고가'].astype(float)
    low = df['저가'].astype(float)
    open_ = df['시가'].astype(float)
    volume = df['거래량'].astype(float)

    value = close * volume
    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    std20 = close.rolling(20).std()
    bb_width = ((sma20 + 2*std20) - (sma20 - 2*std20)) / sma20
    atr = (high - low).rolling(14).mean()
    adr = (atr / close) * 100
    vol_ma20 = volume.rolling(20).mean()
    val_ma20 = value.rolling(20).mean()

    return close, high, low, open_, volume, value, sma20, sma50, bb_width, adr, vol_ma20, val_ma20

# ==========================================
# 📊 기관/외인 수급
# ==========================================
def get_institution_flow(ticker):
    end_date = datetime.today().strftime("%Y%m%d")
    start_date = (datetime.today() - timedelta(days=12)).strftime("%Y%m%d")
    df = stock.get_market_trading_value_by_date(start_date, end_date, ticker)
    if df.empty:
        return 0, 0
    recent = df.tail(5)
    inst = recent['기관합계'].sum()
    foreign = recent['외국인합계'].sum()
    return inst, foreign

# ==========================================
# 🚀 메인 스캐너
# ==========================================
def run():
    print(f"🚀 스캐너 실행: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    kospi_top, kosdaq_top = get_top_tickers()

    early_hits, breakout_hits = [], []

    # ---------------------------
    # KOSPI → BREAKOUT 중심
    # ---------------------------
    for idx, row in kospi_top.iterrows():
        ticker = row['Ticker']
        name = ticker  # pykrx에서는 종목명 조회 추가 가능
        try:
            df = stock.get_market_ohlcv_by_date(
                (datetime.today() - timedelta(days=240)).strftime("%Y%m%d"),
                datetime.today().strftime("%Y%m%d"),
                ticker
            )
            if df.empty or len(df) < 50: continue

            c, h, l, o, v, val, s20, s50, bb_w, adr, v_ma20, val_ma20 = compute_indicators(df)
            inst, foreign = get_institution_flow(ticker)

            last_price = c.iloc[-1]
            pivot = h.iloc[-10:-1].max()

            if last_price > pivot * 1.01 and v.iloc[-1] > v_ma20.iloc[-1]*1.5 and val.iloc[-1] > val_ma20.iloc[-1]*1.5 and inst > 500_000_000:
                entry = int(pivot * 1.01)
                stop = int(l.iloc[-5:].min() * 0.98)
                target = int(entry + (entry - stop)*2)
                breakout_hits.append({"name": name, "entry": entry, "target": target, "stop": stop})

            time.sleep(0.03)
        except:
            continue

    # ---------------------------
    # KOSDAQ → EARLY 중심
    # ---------------------------
    for idx, row in kosdaq_top.iterrows():
        ticker = row['Ticker']
        name = ticker
        try:
            df = stock.get_market_ohlcv_by_date(
                (datetime.today() - timedelta(days=240)).strftime("%Y%m%d"),
                datetime.today().strftime("%Y%m%d"),
                ticker
            )
            if df.empty or len(df) < 50: continue

            c, h, l, o, v, val, s20, s50, bb_w, adr, v_ma20, val_ma20 = compute_indicators(df)
            inst, foreign = get_institution_flow(ticker)
            last_price = c.iloc[-1]

            if val.iloc[-1] >= 2_000_000_000 and last_price > s50.iloc[-1] and last_price > s20.iloc[-1]:
                if val.iloc[-1] > val_ma20.iloc[-1]*1.3:
                    r1 = (h.iloc[-20:-10].max() - l.iloc[-20:-10].min()) / last_price
                    r2 = (h.iloc[-10:-3].max() - l.iloc[-10:-3].min()) / last_price
                    if r2 < r1 and (inst > 500_000_000 or foreign > 500_000_000):
                        score = 0
                        if inst > 0: score += 30
                        if foreign > 0: score += 30
                        if bb_w.iloc[-1] < 0.1: score += 40
                        if score >= 60:
                            early_hits.append({"name": name, "price": int(last_price), "score": score, "inst": int(inst//1_000_000), "foreign": int(foreign//1_000_000)})

            time.sleep(0.03)
        except:
            continue

    # ---------------------------
    # 메시지 전송
    # ---------------------------
    early_hits = sorted(early_hits, key=lambda x: x['score'], reverse=True)[:10]
    breakout_hits = breakout_hits[:10]

    msg = f"🇰🇷 KRX 1000종목 스캐너 ({datetime.now().strftime('%m/%d %H:%M')})\n\n"
    msg += "🟦 EARLY (VCP + 수급)\n"
    if not early_hits: msg += "포착된 종목 없음\n"
    else:
        for e in early_hits:
            msg += f"✨ {e['name']} | {e['price']:,}원\n(기관:{e['inst']}M 외인:{e['foreign']}M)\n\n"

    msg += "🟥 BREAKOUT (강력 돌파)\n"
    if not breakout_hits: msg += "포착된 종목 없음\n"
    else:
        for b in breakout_hits:
            msg += f"🔥 {b['name']}\n진입:{b['entry']:,} 목표:{b['target']:,}\n손절:{b['stop']:,}\n\n"

    if TELEGRAM_TOKEN and CHAT_ID:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": msg})

    print(msg)
    print("✅ 스캔 완료 및 텔레그램 전송 완료")

if __name__ == "__main__":
    run()