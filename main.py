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
# 📊 종목명 매핑 및 시총 상위 티커 수집
# ==========================================
def get_top_tickers_with_names(kospi_count=400, kosdaq_count=600):
    today = datetime.today().strftime("%Y%m%d")
    
    # KOSPI 시총 상위
    df_kospi = stock.get_market_cap(today, market="KOSPI")
    kospi_top = df_kospi.sort_values(by='시가총액', ascending=False).head(kospi_count).index.tolist()
    
    # KOSDAQ 시총 상위
    df_kosdaq = stock.get_market_cap(today, market="KOSDAQ")
    kosdaq_top = df_kosdaq.sort_values(by='시가총액', ascending=False).head(kosdaq_count).index.tolist()
    
    # 종목명 매핑 딕셔너리
    all_names = {**stock.get_market_ticker_and_name("KOSPI"), **stock.get_market_ticker_and_name("KOSDAQ")}
    
    return kospi_top, kosdaq_top, all_names

# ==========================================
# 📈 지표 계산 (Vectorized)
# ==========================================
def compute_indicators(df):
    close = df['종가'].astype(float)
    high = df['고가'].astype(float)
    low = df['저가'].astype(float)
    opened = df['시가'].astype(float)
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

    return close, high, low, opened, volume, value, sma20, sma50, bb_width, adr, vol_ma20, val_ma20

def get_institution_flow(ticker):
    end_date = datetime.today().strftime("%Y%m%d")
    start_date = (datetime.today() - timedelta(days=10)).strftime("%Y%m%d")
    try:
        df = stock.get_market_trading_value_by_date(start_date, end_date, ticker)
        if df.empty: return 0, 0
        recent = df.tail(5)
        return recent['기관합계'].sum(), recent['외국인합계'].sum()
    except: return 0, 0

# ==========================================
# 🚀 메인 스캐너
# ==========================================
def run():
    print(f"🚀 스캐너 가동: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    kospi_top, kosdaq_top, name_map = get_top_tickers_with_names()

    early_hits, breakout_hits = [], []
    start_date = (datetime.today() - timedelta(days=300)).strftime("%Y%m%d")
    end_date = datetime.today().strftime("%Y%m%d")

    # [KOSPI & KOSDAQ 통합 루프]
    for market_type, tickers in [("KOSPI", kospi_top), ("KOSDAQ", kosdaq_top)]:
        for ticker in tickers:
            try:
                name = name_map.get(ticker, ticker)
                df = stock.get_market_ohlcv_by_date(start_date, end_date, ticker)
                if df.empty or len(df) < 60: continue

                c, h, l, o, v, val, s20, s50, bb_w, adr, v_ma20, val_ma20 = compute_indicators(df)
                inst, foreign = get_institution_flow(ticker)

                last_c = c.iloc[-1]
                
                # --- 🟥 BREAKOUT 로직 (코스피 위주) ---
                if market_type == "KOSPI":
                    pivot = h.iloc[-10:-1].max()
                    if last_c > pivot * 1.01 and v.iloc[-1] > v_ma20.iloc[-1]*1.5 and inst > 500_000_000:
                        entry = int(last_c)
                        stop = int(l.iloc[-5:].min() * 0.98)
                        target = int(entry + (entry - stop)*2)
                        breakout_hits.append({"name": name, "entry": entry, "target": target, "stop": stop})

                # --- 🟦 EARLY 로직 (코스닥 위주) ---
                if market_type == "KOSDAQ":
                    if val.iloc[-1] >= 2_000_000_000 and last_c > s50.iloc[-1]:
                        r1 = (h.iloc[-20:-10].max() - l.iloc[-20:-10].min()) / last_c
                        r2 = (h.iloc[-10:-3].max() - l.iloc[-10:-3].min()) / last_c
                        if r2 < r1 and (inst > 300_000_000 or foreign > 300_000_000):
                            score = 40 if bb_w.iloc[-1] < 0.1 else 0
                            if inst > 0: score += 30
                            if foreign > 0: score += 30
                            if score >= 60:
                                early_hits.append({"name": name, "price": int(last_c), "score": score, "inst": int(inst//1_000_000), "foreign": int(foreign//1_000_000)})

                time.sleep(0.04) # API 안정성
            except: continue

    # 메시지 전송
    early_hits = sorted(early_hits, key=lambda x: x['score'], reverse=True)[:10]
    breakout_hits = breakout_hits[:10]

    msg = f"🇰🇷 KRX 1000종목 스캔 ({datetime.now().strftime('%m/%d %H:%M')})\n\n"
    msg += "🟦 EARLY (VCP+수급)\n"
    msg += "\n".join([f"✨ {e['name']} | {e['price']:,}원 (기:{e['inst']}M 외:{e['foreign']}M)" for e in early_hits]) if early_hits else "포착 없음"
    msg += "\n\n🟥 BREAKOUT (돌파)\n"
    msg += "\n".join([f"🔥 {b['name']} | 진입:{b['entry']:,} 목:{b['target']:,}" for b in breakout_hits]) if breakout_hits else "포착 없음"

    if TELEGRAM_TOKEN and CHAT_ID:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": msg})
    print(msg)

if __name__ == "__main__":
    run()
