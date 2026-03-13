import os
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import time

# 1️⃣ 설정 로드
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_ACTUAL_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_ACTUAL_ID")

def get_major_krx_tickers():
    """
    차단 위험이 있는 KRX 사이트 대신, 안정적인 시총 상위권 티커 수동/자동 혼합 방식
    """
    print("🔎 주요 종목 스캔 시작 (KOSPI/KOSDAQ 상위권)...")
    # 주요 대형주 예시 (리스트가 너무 길면 GitHub IP 차단되므로 400~500개가 적당합니다)
    # 실제로는 아래 URL이 가장 안정적입니다.
    try:
        url = "https://raw.githubusercontent.com/mrstock/KoreaStockCode/master/KoreaStockCode.csv"
        df = pd.read_csv(url, dtype={'code': str})
        # 상위 종목 위주로 필터링하거나 전체를 가져옵니다.
        df['ticker'] = df['code'].apply(lambda x: x + ".KS" if x.endswith('0') else x + ".KQ") # 간략화된 규칙
        # 실제로는 데이터프레임의 market 컬럼 활용
        df['full_code'] = np.where(df['market'] == 'KOSPI', df['code'] + ".KS", df['code'] + ".KQ")
        return df['full_code'].tolist()[:500] # 상위 500개만 우선 스캔 (IP 차단 방지)
    except:
        return ["005930.KS", "000660.KS", "035420.KS", "035720.KS", "005380.KS"] # 실패 시 비상 리스트

def compute_ssm_strategy(df):
    if df is None or len(df) < 35: return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    close = df['Close'].values.flatten()
    volume = df['Volume'].values.flatten()
    last_close = float(close[-1])

    if last_close < 1500: return None 

    # MACD 계산
    close_ser = pd.Series(close)
    ema12 = close_ser.ewm(span=12, adjust=False).mean()
    ema26 = close_ser.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()

    # MACD 변곡점 확인 (직전 수렴 혹은 3일내 골든크로스)
    is_after_gc = any((macd.iloc[i] > signal.iloc[i] and macd.iloc[i-1] <= signal.iloc[i-1]) for i in range(-1, -4, -1))
    
    is_before_gc = False
    if macd.iloc[-1] < signal.iloc[-1]:
        if (signal.iloc[-1] - macd.iloc[-1]) < (signal.iloc[-2] - macd.iloc[-2]):
            is_before_gc = True

    if not (is_after_gc or is_before_gc): return None

    # 주가 > 20일선 (정배열 확인)
    sma20 = close_ser.rolling(20).mean().iloc[-1]
    if last_close < sma20: return None

    return {
        "current": int(last_close),
        "status": "골든크로스 이후" if is_after_gc else "직전(수렴)"
    }

def main():
    all_tickers = get_major_krx_tickers()
    found_stocks = []

    print(f"⏳ 총 {len(all_tickers)}개 종목 분석...")
    
    for i, t in enumerate(all_tickers):
        try:
            # 기간을 줄여서 데이터 로딩 속도 최적화
            df = yf.download(t, period="40d", interval="1d", progress=False, timeout=5)
            if df.empty: continue
            
            res = compute_ssm_strategy(df)
            if res:
                found_stocks.append({"ticker": t, **res})
                print(f"🎯 포착: {t}")
            
            # 50종목마다 1초씩 휴식 (GitHub 차단 회피 핵심)
            if i % 50 == 0: time.sleep(1)
        except:
            continue

    if found_stocks:
        msg = "🇰🇷 **국내주식 MACD 변곡점 알림**\n\n"
        for s in found_stocks[:15]:
            msg += f"✅ *{s['ticker']}*\n   - {s['current']:,}원 | {s['status']}\n\n"
        
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    else:
        print("📭 포착된 종목이 없습니다.")

if __name__ == "__main__":
    main()
