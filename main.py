import pandas as pd
import numpy as np
import requests
import time
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import StringIO

# ==========================================
# 🔧 설정 (사용자 정보 입력)
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_ACTUAL_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_ACTUAL_ID")

MIN_SCORE = 50
MIN_VALUE = 5_000_000_000  # 거래대금 최소 50억

# ==========================================
# 📩 텔레그램 전송
# ==========================================
def send_telegram(msg):
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
            print(f"❌ 텔레그램 통신 오류: {e}")

# ==========================================
# 📅 종목 리스트 가져오기 (KRX)
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
            if any(x in name for x in ["우", "스팩", "리츠", "ETN", "ETF"]): continue

            ticker = f"{code}.KQ" if "코스닥" in market else f"{code}.KS"
            tickers.append({"ticker": ticker, "name": name})
        return tickers
    except Exception as e:
        print(f"❌ 종목 리스트 획득 오류: {e}")
        return []

# ==========================================
# 📈 점수 계산
# ==========================================
def calculate_score(df):
    try:
        close = df['Close'].squeeze()
        vol = df['Volume'].squeeze()
        if len(close) < 60: return 0, False

        curr = float(close.iloc[-1])
        score = 0

        # 거래량 증가
        if vol.iloc[-3:].mean() > vol.iloc[-10:-3].mean(): score += 20

        # 변동성 축소
        r20 = (close.iloc[-20:].max() - close.iloc[-20:].min()) / curr
        r5 = (close.iloc[-5:].max() - close.iloc[-5:].min()) / curr
        if r5 < r20: score += 20

        # 이평선 정배열
        m20 = close.rolling(20).mean().iloc[-1]
        m60 = close.rolling(60).mean().iloc[-1]
        if m20 > m60 and curr > m20: score += 20

        # 가격 위치
        if curr > close.iloc[-60:].max() * 0.7: score += 20

        # 단기 상승세
        if close.iloc[-1] > close.iloc[-3]: score += 10

        # 돌파 임박
        ready = curr >= close.iloc[-5:].max() * 0.92
        return score, ready
    except:
        return 0, False

# ==========================================
# ⚡ 강세 필터
# ==========================================
def strong_filter(df):
    try:
        close = df['Close'].squeeze()
        vol = df['Volume'].squeeze()
        v = vol.iloc[-3:].mean() > vol.iloc[-10:-3].mean() * 1.2
        m = close.iloc[-1] > close.iloc[-2] * 1.01
        r = close.iloc[-1] >= close.iloc[-20:].max() * 0.9
        return bool(v and m and r)
    except:
        return False

# ==========================================
# 🔍 개별 분석
# ==========================================
def analyze(item):
    try:
        df = yf.download(item['ticker'], period="6mo", progress=False, threads=False)
        if df.empty or len(df) < 60: return None, True

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        close = df['Close'].squeeze()
        vol = df['Volume'].squeeze()

        # 거래대금 필터
        value = float(close.iloc[-1]) * float(vol.iloc[-1])
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
# 🚀 메인 컨트롤러
# ==========================================
def run():
    print("🚀 스캔 시작...")
    tickers = get_tickers()
    total = len(tickers)
    success, valid = 0, 0
    A, B, C = [], [], []

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

    # 결과 제한
    A = sorted(A, key=lambda x: x['score'], reverse=True)[:15]
    B = sorted(B, key=lambda x: x['score'], reverse=True)[:10]
    C = sorted(C, key=lambda x: x['score'], reverse=True)[:10]

    # 메시지 작성
    header = f"<b>📊 KRX Market Scanner</b>\n전체: {total} | 성공: {success} | 필터통과: {valid}\n"
    header += "⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"

    msg = header
    if A:
        msg += "<b>🔥 A급 (강력 매수 후보)</b>\n"
        msg += "\n".join([f"• {x['name']}({x['ticker']}) - <b>{int(x['score'])}점</b>" for x in A]) + "\n\n"
    if B:
        msg += "<b>👀 B급 (추적 관찰)</b>\n"
        msg += ", ".join([x['name'] for x in B]) + "\n\n"
    if C:
        msg += "<b>🌱 C급 (매집 후보)</b>\n"
        msg += ", ".join([x['name'] for x in C]) + "\n\n"
    if not A and not B and not C:
        msg += "⚠️ 조건에 맞는 종목이 없습니다."

    send_telegram(msg)
    print(f"✅ 스캔 완료! A:{len(A)} B:{len(B)} C:{len(C)}")

if __name__ == "__main__":
    run()