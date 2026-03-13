import os
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import time

# 1️⃣ 설정 로드
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_ACTUAL_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_ACTUAL_ID")

def get_krx_tickers():
    print("🔎 국내 종목 리스트 수집 (GitHub 안정화 버전)...")
    tickers = []
    try:
        # 더 안정적인 깃허브 저장소의 상장사 리스트 활용 (KRX 직접 접근 대신)
        url = "https://raw.githubusercontent.com/mrstock/KoreaStockCode/master/KoreaStockCode.csv"
        df = pd.read_csv(url, dtype={'code': str})
        
        for _, row in df.iterrows():
            code = row['code']
            market = row['market'] # KOSPI or KOSDAQ
            suffix = ".KS" if market == "KOSPI" else ".KQ"
            tickers.append(code + suffix)
            
        print(f"🚀 총 {len(tickers)}개 티커 수집 완료")
    except Exception as e:
        print(f"❌ 리스트 수집 실패, 비상용 수단 사용: {e}")
        # 실패 시 최소한의 시가총액 상위 종목이라도 수동 추가 가능
    return tickers

def compute_ssm_strategy(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if len(df) < 50: return None

    close = df['Close'].values.flatten()
    volume = df['Volume'].values.flatten()
    last_close = float(close[-1])

    if last_close < 1500: return None # 1,500원 미만 제외

    # OBV (기관수급)
    obv = [0]
    for i in range(1, len(close)):
        if close[i] > close[i-1]: obv.append(obv[-1] + volume[i])
        elif close[i] < close[i-1]: obv.append(obv[-1] - volume[i])
        else: obv.append(obv[-1])
    obv_ser = pd.Series(obv)
    is_institutional_buy = obv_ser.iloc[-1] > obv_ser.ewm(span=5).mean().iloc[-1]

    # MACD
    close_ser = pd.Series(close)
    ema12 = close_ser.ewm(span=12, adjust=False).mean()
    ema26 = close_ser.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    
    # RSI
    delta = close_ser.diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rsi = (100 - (100 / (1 + (gain / loss)))).iloc[-1]

    # 변곡점 판별
    is_after_gc = any((macd.iloc[i] > signal.iloc[i] and macd.iloc[i-1] <= signal.iloc[i-1]) for i in range(-1, -4, -1))
    
    is_before_gc = False
    if macd.iloc[-1] < signal.iloc[-1]:
        if (signal.iloc[-1] - macd.iloc[-1]) < (signal.iloc[-2] - macd.iloc[-2]):
            is_before_gc = True

    if not (is_after_gc or is_before_gc) or not is_institutional_buy or last_close < close_ser.rolling(20).mean().iloc[-1]:
        return None

    return {
        "current": int(last_close),
        "status": "골든크로스 이후" if is_after_gc else "직전(수렴)",
        "rsi": round(float(rsi), 1)
    }

def main():
    all_tickers = get_krx_tickers()
    found_stocks = []

    # GitHub Actions의 사양과 IP 차단을 고려하여 '상위 1000개' 정도로 제한하거나 
    # 혹은 다운로드 시 chunk를 나누는 것이 좋습니다.
    print(f"⏳ 데이터 분석 시작 (약 {len(all_tickers)}개)...")
    
    for i, t in enumerate(all_tickers):
        try:
            # interval 설정을 통해 서버 부하 방지
            df = yf.download(t, period="60d", interval="1d", progress=False, timeout=10)
            if df.empty: continue
            
            res = compute_ssm_strategy(df)
            if res:
                found_stocks.append({"ticker": t, **res})
                print(f"🎯 포착: {t}")
        except: continue
        
        # 200개마다 2초간 휴식 (IP 차단 방지)
        if i % 200 == 0 and i > 0:
            print(f"--- {i}개 완료, 잠시 대기... ---")
            time.sleep(2)

    if found_stocks:
        msg = "🇰🇷 **국내주식 변곡점 알림**\n\n"
        for s in found_stocks[:20]:
            msg += f"✅ *{s['ticker']}*\n   - {s['current']:,}원 | {s['status']} | RSI: {s['rsi']}\n\n"
        
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    else:
        print("📭 포착 종목 없음")

if __name__ == "__main__":
    main()
