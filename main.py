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
    """텔레그램 메시지 전송 및 결과 로그 출력"""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("❌ 텔레그램 토큰 또는 채팅 ID가 설정되지 않았습니다.")
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    
    try:
        res = requests.post(url, json=payload)
        if res.status_code == 200:
            print(f"✅ 텔레그램 전송 성공!")
        else:
            print(f"❌ 텔레그램 전송 실패: {res.status_code} - {res.text}")
    except Exception as e:
        print(f"❌ 전송 중 에러 발생: {e}")

# 최근 영업일 찾기 로직 (생략 - 이전과 동일)
def get_recent_business_day():
    for i in range(10):
        target_date = (datetime.today() - timedelta(days=i)).strftime("%Y%m%d")
        try:
            df = stock.get_market_ohlcv(target_date, target_date, "005930")
            if not df.empty: return target_date
        except: continue
    return datetime.today().strftime("%Y%m%d")

# 지표 계산 및 수급 로직 (생략 - 이전과 동일)
def compute_indicators(df):
    # ... 이전 코드와 동일 ...
    close = df['종가'].astype(float)
    high = df['고가'].astype(float)
    low = df['저가'].astype(float)
    opened = df['시가'].astype(float)
    volume = df['거래량'].astype(float)
    value = close * volume
    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    std20 = close.rolling(20).std()
    bb_width = ((sma20 + 2*std20) - (sma20 - 2*std20)) / (sma20 + 1e-9)
    atr = (high - low).rolling(14).mean()
    adr = (atr / (close + 1e-9)) * 100
    vol_ma20 = volume.rolling(20).mean()
    val_ma20 = value.rolling(20).mean()
    return close, high, low, opened, volume, value, sma20, sma50, bb_width, adr, vol_ma20, val_ma20

def get_institution_flow(ticker, end_date):
    start_date = (datetime.strptime(end_date, "%Y%m%d") - timedelta(days=12)).strftime("%Y%m%d")
    try:
        df = stock.get_market_trading_value_by_date(start_date, end_date, ticker)
        if df.empty: return 0, 0
        return df['기관합계'].tail(5).sum(), df['외국인합계'].tail(5).sum()
    except: return 0, 0

def run():
    print(f"🚀 스캐너 가동: {datetime.now()}")
    
    # 1. 날짜 및 티커 준비
    last_date = get_recent_business_day()
    print(f"📅 데이터 기준일: {last_date}")
    
    all_names = {**stock.get_market_ticker_and_name("KOSPI"), **stock.get_market_ticker_and_name("KOSDAQ")}
    kospi_top = stock.get_market_cap(last_date, market="KOSPI").sort_values(by='시가총액', ascending=False).head(400).index.tolist()
    kosdaq_top = stock.get_market_cap(last_date, market="KOSDAQ").sort_values(by='시가총액', ascending=False).head(600).index.tolist()

    early_hits, breakout_hits = [], []
    start_search = (datetime.strptime(last_date, "%Y%m%d") - timedelta(days=300)).strftime("%Y%m%d")

    # 2. 루프 실행
    for m_type, tickers in [("KOSPI", kospi_top), ("KOSDAQ", kosdaq_top)]:
        for ticker in tickers:
            try:
                df = stock.get_market_ohlcv_by_date(start_search, last_date, ticker)
                if df.empty or len(df) < 60: continue
                
                c, h, l, o, v, val, s20, s50, bb_w, adr, v_ma20, val_ma20 = compute_indicators(df)
                inst, foreign = get_institution_flow(ticker, last_date)
                last_c = c.iloc[-1]

                if m_type == "KOSPI":
                    pivot = h.iloc[-10:-1].max()
                    # 테스트를 위해 조건을 조금 완화해봅니다 (실제 운영시 다시 강화 가능)
                    if last_c > pivot * 0.99 and v.iloc[-1] > v_ma20.iloc[-1] * 1.2: 
                        breakout_hits.append({"name": all_names.get(ticker, ticker), "entry": int(last_c)})
                
                elif m_type == "KOSDAQ":
                    if val.iloc[-1] >= 1_000_000_000 and last_c > s50.iloc[-1]: # 기준 20억 -> 10억 완화
                        early_hits.append({"name": all_names.get(ticker, ticker), "price": int(last_c)})
                
                time.sleep(0.02)
            except: continue

    # 3. 메시지 구성
    msg = f"🇰🇷 스캔 결과 ({last_date})\n\n"
    
    msg += "🟦 EARLY\n"
    msg += "\n".join([f"- {e['name']}" for e in early_hits[:10]]) if early_hits else "포착 없음\n"
    
    msg += "\n\n🟥 BREAKOUT\n"
    msg += "\n".join([f"- {b['name']}" for b in breakout_hits[:10]]) if breakout_hits else "포착 없음\n"

    # 4. 무조건 전송 (포착 종목이 없어도 상태 보고를 위해 전송)
    send_telegram(msg)

if __name__ == "__main__":
    run()
