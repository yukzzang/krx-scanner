import os
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import time

# ==========================================
# 1️⃣ 환경 변수 및 설정
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_ACTUAL_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_ACTUAL_ID")
MIN_SCORE = 50 

# ==========================================
# 2️⃣ 한국 종목 리스트 수집 (Naver/KRX 대용)
# ==========================================
def get_krx_tickers():
    print("🔎 코스피/코스닥 종목 리스트 수집 시작...")
    # 한국거래소(KRX) 종목 리스트를 가져오는 간단한 방법 (pandas 활용)
    try:
        # 코스피
        url_kospi = 'https://kind.krx.co.kr/corpoff/corpList.do?method=download&searchType=13&marketType=stockMkt'
        kospi_df = pd.read_html(url_kospi, header=0)[0]
        kospi_tickers = kospi_df['종목코드'].apply(lambda x: f"{x:06d}.KS").tolist()

        # 코스닥
        url_kosdaq = 'https://kind.krx.co.kr/corpoff/corpList.do?method=download&searchType=13&marketType=kosdaqMkt'
        kosdaq_df = pd.read_html(url_kosdaq, header=0)[0]
        kosdaq_tickers = kosdaq_df['종목코드'].apply(lambda x: f"{x:06d}.KQ").tolist()
        
        all_tickers = kospi_tickers + kosdaq_tickers
        print(f"🚀 총 {len(all_tickers)}개 종목 수집 완료")
        return all_tickers
    except Exception as e:
        print(f"❌ 종목 리스트 수집 실패: {e}")
        return []

# ==========================================
# 3️⃣ 전략 계산 로직
# ==========================================
def compute_ssm_strategy(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    if df is None or len(df) < 50: return None

    close = df['Close'].values.flatten()
    volume = df['Volume'].values.flatten()
    last_close = float(close[-1])

    # 1. 주가 필터 (1,500원 이상)
    if last_close < 1500: return None

    # 2. 기관 수급 (OBV)
    obv = [0]
    for i in range(1, len(close)):
        if close[i] > close[i-1]: obv.append(obv[-1] + volume[i])
        elif close[i] < close[i-1]: obv.append(obv[-1] - volume[i])
        else: obv.append(obv[-1])
    
    obv_ser = pd.Series(obv)
    obv_ema5 = obv_ser.ewm(span=5).mean()
    is_institutional_buy = obv_ser.iloc[-1] > obv_ema5.iloc[-1]

    # 3. MACD/RSI/SMA 지표
    close_ser = pd.Series(close)
    ema12 = close_ser.ewm(span=12, adjust=False).mean()
    ema26 = close_ser.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()

    delta = close_ser.diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rsi = (100 - (100 / (1 + (gain / loss)))).iloc[-1]
    sma20 = close_ser.rolling(20).mean().iloc[-1]

    # 4. 변곡점 상태 판별 (직전~이후 3일)
    is_after_gc = False
    for i in range(-1, -4, -1):
        if (macd.iloc[i] > signal.iloc[i]) and (macd.iloc[i-1] <= signal.iloc[i-1]):
            is_after_gc = True
            break
    
    is_before_gc = False
    if macd.iloc[-1] < signal.iloc[-1]:
        current_gap = signal.iloc[-1] - macd.iloc[-1]
        prev_gap = signal.iloc[-2] - macd.iloc[-2]
        if current_gap < prev_gap:
            is_before_gc = True

    # 필수 필터링
    if not (is_after_gc or is_before_gc): return None
    if not is_institutional_buy or last_close < sma20: return None

    score = 50
    status = "골든크로스 이후" if is_after_gc else "골든크로스 직전(수렴)"
    if is_after_gc: score += 10
    if 40 <= rsi <= 65: score += 15
    
    return {
        "score": score,
        "current": int(last_close),
        "rsi": round(float(rsi), 1),
        "status": status
    }

# ==========================================
# 4️⃣ 메인 실행
# ==========================================
def main():
    tickers = get_krx_tickers()
    found_stocks = []

    print(f"⏳ 한국 시장 분석 시작...")
    # 한국 종목명 매핑을 위한 리스트 (Kind에서 가져온 정보를 활용하면 좋지만 여기선 간략화)
    
    for i, t in enumerate(tickers):
        try:
            # 기간은 최근 60일치면 충분합니다.
            df = yf.download(t, period="60d", interval="1d", progress=False)
            if df.empty: continue
            
            result = compute_ssm_strategy(df)
            if result:
                found_stocks.append({"ticker": t, **result})
        except: continue
        if i % 100 == 0: print(f"진행 중: {i}/{len(tickers)}...")

    if found_stocks:
        found_stocks.sort(key=lambda x: x['score'], reverse=True)
        msg = "🇰🇷 **국내주식 변곡점 포착 (KOSPI/KOSDAQ)**\n"
        msg += "조건: 주가 1500원↑ + OBV 우상향 + MACD 변곡\n\n"
        
        for s in found_stocks[:20]: # 최대 20개 전송
            market = "코스피" if ".KS" in s['ticker'] else "코스닥"
            msg += f"✅ *{s['ticker']}* ({market} / {s['score']}점)\n"
            msg += f"   - 현재가: {s['current']:,}원 | {s['status']}\n"
            msg += f"   - RSI: {s['rsi']}\n\n"

        if TELEGRAM_TOKEN != "YOUR_ACTUAL_TOKEN":
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                          json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})
        else: print(msg)
    else:
        print("📭 조건에 맞는 국내 종목이 없습니다.")

if __name__ == "__main__":
    main()
