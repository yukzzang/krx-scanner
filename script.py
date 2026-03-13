import os
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import time

# 텔레그램 설정 로드 (GitHub Secrets)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def get_krx_tickers():
    """
    가장 안정적인 깃허브 원격 저장소의 종목 리스트 활용
    """
    print("🔎 종목 리스트 수집 시작...")
    try:
        # 이 URL은 GitHub Actions 환경에서도 차단 없이 아주 잘 읽힙니다.
        url = "https://raw.githubusercontent.com/mrstock/KoreaStockCode/master/KoreaStockCode.csv"
        df = pd.read_csv(url, dtype={'code': str})
        
        # 시장에 따른 티커 생성 (.KS 또는 .KQ)
        df['ticker'] = np.where(df['market'] == 'KOSPI', df['code'] + ".KS", df['code'] + ".KQ")
        
        # IP 차단 방지를 위해 상위 300개만 우선 스캔
        tickers = df['ticker'].tolist()[:300]
        print(f"🚀 {len(tickers)}개 종목 로드 완료")
        return tickers
    except Exception as e:
        print(f"⚠️ 리스트 로딩 실패 ({e}). 비상용 리스트를 사용합니다.")
        return ["005930.KS", "000660.KS", "035420.KS", "035720.KS", "005380.KS", "068270.KS"]

def analyze_stock(ticker):
    try:
        # 데이터 다운로드 (타임아웃 설정으로 무한 대기 방지)
        df = yf.download(ticker, period="60d", interval="1d", progress=False, timeout=10)
        
        if df is None or df.empty or len(df) < 35:
            return None
        
        # Multi-Index 컬럼 평탄화 (최신 yfinance 대응)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        close = df['Close'].values.flatten()
        last_price = float(close[-1])

        # 주가 1500원 미만 제외
        if last_price < 1500 or np.isnan(last_price):
            return None

        # 지표 계산 (MACD)
        c_ser = pd.Series(close)
        e12 = c_ser.ewm(span=12, adjust=False).mean()
        e26 = c_ser.ewm(span=26, adjust=False).mean()
        macd = e12 - e26
        signal = macd.ewm(span=9, adjust=False).mean()

        # 골든크로스 판별 (최근 3일 이내 혹은 직전 수렴)
        is_after = any((macd.iloc[i] > signal.iloc[i] and macd.iloc[i-1] <= signal.iloc[i-1]) for i in range(-1, -4, -1))
        
        is_before = False
        if macd.iloc[-1] < signal.iloc[-1]:
            gap_today = signal.iloc[-1] - macd.iloc[-1]
            gap_yesterday = signal.iloc[-2] - macd.iloc[-2]
            if gap_today < gap_yesterday:
                is_before = True

        if not (is_after or is_before):
            return None

        # 정배열 필터 (주가 > 20일선)
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
        print("❌ TELEGRAM_TOKEN 또는 TELEGRAM_CHAT_ID 환경변수가 없습니다.")
        return

    tickers = get_krx_tickers()
    found = []

    for i, t in enumerate(tickers):
        res = analyze_stock(t)
        if res:
            found.append(res)
            print(f"🎯 포착: {t}")
        
        # 30개마다 1초 휴식 (IP 차단 방어)
        if i % 30 == 0:
            time.sleep(1)

    if found:
        msg = "🇰🇷 **국내주식 MACD 변곡점**\n\n"
        for s in found[:15]:
            msg += f"✅ *{s['ticker']}*\n   - {s['price']:,}원 | {s['status']}\n\n"
        
        try:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                          json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})
            print("✅ 전송 완료")
        except Exception as e:
            print(f"❌ 전송 실패: {e}")
    else:
        print("📭 오늘 조건에 맞는 종목이 없습니다.")

if __name__ == "__main__":
    main()
