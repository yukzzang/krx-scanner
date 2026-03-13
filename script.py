import os
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import time

# ================================
# 텔레그램 설정 로드
# ================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

if not TELEGRAM_TOKEN or not CHAT_ID:
    print("❌ TELEGRAM_TOKEN 또는 TELEGRAM_CHAT_ID가 설정되지 않았습니다.")
    exit(1)

# ================================
# KRX 종목 리스트 가져오기
# ================================
def get_krx_tickers():
    print("🔎 종목 리스트 수집 중...")
    try:
        url = "https://raw.githubusercontent.com/mrstock/KoreaStockCode/master/KoreaStockCode.csv"
        df = pd.read_csv(url, dtype={'code': str})
        df['full_code'] = np.where(df['market'] == 'KOSPI', df['code'] + ".KS", df['code'] + ".KQ")
        return df['full_code'].tolist()[:350]  # 상위 350개만 처리
    except Exception as e:
        print("⚠️ 종목 리스트 로드 실패:", e)
        return ["005930.KS", "000660.KS", "035420.KS", "035720.KS"]  # 기본 종목

# ================================
# 텔레그램 메시지 전송 (재시도 포함)
# ================================
def post_telegram(msg, retries=3, delay=2):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for attempt in range(retries):
        try:
            resp = requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})
            if resp.status_code == 200:
                print("✅ 텔레그램 전송 성공")
                return True
            else:
                print(f"⚠️ 전송 실패: {resp.status_code}, {resp.text}")
        except Exception as e:
            print(f"⚠️ 전송 예외: {e}")
        time.sleep(delay)
    print("❌ 텔레그램 전송 실패")
    return False

# ================================
# 주식 분석 (골든크로스 / 상승수렴)
# ================================
def analyze_stock(ticker, retries=2):
    for attempt in range(retries):
        try:
            df = yf.download(ticker, period="60d", interval="1d", progress=False, timeout=10)
            if df is None or df.empty or len(df) < 35:
                return None

            # MultiIndex 컬럼 평탄화
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            if 'Close' not in df.columns:
                return None

            close = df['Close'].values.flatten()
            last_price = float(close[-1])
            if last_price < 1500 or np.isnan(last_price):
                return None

            # MACD 계산
            c_ser = pd.Series(close)
            e12 = c_ser.ewm(span=12, adjust=False).mean()
            e26 = c_ser.ewm(span=26, adjust=False).mean()
            macd = e12 - e26
            signal = macd.ewm(span=9, adjust=False).mean()

            # 최근 3일 내 골든크로스
            is_after = any((macd.iloc[i] > signal.iloc[i] and macd.iloc[i-1] <= signal.iloc[i-1]) 
                           for i in range(-1, -4, -1))

            # 골든크로스 직전 수렴
            is_before = False
            if macd.iloc[-1] < signal.iloc[-1]:
                gap_now = signal.iloc[-1] - macd.iloc[-1]
                gap_prev = signal.iloc[-2] - macd.iloc[-2]
                if gap_now < gap_prev:
                    is_before = True

            if not (is_after or is_before):
                return None

            # 정배열 확인 (주가 > 20일 이동평균)
            sma20 = c_ser.rolling(20).mean().iloc[-1]
            if last_price < sma20:
                return None

            return {
                "ticker": ticker,
                "price": int(last_price),
                "status": "골든크로스" if is_after else "상승수렴"
            }
        except Exception as e:
            print(f"⚠️ {ticker} 분석 실패: {e}, 재시도 {attempt+1}/{retries}")
            time.sleep(1)
    return None

# ================================
# 메인 실행
# ================================
def main():
    tickers = get_krx_tickers()
    found = []
    print(f"🚀 {len(tickers)}개 종목 분석 시작...")

    for i, t in enumerate(tickers, 1):
        res = analyze_stock(t)
        if res:
            found.append(res)
            print(f"🎯 포착: {t} ({res['status']})")

        # 30개마다 1~2초 쉬어서 API 과부하 방지
        if i % 30 == 0:
            time.sleep(2)

    if found:
        msg = "🇰🇷 **국내주식 변곡점 알림 (script.py)**\n\n"
        for s in found[:15]:
            msg += f"✅ *{s['ticker']}*\n   - {s['price']:,}원 | {s['status']}\n\n"
        post_telegram(msg)
    else:
        print("📭 포착된 종목 없음")

if __name__ == "__main__":
    main()
