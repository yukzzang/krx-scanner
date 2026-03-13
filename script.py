import os
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import time

# 설정 로드
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def get_krx_tickers():
    print("🔎 종목 리스트 수집 중...")
    try:
        url = "https://raw.githubusercontent.com/mrstock/KoreaStockCode/master/KoreaStockCode.csv"
        df = pd.read_csv(url, dtype={'code': str})
        df['full_code'] = np.where(df['market'] == 'KOSPI', df['code'] + ".KS", df['code'] + ".KQ")
        # 과도한 요청으로 인한 차단 방지를 위해 상위 350개만 스캔
        return df['full_code'].tolist()[:350]
    except Exception as e:
        print(f"리스트 로드 에러: {e}")
        return ["005930.KS", "000660.KS", "035420.KS", "035720.KS"]

def analyze_stock(ticker):
    try:
        # 10초 타임아웃 설정
        df = yf.download(ticker, period="60d", interval="1d", progress=False, timeout=10)
        
        if df is None or df.empty or len(df) < 35:
            return None
        
        # [핵심] Multi-Index 컬럼 대응 (에러 1순위 해결)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # 데이터 존재 여부 재확인
        if 'Close' not in df.columns:
            return None

        close = df['Close'].values.flatten()
        last_price = float(close[-1])

        if last_price < 1500 or np.isnan(last_price):
            return None

        # 지표 계산
        c_ser = pd.Series(close)
        e12 = c_ser.ewm(span=12, adjust=False).mean()
        e26 = c_ser.ewm(span=26, adjust=False).mean()
        macd = e12 - e26
        signal = macd.ewm(span=9, adjust=False).mean()

        # MACD 변곡점 판별
        is_after = any((macd.iloc[i] > signal.iloc[i] and macd.iloc[i-1] <= signal.iloc[i-1]) for i in range(-1, -4, -1))
        
        is_before = False
        if macd.iloc[-1] < signal.iloc[-1]:
            # 수렴 여부 (Gap 축소 확인)
            gap_today = signal.iloc[-1] - macd.iloc[-1]
            gap_yesterday = signal.iloc[-2] - macd.iloc[-2]
            if gap_today < gap_yesterday:
                is_before = True

        if not (is_after or is_before):
            return None

        # 20일선 정배열 확인
        sma20 = c_ser.rolling(20).mean().iloc[-1]
        if last_price < sma20:
            return None

        return {
            "ticker": ticker,
            "price": int(last_price),
            "status": "골든크로스" if is_after else "상승수렴"
        }
    except Exception:
        return None

def main():
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("❌ Secrets 설정(TOKEN, ID)을 확인해주세요.")
        return

    tickers = get_krx_tickers()
    found = []
    print(f"🚀 {len(tickers)}개 국내 종목 분석 시작...")

    for i, t in enumerate(tickers):
        res = analyze_stock(t)
        if res:
            found.append(res)
            print(f"🎯 포착: {t}")
        
        # 30개마다 1초 휴식 (IP 차단 방어)
        if i % 30 == 0:
            time.sleep(1)

    if found:
        msg = "🇰🇷 **국내주식 변곡점 포착**\n\n"
        for s in found[:15]:
            msg += f"✅ *{s['ticker']}*\n   - {s['price']:,}원 | {s['status']}\n\n"
        
        send_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(send_url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})
        print("✅ 텔레그램 전송 완료")
    else:
        print("📭 포착된 종목이 없습니다.")

if __name__ == "__main__":
    main()
