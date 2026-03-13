import os
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import time

# 설정 로드
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_ID")

def get_krx_tickers():
    # 가장 안정적인 상장사 리스트 경로
    url = "https://raw.githubusercontent.com/mrstock/KoreaStockCode/master/KoreaStockCode.csv"
    try:
        df = pd.read_csv(url, dtype={'code': str})
        # 티커 생성 로직 보강
        df['full_code'] = np.where(df['market'] == 'KOSPI', df['code'] + ".KS", df['code'] + ".KQ")
        return df['full_code'].tolist()[:300] # 상위 300개만 스캔 (차단 방지)
    except:
        return ["005930.KS", "000660.KS", "035420.KS", "035720.KS"]

def analyze_stock(ticker):
    try:
        # 데이터 가져오기 (기간을 넉넉히 60일)
        df = yf.download(ticker, period="60d", interval="1d", progress=False, timeout=15)
        
        if df.empty or len(df) < 35: return None
        
        # [중요] MultiIndex 컬럼 제거
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # 데이터 평탄화 (yfinance 최신버전 대응)
        close = df['Close'].values.flatten()
        last_price = float(close[-1])

        if last_price < 1500: return None # 1500원 미만 제외

        # MACD 계산
        c_ser = pd.Series(close)
        e12 = c_ser.ewm(span=12, adjust=False).mean()
        e26 = c_ser.ewm(span=26, adjust=False).mean()
        macd = e12 - e26
        signal = macd.ewm(span=9, adjust=False).mean()

        # 조건 1: 최근 3일 내 골든크로스
        is_after = any((macd.iloc[i] > signal.iloc[i] and macd.iloc[i-1] <= signal.iloc[i-1]) for i in range(-1, -4, -1))
        
        # 조건 2: 직전 수렴 (데드크로스 중 간격 축소)
        is_before = False
        if macd.iloc[-1] < signal.iloc[-1]:
            if (signal.iloc[-1] - macd.iloc[-1]) < (signal.iloc[-2] - macd.iloc[-2]):
                is_before = True

        if not (is_after or is_before): return None

        # 조건 3: 주가 > 20일선
        sma20 = c_ser.rolling(20).mean().iloc[-1]
        if last_price < sma20: return None

        return {
            "ticker": ticker,
            "price": int(last_price),
            "status": "골든크로스 발생" if is_after else "상승임박(수렴)"
        }
    except Exception as e:
        print(f"Error analyzing {ticker}: {e}")
        return None

def main():
    tickers = get_krx_tickers()
    found = []
    print(f"🚀 {len(tickers)}개 국내 종목 분석 시작...")

    for i, t in enumerate(tickers):
        res = analyze_stock(t)
        if res:
            found.append(res)
            print(f"🎯 포착: {t}")
        
        if i % 20 == 0: time.sleep(1) # IP 차단 방지

    if found:
        msg = "🇰🇷 **국내주식 변곡점 알림**\n\n"
        for s in found[:15]:
            msg += f"✅ *{s['ticker']}*\n   - {s['price']:,}원 | {s['status']}\n\n"
        
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    else:
        print("📭 포착된 종목이 없습니다.")

if __name__ == "__main__":
    main()
