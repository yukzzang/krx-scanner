import os
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import time

# 1️⃣ 설정 (GitHub Secrets)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_ACTUAL_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_ACTUAL_ID")

def get_krx_tickers():
    """
    야후 파이낸스에서 한국 종목을 검색하기 위한 티커 리스트 생성
    (가장 안정적인 KOSPI 200 + KOSDAQ 150 위주로 먼저 시도)
    """
    print("🔎 종목 리스트 생성 중...")
    # 외부 사이트 접속 에러를 피하기 위해, 주요 종목 300개를 직접 생성하거나 
    # 데이터가 확실한 경로만 사용합니다.
    try:
        # 가벼운 깃허브 저장소의 리스트 활용
        url = "https://raw.githubusercontent.com/mrstock/KoreaStockCode/master/KoreaStockCode.csv"
        df = pd.read_csv(url, dtype={'code': str})
        
        # 시장 구분(KOSPI/KOSDAQ)에 따른 접미사 부여
        df['full_code'] = np.where(df['market'] == 'KOSPI', df['code'] + ".KS", df['code'] + ".KQ")
        return df['full_code'].tolist()[:350] # IP 차단 방지를 위해 350개로 제한
    except:
        # 위 주소가 막힐 경우를 대비한 시가총액 최상위 비상 리스트
        return ["005930.KS", "000660.KS", "035420.KS", "035720.KS", "005380.KS", "068270.KS"]

def compute_ssm(ticker):
    try:
        # 타임아웃을 10초로 늘려 GitHub Actions의 느린 네트워크 대응
        df = yf.download(ticker, period="50d", interval="1d", progress=False, timeout=10)
        if df.empty or len(df) < 30: return None
        
        # MultiIndex 컬럼 제거 (최신 yfinance 대응)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        close = df['Close'].values.flatten()
        last_price = float(close[-1])

        # 주가 1500원 필터
        if last_price < 1500: return None

        # MACD 계산
        close_ser = pd.Series(close)
        ema12 = close_ser.ewm(span=12, adjust=False).mean()
        ema26 = close_ser.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()

        # 골든크로스 판별 (최근 3일내 발생 혹은 직전 수렴)
        is_after = any((macd.iloc[i] > signal.iloc[i] and macd.iloc[i-1] <= signal.iloc[i-1]) for i in range(-1, -4, -1))
        
        is_before = False
        if macd.iloc[-1] < signal.iloc[-1]:
            gap_today = signal.iloc[-1] - macd.iloc[-1]
            gap_yesterday = signal.iloc[-2] - macd.iloc[-2]
            if gap_today < gap_yesterday:
                is_before = True

        if not (is_after or is_before): return None

        # 정배열 필터 (주가 > 20일선)
        sma20 = close_ser.rolling(20).mean().iloc[-1]
        if last_price < sma20: return None

        return {
            "ticker": ticker,
            "price": int(last_price),
            "status": "골든크로스 이후" if is_after else "직전(수렴)"
        }
    except Exception as e:
        return None

def main():
    tickers = get_krx_tickers()
    found = []
    print(f"🚀 {len(tickers)}개 종목 분석 시작...")

    for i, t in enumerate(tickers):
        res = compute_ssm(t)
        if res:
            found.append(res)
            print(f"🎯 포착: {t}")
        
        # 20종목마다 1초 휴식 (GitHub 환경에서 차단 방지 핵심)
        if i % 20 == 0:
            time.sleep(1)

    if found:
        msg = "🇰🇷 **국내주식 MACD 변곡점**\n\n"
        for s in found[:15]:
            msg += f"✅ *{s['ticker']}*\n   - {s['price']:,}원 | {s['status']}\n\n"
        
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    else:
        print("📭 포착된 종목이 없습니다.")

if __name__ == "__main__":
    main()
