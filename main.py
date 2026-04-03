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
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print(f"\n📢 [텔레그램 미설정]\n{message}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=15)
    except: pass

# ==========================================
# 📅 영업일 기준 티커 수집 (핵심 수정)
# ==========================================
def get_korean_tickers():
    # 오늘부터 거꾸로 7일간 탐색하여 데이터가 있는 날을 찾음
    for i in range(0, 8):
        target_date = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
        try:
            # 해당 날짜의 코스피 리스트 확인
            kospi = stock.get_market_ticker_list(target_date, market="KOSPI")
            if len(kospi) > 100: # 데이터가 정상적으로 있다면
                nm_k = stock.get_market_ticker_name("KOSPI")
                nm_q = stock.get_market_ticker_name("KOSDAQ")
                ticker_to_name = {**nm_k, **nm_q}

                kosdaq = stock.get_market_ticker_list(target_date, market="KOSDAQ")
                
                # 시가총액 순으로 정렬해서 가져오고 싶다면 여기서 추가 로직이 필요하지만, 
                # 일단 리스트의 앞부분 500개씩 추출
                combined = []
                for t in kospi[:500]:
                    combined.append({"ticker": t + ".KS", "name": ticker_to_name.get(t, t)})
                for t in kosdaq[:500]:
                    combined.append({"ticker": t + ".KQ", "name": ticker_to_name.get(t, t)})

                print(f"✅ 티커 확보 성공! 기준일: {target_date}, 총 {len(combined)}개")
                return combined, target_date
        except:
            continue
    
    return [], ""

# ==========================================
# 📊 점수 계산 (yfinance MultiIndex 대응)
# ==========================================
def calculate_score(df):
    try:
        # 최근 yfinance 업데이트로 인한 컬럼 구조 강제 평탄화
        df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]
        close = df['Close'].astype(float)
        vol = df['Volume'].astype(float)

        if len(df) < 70: return 0, 0, 0
        
        curr_p = float(close.iloc[-1])
        score = 0

        # 1. 거래량 (25점)
        avg_v = vol.iloc[-21:-1].mean() + 1e-9
        v_ratio = vol.iloc[-1] / avg_v
        if 0.2 < v_ratio < 1.0: score += 25
        elif v_ratio < 1.5: score += 15

        # 2. 이평선 (20점)
        m5, m20, m60 = close.rolling(5).mean().iloc[-1], close.rolling(20).mean().iloc[-1], close.rolling(60).mean().iloc[-1]
        gap = max(m5, m20, m60) / (min(m5, m20, m60) + 1e-9)
        if gap < 1.04: score += 20
        elif gap < 1.07: score += 10

        # 3. 추세/위치/변동성 (각 15점)
        if close.rolling(60).mean().iloc[-1] >= close.rolling(60).mean().iloc[-5]: score += 15
        if curr_p > close.iloc[-60:].max() * 0.80: score += 15
        
        r10 = (close.iloc[-10:].max() - close.iloc[-10:].min()) / (curr_p + 1e-9)
        if r10 < 0.10: score += 15
        elif r10 < 0.15: score += 10

        # 4. 상승압력 (10점)
        if close.iloc[-1] >= close.iloc[-3]: score += 10

        entry = float(close.iloc[-10:].max() * 1.005)
        stop = float(close.iloc[-10:].min() * 0.98)
        return score, entry, stop
    except: return 0, 0, 0

# ==========================================
# 🔍 종목 분석
# ==========================================
def analyze_ticker(item):
    try:
        # 데이터 차단 방지를 위한 미세 지연 (병렬 실행 시 중요)
        time.sleep(0.05)
        df = yf.download(item['ticker'], period="7mo", interval="1d", progress=False, show_errors=False)
        if df.empty or len(df) < 70: return None

        score, entry, stop = calculate_score(df)
        if score < 40: return None

        # yfinance 구조 대응 후 종가 추출
        close_series = df['Close'].squeeze()
        curr_p = float(close_series.iloc[-1])
        h5 = float(close_series.iloc[-5:].max())
        is_break = curr_p >= h5 * 0.95

        return {
            "name": item['name'], "ticker": item['ticker'].split('.')[0],
            "price": curr_p, "score": score, "entry": entry, "stop": stop, "breakout": is_break
        }
    except: return None

# ==========================================
# 🚀 메인 실행
# ==========================================
def run_scanner():
    print("🚀 1,000종목 병렬 스캐너 가동...")
    items, target_date = get_korean_tickers()
    
    if not items:
        print("❌ 분석할 티커를 찾지 못했습니다.")
        return

    A, B, C = [], [], []
    start_time = time.time()

    # 병렬 처리 (Thread 25개로 안정화)
    with ThreadPoolExecutor(max_workers=25) as executor:
        futures = [executor.submit(analyze_ticker, it) for it in items]
        for idx, future in enumerate(as_completed(futures)):
            r = future.result()
            if not r: continue

            if r["score"] >= 70 and r["breakout"]: A.append(r)
            elif r["score"] >= 60: B.append(r)
            elif r["score"] >= 50: C.append(r)

            if (idx + 1) % 100 == 0:
                print(f"📊 분석 진행 중: {idx + 1}/{len(items)} 완료")

    elapsed = round(time.time() - start_time, 1)

    # 리포트 생성
    msg = f"<b>📊 [1000종목 매집 스캐너]</b>\n"
    msg += f"📅 기준일: {target_date}\n"
    msg += f"⏱ 소요시간: {elapsed}초\n\n"

    msg += "<b>🔥 A급 (즉시 매매)</b>\n"
    if A:
        for x in A[:6]:
            msg += f"• <b>{x['name']}</b> ({x['score']}점)\n  현재: {int(x['price']):,} | 🚀 {int(x['entry']):,}\n\n"
    else: msg += "없음\n\n"

    msg += "<b>👀 B급 (관찰)</b>\n"
    msg += ", ".join([f"<b>{x['name']}</b>" for x in B[:10]]) if B else "없음"
    msg += "\n\n"

    msg += "<b>🌱 C급 (매집)</b>\n"
    msg += ", ".join([x['name'] for x in C[:15]]) if C else "없음"

    send_telegram(msg)
    print(f"✅ 완료 | A:{len(A)} B:{len(B)} C:{len(C)} | {elapsed}초")

if __name__ == "__main__":
    run_scanner()
