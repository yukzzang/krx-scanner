import os
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import time
from bs4 import BeautifulSoup

# ==========================================
# 1️⃣ GitHub Secrets 환경 변수 로드
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_ACTUAL_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_ACTUAL_ID")
MIN_SSM_SCORE = 60

# ==========================================
# 2️⃣ 코스피 / 코스닥 종목 수집
# ==========================================
def get_combined_tickers():
    print("🔎 코스피/코스닥 종목 리스트 수집 시작...")
    tickers = []

    base_url = "https://finance.naver.com/sise/sise_market_sum.naver?sosok={}&page={}"

    for market_code in [0, 1]:  # 0: 코스피, 1: 코스닥
        page = 1
        while True:
            url = base_url.format(market_code, page)
            headers = {'User-Agent': 'Mozilla/5.0'}
            resp = requests.get(url, headers=headers)
            soup = BeautifulSoup(resp.text, 'html.parser')
            table = soup.find("table", class_="type_2")
            if table is None: break
            rows = table.find_all("tr")[2:]  # 헤더 제외
            cnt = 0
            for row in rows:
                cols = row.find_all("td")
                if len(cols) < 2: continue
                code_tag = cols[1].find("a")
                if code_tag and 'href' in code_tag.attrs:
                    href = code_tag.attrs['href']
                    code = href.split('code=')[-1]
                    tickers.append(code + ".KS" if market_code == 0 else code + ".KQ")
                    cnt += 1
            if cnt == 0: break
            page += 1
            time.sleep(0.5)

    print(f"🚀 최종 수집된 티커: {len(tickers)}개")
    return tickers

# ==========================================
# 3️⃣ 전략 계산 로직 (기관수급 + MACD + RSI)
# ==========================================
def compute_ssm_strategy(df):
    if df is None or len(df) < 50: return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    close = df['Close'].values.flatten()
    high = df['High'].values.flatten()
    low = df['Low'].values.flatten()
    volume = df['Volume'].values.flatten()
    last_close = float(close[-1])
    day_volume_krw = last_close * volume[-1]

    # --- 기관 수급 지표: OBV ---
    obv = [0]
    for i in range(1, len(close)):
        if close[i] > close[i-1]:
            obv.append(obv[-1] + volume[i])
        elif close[i] < close[i-1]:
            obv.append(obv[-1] - volume[i])
        else:
            obv.append(obv[-1])
    obv_ser = pd.Series(obv)
    obv_ema5 = obv_ser.ewm(span=5).mean()

    # 필수 조건: 기관 수급 (OBV 상승 + 거래대금 7억 원 이상)
    is_institutional_buy = (obv_ser.iloc[-1] > obv_ema5.iloc[-1]) and (day_volume_krw > 700000000)
    if not is_institutional_buy: return None

    close_ser = pd.Series(close)
    # MACD
    ema12 = close_ser.ewm(span=12, adjust=False).mean()
    ema26 = close_ser.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    # RSI
    delta = close_ser.diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rsi = (100 - (100 / (1 + (gain / loss)))).iloc[-1]
    # SMA20, ADR, 거래배수
    sma20 = close_ser.rolling(20).mean().iloc[-1]
    adr = ((pd.Series(high) - pd.Series(low)).rolling(14).mean() / close_ser * 100).iloc[-1]
    vol_ma20 = pd.Series(volume).rolling(20).mean().iloc[-1]
    vol_ratio = volume[-1] / vol_ma20 if vol_ma20 > 0 else 0

    # MACD 골든크로스 최근 3일
    is_macd_gc = False
    for i in range(-1, -4, -1):
        if (macd.iloc[i] > signal.iloc[i]) and (macd.iloc[i-1] <= signal.iloc[i-1]):
            is_macd_gc = True
            break
    if not is_macd_gc: return None
    if not (20 <= rsi <= 65) or last_close < sma20: return None

    # 점수 산정
    score = 50
    if is_institutional_buy: score += 10
    if vol_ratio >= 1.5: score += 10
    if vol_ratio >= 2.0: score += 10
    if adr >= 2.5: score += 10
    if rsi >= 45: score += 10

    return {
        "score": score,
        "current": round(last_close, 2),
        "rsi": round(float(rsi), 1),
        "adr": round(float(adr), 2),
        "vol_ratio": round(float(vol_ratio), 2),
        "volume_krw_b": round(day_volume_krw / 100000000, 1)
    }

# ==========================================
# 4️⃣ 메인 실행부
# ==========================================
def main():
    tickers = get_combined_tickers()
    found_stocks = []

    print(f"⏳ 분석 시작 (기관수급 + MACD 골크 + RSI 20-65)...")
    for i, t in enumerate(tickers):
        try:
            df = yf.download(t, period="60d", interval="1d", progress=False)
            if df.empty: continue
            result = compute_ssm_strategy(df)
            if result and result["score"] >= MIN_SSM_SCORE:
                found_stocks.append({"ticker": t, **result})
                print(f"🎯 포착: {t} | 점수: {result['score']} | 대금: {result['volume_krw_b']}억 원")
        except: continue
        if i % 50 == 0: print(f"진행: {i}/{len(tickers)}...")

    if found_stocks:
        found_stocks.sort(key=lambda x: x['score'], reverse=True)
        msg = "🚀 **기관수급 & MACD 골든크로스 포착**\n\n"
        for s in found_stocks[:15]:
            msg += f"✅ *{s['ticker']}* ({s['score']}점)\n"
            msg += f"   - 현재가: {s['current']} | 거래대금: {s['volume_krw_b']}억 원\n"
            msg += f"   - RSI: {s['rsi']} | ADR: {s['adr']}% | 거래배수: {s['vol_ratio']}x\n\n"

        if TELEGRAM_TOKEN != "YOUR_ACTUAL_TOKEN":
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            payload = {"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}
            res = requests.post(url, json=payload)
            if res.status_code == 200:
                print("✅ 텔레그램 메시지 전송 완료")
            else:
                print(f"❌ 전송 실패: {res.text}")
        else:
            print("\n[알림] 토큰 설정이 없어 콘솔에 출력합니다.")
            print(msg)
    else:
        print("📭 조건에 맞는 종목이 없습니다.")

if __name__ == "__main__":
    main()
