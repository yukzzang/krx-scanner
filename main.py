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
# 📊 최근 영업일 데이터 수집 (에러 방지용)
# ==========================================
def get_recent_business_day():
    """데이터가 존재하는 가장 최근 영업일을 반환합니다."""
    for i in range(10):  # 최대 10일 전까지 확인
        target_date = (datetime.today() - timedelta(days=i)).strftime("%Y%m%d")
        try:
            # 해당 날짜에 삼성전자 데이터가 있는지 확인해봅니다
            df = stock.get_market_ohlcv(target_date, target_date, "005930")
            if not df.empty:
                return target_date
        except:
            continue
    return datetime.today().strftime("%Y%m%d")

def get_top_tickers_with_names(kospi_count=400, kosdaq_count=600):
    # 실제 데이터가 있는 날짜를 찾음
    search_date = get_recent_business_day()
    print(f"📅 데이터 조회 기준일: {search_date}")
    
    try:
        # KOSPI 시총 상위
        df_kospi = stock.get_market_cap(search_date, market="KOSPI")
        if df_kospi.empty:
            # 만약 그래도 비어있다면 강제로 인덱스라도 생성 (에러 방지)
            kospi_top = []
        else:
            kospi_top = df_kospi.sort_values(by='시가총액', ascending=False).head(kospi_count).index.tolist()
        
        # KOSDAQ 시총 상위
        df_kosdaq = stock.get_market_cap(search_date, market="KOSDAQ")
        if df_kosdaq.empty:
            kosdaq_top = []
        else:
            kosdaq_top = df_kosdaq.sort_values(by='시가총액', ascending=False).head(kosdaq_count).index.tolist()
        
        # 종목명 매핑
        all_names = {**stock.get_market_ticker_and_name("KOSPI"), **stock.get_market_ticker_and_name("KOSDAQ")}
        
        return kospi_top, kosdaq_top, all_names, search_date
    except Exception as e:
        print(f"❌ 데이터 수집 중 치명적 에러: {e}")
        return [], [], {}, search_date

# ==========================================
# 📈 지표 계산 및 수급 조회 (기존 로직 유지)
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
    bb_width = ((sma20 + 2*std20) - (sma20 - 2*std20)) / (sma20 + 1e-9) # 0 나누기 방지
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
        recent = df.tail(5)
        return recent['기관합계'].sum(), recent['외국인합계'].sum()
    except: return 0, 0

# ==========================================
# 🚀 메인 스캐너
# ==========================================
def run():
    print(f"🚀 스캐너 가동: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    kospi_top, kosdaq_top, name_map, last_date = get_top_tickers_with_names()

    if not kospi_top and not kosdaq_top:
        print("❌ 분석할 티커가 없습니다. 종료합니다.")
        return

    early_hits, breakout_hits = [], []
    start_date = (datetime.strptime(last_date, "%Y%m%d") - timedelta(days=300)).strftime("%Y%m%d")

    # [KOSPI & KOSDAQ 통합 루프]
    markets = [("KOSPI", kospi_top), ("KOSDAQ", kosdaq_top)]
    for market_type, tickers in markets:
        for ticker in tickers:
            try:
                name = name_map.get(ticker, ticker)
                df = stock.get_market_ohlcv_by_date(start_date, last_date, ticker)
                if df.empty or len(df) < 60: continue

                c, h, l, o, v, val, s20, s50, bb_w, adr, v_ma20, val_ma20 = compute_indicators(df)
                inst, foreign = get_institution_flow(ticker, last_date)

                last_c = c.iloc[-1]
                
                if market_type == "KOSPI":
                    pivot = h.iloc[-10:-1].max()
                    if last_c > pivot * 1.01 and v.iloc[-1] > v_ma20.iloc[-1]*1.5 and inst > 500_000_000:
                        entry = int(last_c)
                        stop = int(l.iloc[-5:].min() * 0.98)
                        target = int(entry + (entry - stop)*2)
                        breakout_hits.append({"name": name, "entry": entry, "target": target, "stop": stop})

                elif market_type == "KOSDAQ":
                    if val.iloc[-1] >= 2_000_000_000 and last_c > s50.iloc[-1]:
                        r1 = (h.iloc[-20:-10].max() - l.iloc[-20:-10].min()) / (last_c + 1e-9)
                        r2 = (h.iloc[-10:-3].max() - l.iloc[-10:-3].min()) / (last_c + 1e-9)
                        if r2 < r1 and (inst > 300_000_000 or foreign > 300_000_000):
                            score = 40 if bb_w.iloc[-1] < 0.1 else 0
                            if inst > 0: score += 30
                            if foreign > 0: score += 30
                            if score >= 60:
                                early_hits.append({"name": name, "price": int(last_c), "score": score, "inst": int(inst//1_000_000), "foreign": int(foreign//1_000_000)})

                time.sleep(0.04)
            except: continue

    # 결과 정렬 및 전송
    early_hits = sorted(early_hits, key=lambda x: x['score'], reverse=True)[:10]
    breakout_hits = breakout_hits[:10]

    msg = f"🇰🇷 KRX 1000종목 스캔 ({datetime.now().strftime('%m/%d %H:%M')})\n"
    msg += f"📅 기준일: {last_date}\n\n"
    msg += "🟦 EARLY (VCP+수급)\n"
    msg += "\n".join([f"✨ {e['name']} | {e['price']:,}원 (기:{e['inst']}M 외:{e['foreign']}M)" for e in early_hits]) if early_hits else "포착 없음"
    msg += "\n\n🟥 BREAKOUT (돌파)\n"
    msg += "\n".join([f"🔥 {b['name']} | 진입:{b['entry']:,} 목:{b['target']:,}" for b in breakout_hits]) if breakout_hits else "포착 없음"

    if TELEGRAM_TOKEN and CHAT_ID:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": msg})
    print(msg)

if __name__ == "__main__":
    run()
