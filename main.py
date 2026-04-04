import pandas as pd
import numpy as np
import requests
import time
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================
# 🔧 설정
# ==========================================
TELEGRAM_TOKEN = "YOUR_TOKEN"
CHAT_ID = "YOUR_CHAT_ID"
MIN_SCORE = 50  # 점수 기준

# ==========================================
# 📩 텔레그램 전송
# ==========================================
def send_telegram(msg):
    print("\n📩 텔레그램 전송 시도")
    try:
        res = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": msg[:4000]},  # 최대 4000자
            timeout=10
        )
        print("응답:", res.status_code, res.text)
    except Exception as e:
        print("❌ 오류:", e)

# ==========================================
# 📅 KRX 종목 가져오기
# ==========================================
def get_tickers():
    print("🔎 KRX 종목 수집 중...")
    url = "http://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13"
    df = pd.read_html(requests.get(url).text, header=0)[0]
    df['종목코드'] = df['종목코드'].apply(lambda x: str(x).zfill(6))
    df['ticker'] = df['종목코드'] + ".KS"
    tickers = df[['ticker', '회사명']].rename(columns={'회사명': 'name'})
    print(f"✅ 종목 수: {len(tickers)}")
    return tickers.to_dict('records')

# ==========================================
# 📊 점수 계산
# ==========================================
def calculate_score(df):
    try:
        close = df['Close']
        vol = df['Volume']

        if len(df) < 60:
            return 0, False

        curr = close.iloc[-1]
        s = 0

        # 거래량 증가
        if vol.iloc[-3:].mean() > vol.iloc[-10:-3].mean() * 1.2:
            s += 20

        # 변동성 감소
        r20 = (close.iloc[-20:].max() - close.iloc[-20:].min()) / curr
        r5 = (close.iloc[-5:].max() - close.iloc[-5:].min()) / curr
        if r5 < r20:
            s += 20

        # 추세 확인 (20일 > 60일선)
        m20 = close.rolling(20).mean().iloc[-1]
        m60 = close.rolling(60).mean().iloc[-1]
        if m20 > m60 and curr > m20:
            s += 20

        # 위치
        if curr > close.iloc[-60:].max() * 0.7:
            s += 20

        # 최근 상승
        if close.iloc[-1] > close.iloc[-3]:
            s += 10

        # 돌파 직전
        ready = curr >= close.iloc[-5:].max() * 0.92

        return s, ready

    except:
        return 0, False

# ==========================================
# 🔥 A급 필터
# ==========================================
def strong_filter(df):
    try:
        close = df['Close']
        vol = df['Volume']
        v = vol.iloc[-3:].mean() > vol.iloc[-10:-3].mean() * 1.2
        m = close.iloc[-1] > close.iloc[-2] * 1.01
        r = close.iloc[-1] >= close.iloc[-20:].max() * 0.9
        return v and m and r
    except:
        return False

# ==========================================
# 🔍 개별 종목 분석
# ==========================================
def analyze(item):
    try:
        time.sleep(0.01)
        df = yf.download(item['ticker'], period="6mo", progress=False)
        if df.empty: return None, False
        s, ready = calculate_score(df)
        if s < MIN_SCORE: return None, True
        return {
            "name": item['name'],
            "score": s,
            "ready": ready,
            "strong": strong_filter(df)
        }, True
    except:
        return None, False

# ==========================================
# 🚀 실행
# ==========================================
def run():
    tickers = get_tickers()
    total = len(tickers)
    success = 0
    valid = 0
    A, B, C = [], [], []

    with ThreadPoolExecutor(max_workers=15) as ex:
        futures = [ex.submit(analyze, t) for t in tickers]
        for f in as_completed(futures):
            r, ok = f.result()
            if ok: success += 1
            if not r: continue
            valid += 1
            if r["score"] >= 60 and r["ready"] and r["strong"]:
                A.append(r)
            elif r["score"] >= 50:
                B.append(r)
            else:
                C.append(r)

    # 메시지 생성
    msg = f"<b>📊 KRX 확률 스캐너</b>\n"
    msg += f"📈 전체:{total} 성공:{success} 유효:{valid}\n\n"
    msg += "<b>🔥 A급</b>\n" + ("\n".join([f"{x['name']} ({x['score']})" for x in A[:5]]) if A else "없음")
    msg += "\n\n<b>👀 B급</b>\n" + (", ".join([x['name'] for x in B[:10]]) if B else "없음")
    msg += "\n\n<b>🌱 C급</b>\n" + (", ".join([x['name'] for x in C[:10]]) if C else "없음")

    send_telegram(msg)
    print(f"✅ 완료 A:{len(A)} B:{len(B)} C:{len(C)}")

# ==========================================
# ▶ 실행
# ==========================================
if __name__ == "__main__":
    run()