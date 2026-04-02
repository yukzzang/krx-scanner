import yfinance as yf
import pandas as pd
import numpy as np
import requests
from datetime import datetime
import os
import time

# ❗ 중요: import schedule 줄이 있으면 에러 납니다. 삭제하세요.

# ==========================================
# 🔧 환경 변수 (GitHub Secrets)
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def get_kr_tickers():
    tickers_info = []
    try:
        # KOSPI 200 구성 종목
        url = "https://en.wikipedia.org/wiki/KOSPI_200"
        df = pd.read_html(url)[1]
        for _, row in df.iterrows():
            code = str(row['Ticker']).zfill(6) + ".KS"
            name = row['Component']
            tickers_info.append({'ticker': code, 'name': name})
    except:
        tickers_info = [{'ticker': '005930.KS', 'name': '삼성전자'}]
    return tickers_info

def compute_indicators(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    close = df['Close'].astype(float)
    high = df['High'].astype(float)
    low = df['Low'].astype(float)
    volume = df['Volume'].astype(float)
    
    value = close * volume 
    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    std20 = close.rolling(20).std()
    bb_width = ((sma20 + std20 * 2) - (sma20 - std20 * 2)) / sma20
    atr = (high - low).rolling(14).mean()
    adr = (atr / close) * 100
    return close, high, low, volume, value, sma20, sma50, bb_width, atr, adr

def compute_breakout(close, sma50, bb_width, adr, value):
    if len(close) < 50: return 0
    # 국장 기준: 당일 거래대금 50억 이상만 (필요시 조절)
    if value.iloc[-1] < 5_000_000_000: return 0
    
    last = close.iloc[-1]
    is_squeeze = bb_width.iloc[-1] < bb_width.rolling(30).min().iloc[-1] * 1.1
    if not is_squeeze or last < sma50.iloc[-1]: return 0

    score = 30
    if bb_width.iloc[-1] < 0.06: score += 20
    if adr.iloc[-1] < 4: score += 10
    if last > close.rolling(50).max().iloc[-1] * 0.95: score += 20
    return score

# ==========================================
# 🚀 실행 로직 (일회성 실행)
# ==========================================
def run_scanner():
    print(f"🚀 스캔 시작: {datetime.now()}")
    tickers_data = get_kr_tickers()
    results = []

    # 상위 100개 종목 스캔
    for item in tickers_data[:100]: 
        t, name = item['ticker'], item['name']
        try:
            df = yf.download(t, period="8mo", progress=False, threads=False)
            if df.empty or len(df) < 60: continue

            c, h, l, v, val, s20, s50, bb_w, atr, adr = compute_indicators(df)
            score = compute_breakout(c, s50, bb_w, adr, val)
            
            if score > 0:
                results.append({
                    "name": name, "ticker": t, "score": score,
                    "entry": int(h.iloc[-5:].max() * 1.005),
                    "target": int(h.iloc[-5:].max() * 1.15),
                    "stop": int(c.iloc[-1] * 0.94)
                })
            time.sleep(0.1)
        except: continue

    results = sorted(results, key=lambda x: x['score'], reverse=True)[:10]
    
    if not results:
        msg = f"📩 [{datetime.now().strftime('%m/%d')}] 조건 만족 종목 없음"
    else:
        msg = f"🔥 국장 TOP10 ({datetime.now().strftime('%m/%d %H:%M')})\n\n"
        for r in results:
            msg += f"✨ {r['name']} ({r['ticker']})\n"
            msg += f"추천가: {r['entry']:,}원 | 목표: {r['target']:,}원\n\n"

    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                  json={"chat_id": CHAT_ID, "text": msg})
    print("✅ 전송 완료")

if __name__ == "__main__":
    # ❗ 여기도 schedule 관련 함수 호출을 지우고 run_scanner()만 남깁니다.
    run_scanner()
