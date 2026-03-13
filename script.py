import os
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import time

# ==========================================
# 1️⃣ 환경 변수 설정
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_ACTUAL_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_ACTUAL_ID")
MIN_SSM_SCORE = 60

# ==========================================
# 2️⃣ 한국 종목 리스트 수집 (KOSPI + KOSDAQ)
# ==========================================
def get_krx_tickers():
    print("🔎 KRX 종목 리스트 수집 시작 (KOSPI + KOSDAQ)...")
    try:
        # FinanceDataReader와 유사하게 직접 KRX 상장 종목 리스트를 가져오는 방식
        url = 'https://kind.krx.co.kr/corpoff/corpList.do?method=download&searchType=13'
        df_kospi = pd.read_html(url + '&marketType=stockMkt')[0] # 코스피
        df_kosdaq = pd.read_html(url + '&marketType=kosdaqMkt')[0] # 코스닥
        
        # 종목코드 6자리 포맷팅 및 시장 구분자 추가
        kospi_list = [f"{str(x).zfill(6)}.KS" for x in df_kospi['종목코드']]
        kosdaq_list = [f"{str(x).zfill(6)}.KQ" for x in df_kosdaq['종목코드']]
        
        full_list = kospi_list + kosdaq_list
        print(f"🚀 최종 수집된 한국 종목: {len(full_list)}개")
        return full_list
    except Exception as e:
        print(f"❌ 종목 리스트 수집 실패: {e}")
        return []

# ==========================================
# 3️⃣ 전략 계산 로직 (한국 시장 최적화)
# ==========================================
def compute_ssm_strategy(df):
    # 멀티인덱스 제거 및 데이터 클렌징
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    if df is None or len(df) < 40: return None
    df = df.dropna()

    close = df['Close']
    high = df['High']
    low = df['Low']
    volume = df['Volume']

    last_close = float(close.iloc[-1])
    # 한국 시장 거래대금 기준: 약 50억 원 이상 (환율 1350원 가정 시 약 $3.7M)
    # 기존 $7M(약 95억)은 한국 중소형주에 너무 높을 수 있어 50억 원으로 조정
    day_volume_krw = last_close * volume.iloc[-1]
    
    # 1. OBV (기관 수급 대용) 벡터 계산
    direction = np.sign(close.diff()).fillna(0)
    obv = (direction * volume).cumsum()
    obv_ema5 = obv.ewm(span=5).mean()
    
    # 필수 조건 1: OBV 상향 + 거래대금 50억 이상
    is_institutional_buy = (obv.iloc[-1] > obv_ema5.iloc[-1]) and (day_volume_krw > 5_000_000_000)
    if not is_institutional_buy: return None

    # 2. MACD 계산
    exp1 = close.ewm(span=12, adjust=False).mean()
    exp2 = close.ewm(span=26, adjust=False).mean()
    macd = exp1 - exp2
    signal = macd.ewm(span=9, adjust=False).mean()

    # 3. RSI 계산
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    rsi = (100 - (100 / (1 + rs))).iloc[-1]

    # 4. 기타 지표 (20일선, ADR)
    sma20 = close.rolling(20).mean().iloc[-1]
    adr = ((high - low).rolling(14).mean() / close * 100).iloc[-1]
    vol_ma20 = volume.rolling(20).mean().iloc[-1]
    vol_ratio = volume.iloc[-1] / vol_ma20 if vol_ma20 > 0 else 0

    # [필수 기술적 필터]
    # MACD 3일 내 골든크로스 발생 여부
    is_macd_gc = False
    for i in range(-1, -4, -1):
        if (macd.iloc[i] > signal.iloc[i]) and (macd.iloc[i-1] <= signal.iloc[i-1]):
            is_macd_gc = True
            break
    
    if not is_macd_gc: return None
    if not (20 <= rsi <= 70) or last_close < sma20: return None

    # 점수 산정
    score = 50
    if is_institutional_buy: score += 10
    if vol_ratio >= 1.5: score += 10
    if vol_ratio >= 2.5: score += 10
    if adr >= 3.0: score += 10 # 한국 시장은 변동성이 커서 ADR 기준 상향
    if rsi >= 45: score += 10 

    return {
        "score": score,
        "current": int(last_close),
        "rsi": round(float(rsi), 1),
        "adr": round(float(adr), 2),
        "vol_ratio": round(float(vol_ratio), 2),
        "volume_krw_bn": round(day_volume_krw / 1_000_000_000, 1) # 억 단위
    }

# ==========================================
# 4️⃣ 메인 실행부
# ==========================================
def main():
    tickers = get_krx_tickers()
    found_stocks = []

    print(f"⏳ 한국 시장 분석 시작 (총 {len(tickers)}개 종목)...")
    
    for i, t in enumerate(tickers):
        try:
            # 기간을 60일로 짧게 가져와 속도 개선
            df = yf.download(t, period="60d", interval="1d", progress=False)
            if df.empty: continue
            
            result = compute_ssm_strategy(df)
            if result and result["score"] >= MIN_SSM_SCORE:
                found_stocks.append({"ticker": t, **result})
                print(f"🎯 포착: {t} | 점수: {result['score']} | 대금: {result['volume_krw_bn']}억")
        except: continue
        
        # 100개마다 진행률 표시 및 과도한 요청 방지
        if i % 100 == 0: 
            print(f"진행: {i}/{len(tickers)}...")
            time.sleep(1) # IP 차단 방지용

    # 결과 메시지 생성 및 전송 (생략된 메시지 로직은 동일)
    # ... (기존 텔레그램 전송 코드와 동일하게 구현)
