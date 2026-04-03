import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import os
import time
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
from pykrx import stock

# ==========================================
# 🔧 환경 변수 (GitHub Secrets)
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print(f"\n📢 [로컬 출력]\n{message}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }, timeout=15)
    except Exception as e:
        print(f"❌ 텔레그램 오류: {e}")

# ==========================================
# 📊 티커 및 종목명 수집
# ==========================================
def get_tickers_with_names():
    # 안전하게 어제 날짜 기준으로 티커 리스트 확보
    target_date = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    try:
        print(f"📡 티커 수집 중 (기준일: {target_date})...")
        
        # 코스피/코스닥 종목명 딕셔너리 생성
        nm_k = stock.get_market_ticker_name("KOSPI")
        nm_q = stock.get_market_ticker_name("KOSDAQ")
        ticker_to_name = {**nm_k, **nm_q}

        # 시가총액 상위 종목 추출 (에러 방지를 위해 try-except 감싸기)
        try:
            cap_k = stock.get_market_cap(target_date, market="KOSPI")
            cap_q = stock.get_market_cap(target_date, market="KOSDAQ")
            
            list_k = cap_k.sort_values('시가총액', ascending=False).head(350).index.tolist()
            list_q = cap_q.sort_values('시가총액', ascending=False).head(650).index.tolist()
        except:
            # 시총 데이터 실패 시 전체 리스트 사용
            list_k = stock.get_market_ticker_list(market="KOSPI")[:300]
            list_q = stock.get_market_ticker_list(market="KOSDAQ")[:500]

        # yfinance 형식으로 변환 (.KS / .KQ)
        combined = []
        for t in list_k:
            combined.append({"ticker": f"{t}.KS", "name": ticker_to_name.get(t, t)})
        for t in list_q:
            combined.append({"ticker": f"{t}.KQ", "name": ticker_to_name.get(t, t)})

        print(f"✅ 총 {len(combined)}개 종목 분석 준비 완료")
        return combined
    except Exception as e:
        print(f"⚠️ 티커 수집 실패: {e}")
        return [{"ticker": "005930.KS", "name": "삼성전자"}] # 최소 세이프티

# ==========================================
# 📉 전략 점수 계산 (yfinance 데이터용)
# ==========================================
def calculate_strategy(df):
    if len(df) < 70: return 0, 0, 0
    
    # yf 데이터 구조 대응 (MultiIndex 방지 및 1차원 Series 변환)
    close = df['Close'].squeeze()
    vol = df['Volume'].squeeze()
    curr_p = float(close.iloc[-1])

    score = 0

    # 1. 거래량 마름 (25점)
    avg_vol = vol.iloc[-21:-1].mean() + 1e-9
    vol_ratio = vol.iloc[-1] / avg_vol
    if 0.3 < vol_ratio < 0.7: score += 25
    elif 0.2 < vol_ratio < 1.0: score += 15

    # 2. 이평선 수렴 (20점)
    ma5, ma20, ma60 = close.rolling(5).mean().iloc[-1], close.rolling(20).mean().iloc[-1], close.rolling(60).mean().iloc[-1]
    ma_gap = max(ma5, ma20, ma60) / (min(ma5, ma20, ma60) + 1e-9)
    if ma_gap < 1.03: score += 20
    elif ma_gap < 1.05: score += 10

    # 3. 추세/위치/변동성
    if close.rolling(60).mean().iloc[-1] >= close.rolling(60).mean().iloc[-5]: score += 15
    if curr_p > close.iloc[-60:].max() * 0.85: score += 15
    
    range_10 = (close.iloc[-10:].max() - close.iloc[-10:].min()) / (curr_p + 1e-9)
    if range_10 < 0.05: score += 15
    elif range_10 < 0.08: score += 10

    if close.iloc[-1] >= close.iloc[-2] >= close.iloc[-3]: score += 10

    # 진입/손절가
    entry = float(close.iloc[-10:].max() * 1.005)
    stop = float(close.iloc[-10:].min() * 0.98)

    return score, entry, stop

# ==========================================
# 🔍 개별 종목 분석 (Thread용)
# ==========================================
def analyze_ticker(item):
    ticker = item['ticker']
    name = item['name']
    try:
        # yfinance는 병렬 호출 시 매우 빠릅니다.
        df = yf.download(ticker, period="7mo", interval="1d", progress=False, show_errors=False)
        if df.empty or len(df) < 70: return None

        score, entry, stop = calculate_strategy(df)
        curr_p = float(df['Close'].iloc[-1])
        
        # 돌파 임박 여부
        is_near = curr_p >= (df['Close'].iloc[-5:].max() * 0.98)

        return {
            "name": name, "ticker": ticker.split('.')[0],
            "price": curr_p, "score": score,
            "entry": entry, "stop": stop, "breakout": is_near
        }
    except:
        return None

# ==========================================
# 🚀 메인 스캐너 실행
# ==========================================
def run_scanner():
    start_time = time.time()
    print("🚀 병렬 스캐너 가동...")

    items = get_tickers_with_names()
    A, B, C = [], [], []

    # 🔥 ThreadPoolExecutor로 1000개 종목을 30개씩 동시 처리
    with ThreadPoolExecutor(max_workers=30) as executor:
        futures = [executor.submit(analyze_ticker, item) for item in items]
        
        for future in as_completed(futures):
            res = future.result()
            if not res: continue

            if res['score'] >= 75 and res['breakout']: A.append(res)
            elif res['score'] >= 65: B.append(res)
            elif res['score'] >= 55: C.append(res)

    # 정렬
    A = sorted(A, key=lambda x: x['score'], reverse=True)
    B = sorted(B, key=lambda x: x['score'], reverse=True)
    C = sorted(C, key=lambda x: x['score'], reverse=True)

    # 📢 메시지 구성
    msg = f"<b>📊 [등급별 매집 리포트]</b>\n📅 {datetime.now().strftime('%Y-%m-%d')}\n"
    msg += "━━━━━━━━━━━━━━━━━━\n\n"

    msg += "<b>🔥 A급 (즉시 공략)</b>\n"
    if A:
        for i in A[:6]:
            msg += f"• <b>{i['name']}</b> ({i['score']}점)\n"
            msg += f"  현재: {int(i['price']):,} | 🚀 {int(i['entry']):,} / ⛔ {int(i['stop']):,}\n\n"
    else: msg += "대상 없음\n\n"

    msg += "<b>👀 B급 (관찰)</b>\n"
    msg += ", ".join([f"<b>{x['name']}</b>" for x in B[:8]]) + "\n\n"

    msg += "<b>🌱 C급 (매집)</b>\n"
    msg += ", ".join([x['name'] for x in C[:10]])

    send_telegram(msg)
    
    end_time = time.time()
    print(f"✅ 완료 (소요시간: {int(end_time - start_time)}초) | A:{len(A)} B:{len(B)} C:{len(C)}")

if __name__ == "__main__":
    run_scanner()
