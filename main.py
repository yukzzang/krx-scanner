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
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_ACTUAL_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_ACTUAL_ID")
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
# 2️⃣ OBV 다이버전스
# ==================================
def obv_divergence(close,volume):
    obv=[0]
    for i in range(1,len(close)):
        if close.iloc[i]>close.iloc[i-1]:
            obv.append(obv[-1]+volume.iloc[i])
        elif close.iloc[i]<close.iloc[i-1]:
            obv.append(obv[-1]-volume.iloc[i])
        else:
            obv.append(obv[-1])
    obv=pd.Series(obv)
    price_range=(close[-10:].max()-close[-10:].min())/close[-10:].mean()
    if price_range>0.07: return False
    if obv.iloc[-1]<=obv.iloc[-10]: return False
    return True

# ==================================
# 3️⃣ ATR contraction
# ==================================
def atr_contraction(high,low):
    atr=(high-low).rolling(14).mean()
    if atr.iloc[-1]>atr.iloc[-10]: return False
    return True

# ==================================
# 4️⃣ OBV EMA 상승
# ==================================
def obv_trend(close,volume):
    obv=[0]
    for i in range(1,len(close)):
        if close.iloc[i]>close.iloc[i-1]:
            obv.append(obv[-1]+volume.iloc[i])
        elif close.iloc[i]<close.iloc[i-1]:
            obv.append(obv[-1]-volume.iloc[i])
        else:
            obv.append(obv[-1])
    obv=pd.Series(obv)
    obv_ema=obv.ewm(span=10).mean()
    if obv.iloc[-1]<obv_ema.iloc[-1]: return False
    return True

# ==================================
# 5️⃣ 전략 계산
# ==================================
def compute_strategy(df):
    if df is None or len(df)<90: return None
    if isinstance(df.columns,pd.MultiIndex):
        df.columns=df.columns.get_level_values(0)

    close=df["Close"]
    high=df["High"]
    low=df["Low"]
    volume=df["Volume"]
    price=close.iloc[-1]
    value=price*volume.iloc[-1]

    # 거래대금
    if value<1_000_000_000: return None

    # MACD
    ema12=close.ewm(span=12).mean()
    ema26=close.ewm(span=26).mean()
    macd=ema12-ema26
    signal=macd.ewm(span=9).mean()
    if not (macd.iloc[-1]>signal.iloc[-1] and macd.iloc[-2]<=signal.iloc[-2]): return None

    # RSI
    delta=close.diff()
    gain=(delta.where(delta>0,0)).rolling(14).mean()
    loss=(-delta.where(delta<0,0)).rolling(14).mean()
    rsi=100-(100/(1+(gain/loss)))
    rsi=rsi.iloc[-1]
    if not (30<=rsi<=65): return None

    # 이동평균
    sma20=close.rolling(20).mean().iloc[-1]
    sma60=close.rolling(60).mean().iloc[-1]
    if price<sma20 or sma20<sma60: return None

    # ADR
    adr=((high-low).rolling(14).mean()/close*100).iloc[-1]
    if adr<3: return None

    # 거래량
    vol_ratio=volume.iloc[-1]/volume.rolling(20).mean().iloc[-1]
    if vol_ratio<1.3: return None

    # OBV divergence
    if not obv_divergence(close,volume): return None

    # ATR contraction
    if not atr_contraction(high,low): return None

    # OBV EMA 상승
    if not obv_trend(close,volume): return None

    # 점수
    score=60
    if vol_ratio>=1.5: score+=10
    if adr>=4: score+=10
    if rsi>=50: score+=10

    return {
        "score":score,
        "price":round(price,2),
        "rsi":round(rsi,1),
        "adr":round(adr,2),
        "vol":round(vol_ratio,2),
        "value":round(value/100000000,1)
    }

# ==================================
# 6️⃣ 종목 분석
# ==================================
def analyze_ticker(ticker):
    try:
        df=yf.download(ticker,period="120d",interval="1d",progress=False)
        if df.empty: return None
        result=compute_strategy(df)
        if result: return {"ticker":ticker,**result}
    except: return None

# ==================================
# 7️⃣ 메인
# ==================================
def main():
    tickers=get_combined_tickers()
    results=[]
    print("분석 시작")
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures=[executor.submit(analyze_ticker,t) for t in tickers]
        for future in as_completed(futures):
            r=future.result()
            if r:
                results.append(r)
                print("포착:",r["ticker"])

    if len(results)==0:
        print("조건 종목 없음")
        return

    results.sort(key=lambda x:x["score"],reverse=True)
    msg="🚀 OBV Divergence Scanner\n\n"
    for s in results[:10]:
        msg+=f"✅ {s['ticker']} ({s['score']}점)\n"
        msg+=f"가격 {s['price']} | 거래대금 {s['value']}억\n"
        msg+=f"RSI {s['rsi']} | ADR {s['adr']} | 거래량 {s['vol']}x\n\n"

    print(msg)

    if TELEGRAM_TOKEN:
        url=f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload={"chat_id":CHAT_ID,"text":msg}
        requests.post(url,json=payload)

if __name__=="__main__":
    main()
