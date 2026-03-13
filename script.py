import os
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import time

# 텔레그램 설정 로드
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def get_krx_tickers():
    print("🔎 종목 리스트 수집 중...")
    try:
        url = "https://raw.githubusercontent.com/mrstock/KoreaStockCode/master/KoreaStockCode.csv"
        df = pd.read_csv(url, dtype={'code': str})
        df['full_code'] = np.where(df['market'] == 'KOSPI', df['code'] + ".KS", df['code'] + ".KQ")
        return df['full_code'].tolist()[:350] # IP 차단 방지를 위해 상위 350개만
    except:
        return ["005930.KS", "000660.KS", "035420.KS", "035720.KS"]

def analyze_stock(ticker):
    try:
        df = yf.download(ticker, period="60d", interval="1d", progress=False, timeout=10)
        
        if df is None or df.empty or len(df) < 35:
            return None
        
        # Multi-Index 컬럼 평탄화
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # 'Close' 컬럼이 없으면 스킵
        if 'Close' not in df.columns:
            return None

        # 데이터 추출 및 평탄화
        close = df['Close'].values.flatten()
        last_price = float(close[-1])

        # 주가 1500원 미만 또는 숫자가 아니면 제외
        if last_price < 1500 or np.isnan(last_price):
            return None

        # 지표 계산 (MACD)
        c_ser = pd.Series(close)
        e12 = c_ser.ewm(span=12, adjust=False).mean()
        e26 = c_ser.ewm(span=26, adjust=False).mean()
        macd = e12 - e26
        signal = macd.ewm(span=9, adjust=False).mean()

        # [상태 1] 최근 3일 내 골든크로스 발생
        is_after = any((macd.iloc[i] > signal.iloc[i] and macd.iloc[i-1] <= signal.iloc[i-1]) for i in range(-1, -4, -1))
        
        # [상태 2] 골든크로스 직전 수렴 (간격 축소)
        is_before = False
        if macd.iloc[-1] < signal.iloc[-1]:
            gap_now = signal.iloc[-1] - macd.iloc[-1]
            gap_prev = signal.iloc[-2] - macd.iloc[-2]
            if gap_now < gap_prev:
                is_before = True

        if not (is_after or is_before):
            return None

        # 정배열 확인 (주가 > 20일선)
        sma20 = c_ser.rolling(20).mean().iloc[-1]
        if last_price < sma20:
            return None

        return {
            "ticker": ticker,
            "price": int(last_price),
            "status": "골든크로스" if is_after else "상승수렴"
        }
    except:
        return None

def main():
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("❌ Secrets 설정이 비어있습니다.")
        return

    tickers = get_krx_tickers()
    found = []
    print(f"🚀 {len(tickers)}개 분석 시작...")

    for i, t in enumerate(tickers):
        res = analyze_stock(t)
        if res:
            found.append(res)
            print(f"🎯 포착: {t}")
        
        if i % 30 == 0:
            time.sleep(1)

    if found:
        msg = "🇰🇷 **국내주식 변곡점 알림 (script.py)**\n\n"
        for s in found[:15]:
            msg += f"✅ *{s['ticker']}*\n   - {s['price']:,}원 | {s['status']}\n\n"
        
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})
        print("✅ 전송 성공")
    else:
        print("📭 포착된 종목 없음")

if __name__ == "__main__":
    main()
