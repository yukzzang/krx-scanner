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
import os
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

MIN_SCORE = 50
MIN_VALUE = 5_000_000_000  # 거래대금 최소 50억 (필요시 조정)

# ==========================================
# 📩 텔레그램 전송 (HTML 모드 적용)
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
# 📈 점수 계산 (데이터 안전 처리)
# ==========================================
def calculate_score(df):
    try:
        # 데이터가 MultiIndex인 경우를 대비해 Squeeze 처리
        close = df['Close'].squeeze()
        vol = df['Volume'].squeeze()

        if len(close) < 60: return 0, False

        curr = float(close.iloc[-1])
        score = 0

        # 1. 거래량 증가 (최근 3일 평균 > 이전 7일 평균)
        if vol.iloc[-3:].mean() > vol.iloc[-10:-3].mean():
            score += 20

        # 2. 변동성 축소 (VCP 패턴 기초)
        r20 = (close.iloc[-20:].max() - close.iloc[-20:].min()) / curr
        r5 = (close.iloc[-5:].max() - close.iloc[-5:].min()) / curr
        if r5 < r20: score += 20

        # 3. 이평선 정배열 기초 (20일 > 60일 & 현재가 > 20일)
        m20 = close.rolling(20).mean().iloc[-1]
        m60 = close.rolling(60).mean().iloc[-1]
        if m20 > m60 and curr > m20: score += 20

        # 4. 가격 위치 (최근 60일 고가 대비 70% 이상 지점)
        if curr > close.iloc[-60:].max() * 0.7: score += 20

        # 5. 단기 상승세
        if close.iloc[-1] > close.iloc[-3]: score += 10

        # 돌파 임박 (최근 5일 고가에 근접)
        ready = curr >= close.iloc[-5:].max() * 0.92
        return score, ready
    except:
        return 0, False

# ==========================================
# ⚡ 강한 필터 (강세 종목)
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
# 🔍 개별 분석 실행
# ==========================================
def analyze(item):
    try:
        # 데이터 다운로드
        df = yf.download(item['ticker'], period="6mo", progress=False, threads=False)
        if df.empty or len(df) < 60: return None, True

        # MultiIndex 컬럼 제거 (yf 업데이트 대응)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        close = df['Close'].squeeze()
        vol = df['Volume'].squeeze()

        # 거래대금 필터 (최근일 기준)
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
    except Exception as e:
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

    # 스레드 15개로 병렬 처리
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

    # 결과 정렬
    A = sorted(A, key=lambda x: x['score'], reverse=True)[:15]
    B = sorted(B, key=lambda x: x['score'], reverse=True)[:10]
    C = sorted(C, key=lambda x: x['score'], reverse=True)[:10]

    # 메시지 작성
    header = f"<b>📊 KRX Market Scanner</b>\n"
    header += f"전체: {total} | 성공: {success} | 필터통과: {valid}\n"
    header += "⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"

    msg = header
    if A:
        msg += "<b>🔥 A급 (강력 매수 후보)</b>\n"
        msg += "\n".join([f"• {x['name']}({x['ticker']}) - <b>{int(x['score'])}점</b>" for x in A]) + "\n\n"
    
    if B:
        msg += "<b>👀 B급 (추적 관찰)</b>\n"
        msg += ", ".join([f"{x['name']}" for x in B]) + "\n\n"

    if not A and not B:
        msg += "⚠️ 현재 조건에 부합하는 종목이 없습니다."

    send_telegram(msg)
    print(f"✅ 스캔 완료! A:{len(A)} B:{len(B)} C:{len(C)}")

if __name__ == "__main__":
    run()
