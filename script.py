import FinanceDataReader as fdr
import pandas as pd
import numpy as np
import requests

# =====================
# 텔레그램 설정
# =====================

TELEGRAM_TOKEN = "8617534523:AAE_xvNamAN3_HtCIoLnMB2lVh5jZ_00JOo"
CHAT_ID = "5087265480"

def send_telegram(msg):

    url=f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    requests.post(url,data={
        "chat_id":CHAT_ID,
        "text":msg
    })


print("KRX Smart Money Scanner 시작")

stocks=fdr.StockListing('KRX')

results=[]

for i,row in stocks.iterrows():

    code=row['Code']
    name=row['Name']

    try:

        df=fdr.DataReader(code)

        if len(df)<120:
            continue

        close=df['Close']
        volume=df['Volume']
        high=df['High']
        low=df['Low']

        price=close.iloc[-1]

        # ----------------
        # 가격 필터
        # ----------------

        if price<1500:
            continue

        # ----------------
        # 거래대금
        # ----------------

        value=price*volume.iloc[-1]

        if value<5000000000:
            continue

        # ----------------
        # 이동평균
        # ----------------

        ma5=close.rolling(5).mean()
        ma20=close.rolling(20).mean()

        if ma5.iloc[-1] < ma20.iloc[-1]:
            continue

        # ----------------
        # 거래량 증가
        # ----------------

        vol5=volume.rolling(5).mean()
        vol20=volume.rolling(20).mean()

        if vol5.iloc[-1] < vol20.iloc[-1]*1.3:
            continue

        # ----------------
        # 상승 제한
        # ----------------

        change20=(close.iloc[-1]/close.iloc[-20]-1)*100

        if change20>20:
            continue

        # ----------------
        # 박스권
        # ----------------

        high20=high[-20:].max()

        if price>high20*0.95:
            continue

        # ----------------
        # RSI 계산
        # ----------------

        delta=close.diff()

        gain=(delta.where(delta>0,0)).rolling(14).mean()
        loss=(-delta.where(delta<0,0)).rolling(14).mean()

        rs=gain/loss

        rsi=100-(100/(1+rs))

        rsi_now=rsi.iloc[-1]

        if rsi_now<30 or rsi_now>55:
            continue

        # ----------------
        # MACD 계산
        # ----------------

        ema12=close.ewm(span=12).mean()
        ema26=close.ewm(span=26).mean()

        macd=ema12-ema26
        signal=macd.ewm(span=9).mean()

        macd_gap=macd.iloc[-1]-signal.iloc[-1]

        # MACD 돌파 직전

        if macd_gap<-0.05:
            continue

        # ----------------
        # 세력 점수
        # ----------------

        score=0

        if vol5.iloc[-1]>vol20.iloc[-1]*1.5:
            score+=2

        if macd_gap>-0.02:
            score+=2

        if 35<rsi_now<50:
            score+=2

        if value>10000000000:
            score+=1

        results.append((score,name,code,price,rsi_now))

    except:

        continue


results=sorted(results,reverse=True)

message="🔥 Smart Money Scanner 결과\n\n"

for r in results[:10]:

    message+=f"{r[1]} ({r[2]})\n"
    message+=f"가격:{r[3]}\n"
    message+=f"RSI:{round(r[4],1)}\n"
    message+=f"Score:{r[0]}\n\n"


print(message)

send_telegram(message)
