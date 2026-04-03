import pandas as pd
import numpy as np
import requests
import os
import time
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
from pykrx import stock
from datetime import datetime, timedelta

# ==========================================
# 🔧 환경 변수
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram(message):
    print(f"\n[텔레그램 전송 시도...]\n{message}")
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("❌ 토큰 또는 ID가 없습니다.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        res = requests.post(url, json={
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }, timeout=15)
        if res.status_code == 200:
            print("✅ 텔레그램 전송 성공!")
        else:
            print(f"❌ 전송 실패: {res.text}")
    except Exception as e:
        print(f"❌ 연결 오류: {e}")

# ==========================================
# 📅 최근 영업일 찾기 (가장 중요)
# ==========================================
def get_valid_tickers():
    # 오늘부터 거꾸로 10일간 뒤져서 데이터가 나오는 날을 찾음
    for i in range(0, 10):
        target_date = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
        try:
            # 해당 날짜의 코스피 리스트가 있는지 확인
            kospi_list = stock.get_market_ticker_list(target_date, market="KOSPI")
            if len(kospi_list) > 100:
                print(f"✅ 유효 날짜 발견: {target_date} (종목 수: {len(kospi_list)})")
                
                # 종목명 사전 만들기
                nm_k = stock.get_market_ticker_name("KOSPI")
                nm_q = stock.get_market_ticker_name("KOSDAQ")
                ticker_to_name = {**nm_k, **nm_q}

                kosdaq_list = stock.get_market_ticker_list(target_date, market="KOSDAQ")
                
                combined = []
                # 코스피/코스닥 상위 500개씩 총 1000개 구성
                for t in kospi_list[:500]:
                    combined.append({"ticker": t + ".KS", "name": ticker_to_name.get(t, t)})
                for t in kosdaq_list[:500]:
                    combined.append({"ticker": t + ".KQ", "name": ticker_to_name.get(t, t)})
                
                return combined, target_date
        except:
            continue
    return [], ""

# ==========================================
# 📊 점수 계산 (안정화)
# ==========================================
def calculate_score(df):
    try:
        # yfinance 멀티인덱스 컬럼 대응
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        close = df['Close'].astype(float)
        vol = df['Volume'].astype(float)
        if len(df) < 60: return 0, 0, 0

        curr_p = float(close.iloc[-1])
        score = 0

        # 거래량 (25점)
        avg_v = vol.iloc[-21:-1].mean() + 1e-9
        v_ratio = vol.iloc[-1] / avg_v
        if 0.2 < v_ratio < 1.2: score += 25
        elif v_ratio < 2.0: score += 15

        # 이평선 수렴 (20점)
        m5, m20, m60 = close.rolling(5).mean().iloc[-1], close.rolling(20).mean().iloc[-1], close.rolling(60).mean().iloc[-1]
        gap = max(m5, m20, m60) / (min(m5, m20, m60) + 1e-9)
        if gap < 1.05: score += 20
        elif gap < 1.08: score += 10

        # 추세/위치 (30점)
        if close.rolling(60).mean().iloc[-1] >= close.rolling(60).mean().iloc[-5]: score += 15
        if curr_p > close.iloc[-60:].max() * 0.75: score += 15

        # 변동성 (15점)
        r10 = (close.iloc[-10:].max() - close.iloc[-10:].min()) / (curr_p + 1e-9)
        if r10 < 0.12: score += 15
        elif r10 < 0.20: score += 10

        # 상승압력 (10점)
        if close.iloc[-1] >= close.iloc[-3]: score += 10

        entry = float(close.iloc[-10:].max() * 1.005)
        stop = float(close.iloc[-10:].min() * 0.98)
        return score, entry, stop
    except: return 0, 0, 0

# ==========================================
# 🔍 개별 종목 분석
# ==========================================
def analyze_ticker(item):
    try:
        # 야후 차단 방지용 미세 지연
        time.sleep(0.05)
        df = yf.download(item['ticker'], period="8mo", interval="1d", progress=False, show_errors=False)
        if df.empty or len(df) < 60: return None

        score, entry, stop = calculate_score(df)
        if score < 40: return None

        close_val = float(df['Close'].iloc[-1])
        h5 = float(df['Close'].iloc[-5:].max())
        is_break = close_val >= h5 * 0.95

        return {
            "name": item['name'], "ticker": item['ticker'].split('.')[0],
            "price": close_val, "score": score, "entry": entry, "stop": stop, "breakout": is_break
        }
    except: return None

# ==========================================
# 🚀 메인 실행
# ==========================================
def run_scanner():
    print("🚀 스캐너 가동...")
    tickers, target_date = get_valid_tickers()
    
    if not tickers:
        send_telegram("❌ 종목 리스트를 가져오지 못했습니다. 날짜 오류 의심.")
        return

    A, B, C = [], [], []
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(analyze_ticker, it) for it in tickers]
        for idx, future in enumerate(as_completed(futures)):
            r = future.result()
            if not r: continue

            if r["score"] >= 65 and r["breakout"]: A.append(r)
            elif r["score"] >= 55: B.append(r)
            elif r["score"] >= 45: C.append(r)

            if (idx + 1) % 100 == 0:
                print(f"📊 분석 중: {idx + 1}/{len(tickers)}...")

    elapsed = round(time.time() - start_time, 1)

    # 메시지 생성
    msg = f"<b>📊 [매집 스캐너 리포트]</b>\n📅 기준: {target_date}\n⏱ 소요: {elapsed}초\n\n"
    
    msg += "<b>🔥 A급 (즉시)</b>\n"
    if A:
        for x in A[:6]:
            msg += f"• {x['name']} ({x['score']}점)\n  {int(x['price']):,} -> 목표 {int(x['entry']):,}\n"
    else: msg += "없음\n"

    msg += "\n<b>👀 B급 (관찰)</b>\n"
    msg += ", ".join([f"<b>{x['name']}</b>" for x in B[:10]]) if B else "없음"

    msg += "\n\n<b>🌱 C급 (매집)</b>\n"
    msg += ", ".join([x['name'] for x in C[:15]]) if C else "없음"

    send_telegram(msg)
    print(f"✅ 작업 완료! A:{len(A)} B:{len(B)} C:{len(C)}")

if __name__ == "__main__":
    run_scanner()
