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

def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("❌ 텔레그램 설정 누락")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        res = requests.post(url, json={"chat_id": CHAT_ID, "text": message})
        print(f"📡 전송 상태: {res.status_code}")
    except Exception as e:
        print(f"❌ 전송 에러: {e}")

def get_recent_business_day():
    for i in range(10):
        target_date = (datetime.today() - timedelta(days=i)).strftime("%Y%m%d")
        try:
            df = stock.get_market_ohlcv(target_date, target_date, "005930")
            if not df.empty: return target_date
        except: continue
    return datetime.today().strftime("%Y%m%d")

def compute_indicators(df):
    close = df['종가'].astype(float)
    high = df['고가'].astype(float)
    low = df['저가'].astype(float)
    volume = df['거래량'].astype(float)
    value = close * volume
    
    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    std20 = close.rolling(20).std()
    bb_width = ((sma20 + 2*std20) - (sma20 - 2*std20)) / (sma20 + 1e-9)
    vol_ma20 = volume.rolling(20).mean()
    val_ma20 = value.rolling(20).mean()
    
    return close, high, low, volume, value, sma20, sma50, bb_width, vol_ma20, val_ma20

def run():
    print(f"🚀 스캐너 가동: {datetime.now()}")
    last_date = get_recent_business_day()
    print(f"📅 데이터 기준일: {last_date}")
    
    # 함수 이름 수정: get_market_ticker_name
    all_names = {**stock.get_market_ticker_name("KOSPI"), **stock.get_market_ticker_name("KOSDAQ")}
    
    # 변수 정의 확실히 하기
    try:
        kospi_top = stock.get_market_cap(last_date, market="KOSPI").sort_values(by='시가총액', ascending=False).head(400).index.tolist()
        kosdaq_top = stock.get_market_cap(last_date, market="KOSDAQ").sort_values(by='시가총액', ascending=False).head(600).index.tolist()
    except Exception as e:
        print(f"❌ 티커 수집 중 에러: {e}")
        kospi_top, kosdaq_top = [], []

    early_hits, breakout_hits = [], []
    start_search = (datetime.strptime(last_date, "%Y%m%d") - timedelta(days=300)).strftime("%Y%m%d")

    # 루프 시작
    for m_type, tickers in [("KOSPI", kospi_top), ("KOSDAQ", kosdaq_top)]:
        for ticker in tickers:
            try:
                df = stock.get_market_ohlcv_by_date(start_search, last_date, ticker)
                if df.empty or len(df) < 60: continue
                
                c, h, l, v, val, s20, s50, bb_w, v_ma20, val_ma20 = compute_indicators(df)
                
                # 수급 조회 (에러 방지를 위해 간단히)
                df_tr = stock.get_market_trading_value_by_date(
                    (datetime.strptime(last_date, "%Y%m%d") - timedelta(days=7)).strftime("%Y%m%d"), 
                    last_date, ticker
                )
                inst = df_tr['기관합계'].sum() if not df_tr.empty else 0
                
                last_c = c.iloc[-1]

                if m_type == "KOSPI":
                    pivot = h.iloc[-10:-1].max()
                    if last_c > pivot * 1.01 and v.iloc[-1] > v_ma20.iloc[-1] * 1.5 and inst > 500_000_000:
                        breakout_hits.append(f"🔥 {all_names.get(ticker, ticker)} ({int(last_c):,}원)")
                
                elif m_type == "KOSDAQ":
                    if val.iloc[-1] >= 2_000_000_000 and last_c > s50.iloc[-1]:
                        r1 = (h.iloc[-20:-10].max() - l.iloc[-20:-10].min()) / last_c
                        r2 = (h.iloc[-10:-3].max() - l.iloc[-10:-3].min()) / last_c
                        if r2 < r1 and inst > 300_000_000:
                            early_hits.append(f"✨ {all_names.get(ticker, ticker)} ({int(last_c):,}원)")
                
                time.sleep(0.02)
            except: continue

    # 메시지 전송
    msg = f"🇰🇷 국장 스캔 결과 ({last_date})\n\n"
    msg += "🟦 KOSDAQ EARLY (VCP)\n" + ("\n".join(early_hits[:10]) if early_hits else "포착 없음")
    msg += "\n\n🟥 KOSPI BREAKOUT\n" + ("\n".join(breakout_hits[:10]) if breakout_hits else "포착 없음")

    send_telegram(msg)
    print("✅ 모든 작업 완료")

if __name__ == "__main__":
    run()
