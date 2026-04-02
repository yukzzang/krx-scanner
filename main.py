import yfinance as yf
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import os
import time
from pykrx import stock

# ==========================================
# 🔧 환경 변수 (GitHub Secrets 설정 필요)
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# ==========================================
# 📊 종목 데이터 수집
# ==========================================
def get_all_tickers_with_names():
    """코스피/코스닥 전체 종목 코드와 이름을 가져옵니다."""
    try:
        kospi = stock.get_market_ticker_and_name(market="KOSPI")
        kosdaq = stock.get_market_ticker_and_name(market="KOSDAQ")
        return {**kospi, **kosdaq}
    except Exception as e:
        print(f"티커 수집 에러: {e}")
        return {"005930": "삼성전자"}

def get_institution_flow(ticker):
    """최근 5거래일간의 기관 및 외국인 누적 순매수 대금을 가져옵니다."""
    try:
        end_date = datetime.today().strftime("%Y%m%d")
        start_date = (datetime.today() - timedelta(days=12)).strftime("%Y%m%d") # 주말 포함 넉넉히 조회

        df = stock.get_market_trading_value_by_date(start_date, end_date, ticker)
        if df.empty: return 0, 0

        # 최근 5거래일 데이터만 합산
        recent_df = df.tail(5)
        inst = recent_df['기관합계'].sum()
        foreign = recent_df['외국인합계'].sum()

        return inst, foreign
    except:
        return 0, 0

# ==========================================
# 📈 기술적 지표 계산
# ==========================================
def compute_indicators(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    close = df['Close'].astype(float)
    high = df['High'].astype(float)
    low = df['Low'].astype(float)
    volume = df['Volume'].astype(float)
    opened = df['Open'].astype(float)

    value = close * volume
    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    std20 = close.rolling(20).std()
    
    # 변동성 압축 지표 (BB Width)
    bb_width = ((sma20 + 2*std20) - (sma20 - 2*std20)) / sma20
    
    # 일평균 변동률 (ADR)
    atr = (high - low).rolling(14).mean()
    adr = (atr / close) * 100
    
    vol_ma20 = volume.rolling(20).mean()
    val_ma20 = value.rolling(20).mean()

    return close, high, low, volume, opened, value, sma20, sma50, bb_width, adr, vol_ma20, val_ma20

# ==========================================
# 🚀 메인 스캐너 실행
# ==========================================
def run_strategy():
    print(f"🚀 스캐너 가동: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    ticker_map = get_all_tickers_with_names()
    tickers = list(ticker_map.keys())

    early_hits, breakout_hits = [], []

    # 성능과 API 안정성을 위해 상위 300개 종목 우선 스캔 (시총 순)
    for t in tickers[:300]:
        name = ticker_map[t]
        try:
            # yfinance 호환 티커 설정
            yf_ticker = t + ".KS"
            df = yf.download(yf_ticker, period="8mo", progress=False, threads=False)
            if df.empty:
                yf_ticker = t + ".KQ"
                df = yf.download(yf_ticker, period="8mo", progress=False, threads=False)
            
            if df.empty or len(df) < 60: continue

            # 지표 계산
            c, h, l, v, o, val, s20, s50, bb_w, adr, v_ma20, val_ma20 = compute_indicators(df)
            inst, foreign = get_institution_flow(t)
            
            last_price = c.iloc[-1]

            # ------------------------------------------
            # 🟦 EARLY 전략 (VCP + 수급)
            # ------------------------------------------
            # 1. 기본 필터: 거래대금 20억 이상 & 50일선 위 & 20일선 위
            if val.iloc[-1] >= 2_000_000_000 and last_price > s50.iloc[-1] and last_price > s20.iloc[-1]:
                
                # 2. 거래대금 증가 (평균 대비 1.3배)
                if val.iloc[-1] > val_ma20.iloc[-1] * 1.3:
                    
                    # 3. VCP 패턴 (변동성 축소 확인)
                    r1 = (h.iloc[-20:-10].max() - l.iloc[-20:-10].min()) / last_price
                    r2 = (h.iloc[-10:-3].max() - l.iloc[-10:-3].min()) / last_price

                    if r2 < r1:
                        # 4. 강한 수급 (기관 또는 외인 5억 이상 매수)
                        if (inst > 500_000_000) or (foreign > 500_000_000):
                            score = 0
                            if inst > 0: score += 30
                            if foreign > 0: score += 30
                            if bb_w.iloc[-1] < 0.1: score += 40

                            if score >= 60:
                                early_hits.append({
                                    "name": name, "price": int(last_price), "score": score,
                                    "inst": int(inst // 1_000_000), "foreign": int(foreign // 1_000_000)
                                })

            # ------------------------------------------
            # 🟥 BREAKOUT 전략 (전고점 돌파 + 기관수급)
            # ------------------------------------------
            pivot = h.iloc[-10:-1].max() # 최근 10일간의 고점

            # 1. 돌파 여부 확인 (전고점 +1% 돌파 & 양봉 확인)
            if last_price > pivot * 1.01 and last_price > o.iloc[-1]:
                
                # 2. 거래량 및 거래대금 폭발 (평균 대비 1.5배)
                if v.iloc[-1] > v_ma20.iloc[-1] * 1.5 and val.iloc[-1] > val_ma20.iloc[-1] * 1.5:
                    
                    # 3. 기관 수급 필수 (5억 이상)
                    if inst > 500_000_000:
                        entry = int(pivot * 1.01)
                        stop = int(l.iloc[-5:].min() * 0.98)
                        target = int(entry + (entry - stop) * 2)
                        
                        breakout_hits.append({
                            "name": name, "entry": entry, "target": target, "stop": stop
                        })

            time.sleep(0.08) # API 부하 방지
        except:
            continue

    # 결과 정렬 및 출력
    early_hits = sorted(early_hits, key=lambda x: x['score'], reverse=True)[:10]
    breakout_hits = breakout_hits[:10]

    # 📩 텔레그램 메시지 생성
    msg = f"🇰🇷 국장 수급/차트 스캐너 ({datetime.now().strftime('%m/%d %H:%M')})\n\n"

    msg += "🟦 EARLY (에너지 응축)\n"
    if not early_hits:
        msg += "포착된 종목 없음\n"
    else:
        for e in early_hits:
            msg += f"✨ {e['name']} | {e['price']:,}원\n(기관:{e['inst']}M 외인:{e['foreign']}M)\n\n"

    msg += "🟥 BREAKOUT (강력 돌파)\n"
    if not breakout_hits:
        msg += "포착된 종목 없음\n"
    else:
        for b in breakout_hits:
            msg += f"🔥 {b['name']}\n진입:{b['entry']:,} 목표:{b['target']:,}\n손절:{b['stop']:,}\n\n"

    # 메시지 전송
    if TELEGRAM_TOKEN and CHAT_ID:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                      json={"chat_id": CHAT_ID, "text": msg})
    
    print(msg)
    print("✅ 스캔 및 전송 완료")

if __name__ == "__main__":
    run_strategy()
