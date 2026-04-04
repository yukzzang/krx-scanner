import pandas as pd
import numpy as np
import requests
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import StringIO
import os
import time

# ==========================================
# 🔧 환경 변수
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

MIN_SCORE = 50
MIN_VALUE = 5_000_000_000  # 거래대금 최소 50억 (조정 가능)

# ==========================================
# 📩 텔레그램 전송 (HTML)
# ==========================================
def send_telegram(msg):
    max_len = 3500
    for i in range(0, len(msg), max_len):
        part = msg[i:i+max_len]
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            payload = {"chat_id": CHAT_ID, "text": part, "parse_mode": "HTML"}
            res = requests.post(url, json=payload, timeout=10)
            if res.status_code != 200:
                print(f"❌ 전송 실패: {res.text}")
        except Exception as e:
            print(f"❌ 텔레그램 통신 오류: {e}")

# ==========================================
# 📊 KRX 종목 수집
# ==========================================
def get_krx_tickers():
    try:
        url = "http://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13"
        df = pd.read_html(StringIO(requests.get(url).text), header=0)[0]
        tickers = []
        for _, row in df.iterrows():
            code = str(row['종목코드']).zfill(6)
            name = row['회사명']
            market = row['시장구분']
            if any(x in name for x in ["우", "스팩", "리츠", "ETN", "ETF"]): continue
            ticker = f"{code}.KQ" if "코스닥" in market else f"{code}.KS"
            tickers.append({"ticker": ticker, "name": name})
        return tickers
    except Exception as e:
        print(f"❌ 종목 리스트 오류: {e}")
        return []

# ==========================================
# 📈 점수 계산
# ==========================================
def calculate_score(df):
    try:
        close = df['Close'].astype(float)
        volume = df['Volume'].astype(float)
        if len(close) < 60: return 0, False

        curr = float(close.iloc[-1])
        score = 0

        # 거래량 증가
        if volume.iloc[-3:].mean() > volume.iloc[-10:-3].mean():
            score += 20

        # 변동성 축소 (VCP 기초)
        r20 = (close.iloc[-20:].max() - close.iloc[-20:].min()) / curr
        r5 = (close.iloc[-5:].max() - close.iloc[-5:].min()) / curr
        if r5 < r20: score += 20

        # 이평선 정배열
        m20 = close.rolling(20).mean().iloc[-1]
        m60 = close.rolling(60).mean().iloc[-1]
        if m20 > m60 and curr > m20: score += 20

        # 최근 60일 고점 대비 70% 이상
        if curr > close.iloc[-60:].max() * 0.7: score += 20

        # 단기 상승
        if close.iloc[-1] > close.iloc[-3]: score += 10

        # 돌파 임박
        ready = curr >= close.iloc[-5:].max() * 0.92
        return score, ready
    except:
        return 0, False

# ==========================================
# 강한 필터
# ==========================================
def strong_filter(df):
    try:
        close = df['Close'].astype(float)
        vol = df['Volume'].astype(float)
        v = vol.iloc[-3:].mean() > vol.iloc[-10:-3].mean() * 1.2
        m = close.iloc[-1] > close.iloc[-2] * 1.01
        r = close.iloc[-1] >= close.iloc[-20:].max() * 0.9
        return bool(v and m and r)
    except:
        return False

# ==========================================
# 개별 분석
# ==========================================
def analyze(item):
    try:
        df = yf.download(item['ticker'], period="6mo", progress=False, threads=False)
        if df.empty or len(df) < 60: return None, True
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        close = df['Close'].astype(float)
        volume = df['Volume'].astype(float)
        value = close.iloc[-1] * volume.iloc[-1]
        if value < MIN_VALUE: return None, True

        score, ready = calculate_score(df)
        if score < MIN_SCORE: return None, True

        return {
            "name": item['name'],
            "ticker": item['ticker'].split('.')[0],
            "score": score,
            "ready": ready,
            "strong": strong_filter(df)
        }, True
    except:
        return None, False

# ==========================================
# 메인 컨트롤러
# ==========================================
def run_krx_scanner():
    tickers = get_krx_tickers()
    total = len(tickers)
    success, valid = 0, 0
    A, B, C = [], [], []

    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=15) as ex:
        futures = [ex.submit(analyze, t) for t in tickers]
        for f in as_completed(futures):
            r, ok = f.result()
            if ok: success += 1
            if not r: continue
            valid += 1
            if r["score"] >= 70 and r["ready"] and r["strong"]: A.append(r)
            elif r["score"] >= 60: B.append(r)
            else: C.append(r)

    A = sorted(A, key=lambda x: x['score'], reverse=True)[:15]
    B = sorted(B, key=lambda x: x['score'], reverse=True)[:10]
    C = sorted(C, key=lambda x: x['score'], reverse=True)[:10]

    msg = f"<b>📊 KRX 스캐너</b>\n전체: {total} | 성공: {success} | 필터통과: {valid}\n"
    msg += "⎯" * 30 + "\n"

    if A:
        msg += "<b>🔥 A급</b>\n" + "\n".join([f"• {x['name']}({x['ticker']}) - {int(x['score'])}점" for x in A]) + "\n\n"
    if B:
        msg += "<b>👀 B급</b>\n" + ", ".join([x['name'] for x in B]) + "\n\n"
    if C:
        msg += "<b>⚡ C급</b>\n" + ", ".join([x['name'] for x in C]) + "\n\n"

    send_telegram(msg)
    print(f"✅ 완료! A:{len(A)} B:{len(B)} C:{len(C)}")

if __name__ == "__main__":
    run_krx_scanner()