import os
import yfinance as yf
import pandas as pd
import requests
import time
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==================================
# 환경 변수
# ==================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")  # workflow와 일치
MIN_SCORE = 60

# ==================================
# 1️⃣ 티커 수집
# ==================================
def get_combined_tickers():
    tickers=[]
    base="https://finance.naver.com/sise/sise_market_sum.naver?sosok={}&page={}"
    for market in [0,1]:
        page=1
        while True:
            url=base.format(market,page)
            r=requests.get(url,headers={'User-Agent':'Mozilla/5.0'})
            soup=BeautifulSoup(r.text,"html.parser")
            table=soup.find("table",class_="type_2")
            if table is None: break
            rows=table.find_all("tr")[2:]
            cnt=0
            for row in rows:
                cols=row.find_all("td")
                if len(cols)<2: continue
                a=cols[1].find("a")
                if a:
                    code=a["href"].split("code=")[-1]
                    ticker=code+".KS" if market==0 else code+".KQ"
                    tickers.append(ticker)
                    cnt+=1
            if cnt==0: break
            page+=1
            time.sleep(0.2)
    print("총 종목:",len(tickers))
    return tickers

# ==================================
# 2️⃣ 전략 계산 (MACD + RSI + 거래대금 등)
# ==================================
def compute_strategy(df):
    if df is None or len(df)<60: return None
    if isinstance(df.columns,pd.MultiIndex):
        df.columns=df.columns.get_level_values(0)

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]
    price = close.iloc[-1]
    value = price*volume.iloc[-1]

    if value < 1_000_000_000: return None  # 거래대금 10억 이상

    # MACD 골든크로스
    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    macd = ema12-ema26
    signal = macd.ewm(span=9).mean()
    if not (macd.iloc[-1]>signal.iloc[-1] and macd.iloc[-2]<=signal.iloc[-2]):
        return None

    # RSI
    delta = close.diff()
    gain = (delta.where(delta>0,0)).rolling(14).mean()
    loss = (-delta.where(delta<0,0)).rolling(14).mean()
    rsi = 100-(100/(1+(gain/loss)))
    rsi = rsi.iloc[-1]
    if not (30<=rsi<=65): return None

    # SMA20, SMA60
    sma20 = close.rolling(20).mean().iloc[-1]
    sma60 = close.rolling(60).mean().iloc[-1]
    if price < sma20 or sma20 < sma60: return None

    # 거래량
    vol_ratio = volume.iloc[-1]/volume.rolling(20).mean().iloc[-1]
    if vol_ratio < 1.3: return None

    # 점수
    score = 60
    if vol_ratio >= 1.5: score += 10
    if rsi >= 50: score += 10
    if value >= 5_000_000_000: score += 10

    return {"score": score, "price": round(price,2), "rsi": round(rsi,1),
            "vol": round(vol_ratio,2), "value": round(value/100000000,1)}

# ==================================
# 3️⃣ 종목 분석 (ThreadPool)
# ==================================
def analyze_ticker(ticker):
    try:
        df = yf.download(ticker, period="120d", interval="1d", progress=False)
        if df.empty: return None
        result = compute_strategy(df)
        if result: return {"ticker": ticker, **result}
    except: return None

# ==================================
# 4️⃣ 텔레그램 발송
# ==================================
def send_telegram(msg):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[알림] Telegram token 또는 chat_id가 없습니다.")
        print(msg)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg}  # Markdown 없이 안전
    res = requests.post(url, json=payload)
    print(f"Telegram status: {res.status_code}, response: {res.text}")

# ==================================
# 5️⃣ 메인
# ==================================
def main():
    tickers = get_combined_tickers()
    results = []

    print("분석 시작...")
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = [executor.submit(analyze_ticker, t) for t in tickers]
        for future in as_completed(futures):
            r = future.result()
            if r:
                results.append(r)
                print("포착:", r["ticker"])

    if len(results)==0:
        send_telegram("📭 조건에 맞는 종목이 없습니다.")
        return

    results.sort(key=lambda x: x["score"], reverse=True)
    msg = "🚀 전략 포착 종목\n\n"
    for s in results[:20]:
        msg += f"✅ {s['ticker']} ({s['score']}점) | 가격 {s['price']} | 거래대금 {s['value']}억 | RSI {s['rsi']} | 거래량 {s['vol']}x\n"

    print(msg)
    send_telegram(msg)

if __name__=="__main__":
    main()
