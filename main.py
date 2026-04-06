import os
import pandas as pd
import numpy as np
import requests
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import StringIO

# ==========================================
# 🔧 설정
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

MIN_SCORE = 55
MIN_VALUE = 3_000_000_000  # 거래대금 30억

# ==========================================
# 📩 텔레그램 전송
# ==========================================
def send_telegram(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("❌ 텔레그램 설정 없음")
        return

    max_len = 3500
    for i in range(0, len(msg), max_len):
        part = msg[i:i+max_len]
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            payload = {
                "chat_id": CHAT_ID,
                "text": part,
                "parse_mode": "HTML"
            }
            res = requests.post(url, json=payload, timeout=10)
            if res.status_code != 200:
                print(f"❌ 전송 실패: {res.text}")
        except Exception as e:
            print(f"❌ 텔레그램 오류: {e}")

# ==========================================
# 📅 KRX 종목 리스트
# ==========================================
def get_tickers():
    try:
        url = "http://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13"
        html = requests.get(url).text
        df = pd.read_html(StringIO(html), header=0)[0]

        df['종목코드'] = df['종목코드'].apply(lambda x: str(x).zfill(6))

        tickers = []
        for _, row in df.iterrows():
            code = row['종목코드']
            name = row['회사명']
            market = row['시장구분']

            if not code.isdigit(): continue
            if any(x in name for x in ["우", "스팩", "리츠", "ETF", "ETN"]): continue

            ticker = f"{code}.KQ" if "코스닥" in market else f"{code}.KS"
            tickers.append({"ticker": ticker, "name": name})

        return tickers

    except Exception as e:
        print(f"❌ 종목 리스트 오류: {e}")
        return []

# ==========================================
# 📊 점수 계산 (매집형 핵심)
# ==========================================
def calculate_score_and_levels(df):
    try:
        close = df['Close'].squeeze()
        high = df['High'].squeeze()
        low = df['Low'].squeeze()
        vol = df['Volume'].squeeze()

        if len(close) < 60:
            return 0, False, None

        curr = float(close.iloc[-1])
        score = 0

        # 1️⃣ 거래량 건조
        vol_recent = vol.iloc[-10:].mean()
        vol_past = vol.iloc[-30:].mean()
        if vol_recent < vol_past * 0.8:
            score += 20

        # 2️⃣ VCP (변동성 축소)
        r20 = (close.iloc[-20:].max() - close.iloc[-20:].min()) / curr
        r10 = (close.iloc[-10:].max() - close.iloc[-10:].min()) / curr
        r5 = (close.iloc[-5:].max() - close.iloc[-5:].min()) / curr

        if r5 < r10 < r20:
            score += 25

        # 3️⃣ 추세 유지
        m20 = close.rolling(20).mean().iloc[-1]
        m60 = close.rolling(60).mean().iloc[-1]
        if m20 > m60 and curr > m20:
            score += 20

        # 4️⃣ 전고점 근접 (미돌파)
        high_20 = close.iloc[-20:].max()
        if curr > high_20 * 0.92 and curr < high_20:
            score += 20

        # 5️⃣ RSI
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))

        if 45 < rsi.iloc[-1] < 60:
            score += 15

        # 🎯 돌파 직전
        ready = curr >= high_20 * 0.95

        # 📊 ATR 리스크
        atr = (high - low).rolling(14).mean().iloc[-1]
        entry = curr
        stop = entry - atr * 1.2
        target = entry + atr * 2.5

        status = "READY" if ready else "WAIT"
        if curr < stop:
            status = "INVALID"

        levels = {
            "entry": round(entry, 2),
            "stop": round(stop, 2),
            "target": round(target, 2),
            "status": status
        }

        return score, ready, levels

    except:
        return 0, False, None

# ==========================================
# ⚡ A급 필터
# ==========================================
def strong_filter(df):
    try:
        close = df['Close'].squeeze()
        vol = df['Volume'].squeeze()

        dry = vol.iloc[-10:].mean() < vol.iloc[-30:].mean() * 0.8
        spike = vol.iloc[-1] > vol.iloc[-5:].mean() * 1.5
        near_high = close.iloc[-1] >= close.iloc[-20:].max() * 0.95

        return bool(dry and spike and near_high)

    except:
        return False

# ==========================================
# 🔍 종목 분석
# ==========================================
def analyze(item):
    try:
        df = yf.download(item['ticker'], period="6mo", progress=False, threads=False)

        if df.empty or len(df) < 60:
            return None, True

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # 거래대금 필터
        value = float(df['Close'].iloc[-1]) * float(df['Volume'].iloc[-1])
        if value < MIN_VALUE:
            return None, True

        score, ready, levels = calculate_score_and_levels(df)

        if score < MIN_SCORE:
            return None, True

        return {
            "name": item['name'],
            "ticker": item['ticker'].split('.')[0],
            "score": score,
            "ready": ready,
            "strong": strong_filter(df),
            **levels
        }, True

    except:
        return None, False

# ==========================================
# 🚀 실행
# ==========================================
def run():
    print("🚀 스캔 시작")

    tickers = get_tickers()
    total = len(tickers)

    success, valid = 0, 0
    A, B, C = [], [], []

    with ThreadPoolExecutor(max_workers=15) as ex:
        futures = [ex.submit(analyze, t) for t in tickers]

        for f in as_completed(futures):
            r, ok = f.result()

            if ok:
                success += 1

            if not r:
                continue

            valid += 1

            if r["score"] >= 75 and r["ready"] and r["strong"]:
                A.append(r)
            elif r["score"] >= 65:
                B.append(r)
            else:
                C.append(r)

    # 정렬
    A = sorted(A, key=lambda x: x['score'], reverse=True)[:10]
    B = sorted(B, key=lambda x: x['score'], reverse=True)[:10]
    C = sorted(C, key=lambda x: x['score'], reverse=True)[:10]

    # 메시지
    msg = f"<b>📊 KRX 매집 스캐너</b>\n전체:{total} 성공:{success} 유효:{valid}\n"
    msg += "⎯" * 30 + "\n"

    for label, group in [("🔥 A급 (터지기 직전)", A),
                         ("👀 B급 (관찰)", B),
                         ("🌱 C급 (초기 매집)", C)]:

        if group:
            msg += f"<b>{label}</b>\n"
            for x in group:
                msg += f"• {x['name']}({x['ticker']}) {x['score']}점\n"
                msg += f"  ▶ 진입:{x['entry']} 손절:{x['stop']} 목표:{x['target']} [{x['status']}]\n"
            msg += "\n"

    if not (A or B or C):
        msg += "⚠️ 조건 만족 종목 없음"

    send_telegram(msg)

    print(f"✅ 완료 A:{len(A)} B:{len(B)} C:{len(C)}")


if __name__ == "__main__":
    run()