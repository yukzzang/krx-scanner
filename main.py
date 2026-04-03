import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import os
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
from pykrx import stock

# ==========================================
# 🔧 환경 변수
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print(message)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=15)
    except: pass

# ==========================================
# 📊 1000개 티커 확보 (시총 순)
# ==========================================
def get_tickers_info():
    # 안전하게 2일 전 날짜부터 역산 (주말/공휴일 방어)
    date = (datetime.now() - timedelta(days=2)).strftime("%Y%m%d")
    try:
        nm_k = stock.get_market_ticker_name("KOSPI")
        nm_q = stock.get_market_ticker_name("KOSDAQ")
        ticker_to_name = {**nm_k, **nm_q}

        cap_k = stock.get_market_cap(date, market="KOSPI")
        cap_q = stock.get_market_cap(date, market="KOSDAQ")

        # 코스피 400, 코스닥 600
        list_k = cap_k.sort_values('시가총액', ascending=False).head(400).index.tolist()
        list_q = cap_q.sort_values('시가총액', ascending=False).head(600).index.tolist()

        combined = []
        for t in list_k: combined.append({"ticker": f"{t}.KS", "name": ticker_to_name.get(t, t)})
        for t in list_q: combined.append({"ticker": f"{t}.KQ", "name": ticker_to_name.get(t, t)})
        
        print(f"📡 분석 대상 {len(combined)}개 추출 완료")
        return combined
    except:
        return [{"ticker": "005930.KS", "name": "삼성전자"}]

# ==========================================
# 📊 점수 계산 (대폭 완화 버전)
# ==========================================
def calculate_score(df):
    try:
        # yfinance 데이터 추출 안정화
        close = df['Close'].values.flatten()
        vol = df['Volume'].values.flatten()
        
        if len(close) < 60: return 0, 0, 0
        curr_p = float(close[-1])
        score = 0

        # 1. 거래량 (0.05 ~ 2.0배까지 대폭 완화)
        avg_v = np.mean(vol[-21:-1]) + 1e-9
        v_ratio = vol[-1] / avg_v
        if 0.1 < v_ratio < 1.5: score += 25
        elif v_ratio < 2.5: score += 15

        # 2. 이평선 수렴 (폭 8%까지 완화)
        m5 = np.mean(close[-5:])
        m20 = np.mean(close[-20:])
        m60 = np.mean(close[-60:])
        gap = max(m5, m20, m60) / (min(m5, m20, m60) + 1e-9)
        if gap < 1.05: score += 20
        elif gap < 1.08: score += 10

        # 3. 추세 (60일선 평단가 유지 여부)
        if m60 >= np.mean(close[-65:-5]): score += 15
        
        # 4. 위치 (고점 대비 70% 이상이면 합격)
        h60 = np.max(close[-60:])
        if curr_p > h60 * 0.70: score += 15
        elif curr_p > h60 * 0.55: score += 10

        # 5. 변동성 (20%까지 대폭 완화)
        r10 = (np.max(close[-10:]) - np.min(close[-10:])) / (curr_p + 1e-9)
        if r10 < 0.15: score += 15
        elif r10 < 0.25: score += 10

        # 6. 상승세
        if close[-1] >= close[-5]: score += 10

        entry = float(np.max(close[-10:]) * 1.005)
        stop = float(np.min(close[-10:]) * 0.98)
        return score, entry, stop
    except: return 0, 0, 0

# ==========================================
# 🔍 개별 분석
# ==========================================
def analyze_ticker(item):
    try:
        # 데이터 기간을 1년으로 늘려 누락 방지
        df = yf.download(item['ticker'], period="1y", interval="1d", progress=False, show_errors=False)
        if df.empty: return None
        
        score, entry, stop = calculate_score(df)
        curr_p = float(df['Close'].values.flatten()[-1])
        
        # 돌파 조건 완화 (5일 고가 대비 -7% 이내)
        h5 = float(np.max(df['Close'].values.flatten()[-5:]))
        is_break = curr_p >= h5 * 0.93

        return {
            "name": item['name'], "ticker": item['ticker'].split('.')[0],
            "price": curr_p, "score": score, "entry": entry, "stop": stop, "breakout": is_break
        }
    except: return None

# ==========================================
# 🚀 메인 실행
# ==========================================
def run_scanner():
    print("🚀 [진짜 완화형] 1,000종목 전수 스캔 시작")
    items = get_tickers_info()
    A, B, C = [], [], []

    with ThreadPoolExecutor(max_workers=30) as executor:
        futures = [executor.submit(analyze_ticker, it) for it in items]
        for idx, future in enumerate(as_completed(futures)):
            res = future.result()
            if not res: continue

            # 등급 컷 대폭 하향 (더 많이 잡히게)
            if res["score"] >= 65 and res["breakout"]: A.append(res)
            elif res["score"] >= 55: B.append(res)
            elif res["score"] >= 45: C.append(res)

            if (idx + 1) % 100 == 0: print(f"📊 진행률: {idx + 1}/1000...")

    # 정렬
    A = sorted(A, key=lambda x: x['score'], reverse=True)
    B = sorted(B, key=lambda x: x['score'], reverse=True)
    C = sorted(C, key=lambda x: x['score'], reverse=True)

    # 📢 메시지
    msg = f"<b>📊 [전수 조사 완화 리포트]</b>\n📅 {datetime.now().strftime('%Y-%m-%d')}\n\n"
    
    msg += "<b>🔥 A급 (강력 추천)</b>\n"
    if A:
        for i in A[:6]:
            msg += f"• <b>{i['name']}</b> ({i['score']}점)\n  현재: {int(i['price']):,} | 🚀 {int(i['entry']):,}\n\n"
    else: msg += "대상 없음\n\n"

    msg += "<b>👀 B급 (관찰 대상)</b>\n"
    msg += ", ".join([f"<b>{x['name']}</b>" for x in B[:10]]) if B else "없음"
    msg += "\n\n"

    msg += "<b>🌱 C급 (매집 포착)</b>\n"
    msg += ", ".join([f"{x['name']}" for x in C[:15]]) if C else "없음"

    send_telegram(msg)
    print(f"✅ 완료 | A:{len(A)} B:{len(B)} C:{len(C)}")

if __name__ == "__main__":
    run_scanner()
