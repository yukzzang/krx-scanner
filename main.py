import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import os
import time
from pykrx import stock

# ==========================================
# 🔧 환경 변수 (GitHub Secrets 설정 필수)
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print(f"\n📢 [텔레그램 미설정 - 로출]\n{message}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        res = requests.post(url, json={
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }, timeout=15)
        if res.status_code != 200:
            print(f"❌ 전송 실패: {res.text}")
    except Exception as e:
        print(f"❌ 오류 발생: {e}")

# ==========================================
# 📅 데이터 가용 날짜 확인 (가장 확실한 영업일 찾기)
# ==========================================
def get_safe_business_day():
    """
    오늘 데이터가 없으면 어제, 어제 없으면 그저께... 
    실제로 데이터가 들어있는 날을 찾을 때까지 최대 10일을 역산합니다.
    """
    # UTC 기준 서버 시간 고려하여 안전하게 오늘(0)부터 10일 전까지 탐색
    for i in range(0, 11):
        target_d = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
        try:
            # 해당 날짜의 시가총액 데이터를 호출해봅니다.
            df = stock.get_market_cap(target_d)
            # 데이터가 존재하고 종목 수가 최소 500개 이상이면 '살아있는 장날'로 판단
            if not df.empty and len(df) > 500:
                print(f"✅ 유효한 데이터 날짜 발견: {target_d} (종목수: {len(df)})")
                return target_d
        except:
            continue
    # 최후의 보루 (어제 날짜 반환)
    return (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")

# ==========================================
# 📊 핵심 전략 점수 계산
# ==========================================
def calculate_score(close, vol):
    score = 0
    curr_close = close.iloc[-1]
    avg_vol_20 = vol.iloc[-21:-1].mean() + 1e-9
    vol_ratio = vol.iloc[-1] / avg_vol_20

    # 1. 거래량 마름 (25점) - 매도세 소멸 확인
    if 0.3 < vol_ratio < 0.7: score += 25
    elif 0.2 < vol_ratio < 1.0: score += 15

    # 2. 이평선 밀집 (20점) - 에너지 응축
    ma5 = close.rolling(5).mean().iloc[-1]
    ma20 = close.rolling(20).mean().iloc[-1]
    ma60 = close.rolling(60).mean().iloc[-1]
    ma_gap = max(ma5, ma20, ma60) / (min(ma5, ma20, ma60) + 1e-9)
    if ma_gap < 1.03: score += 20
    elif ma_gap < 1.05: score += 10

    # 3. 장기 추세 (15점) - 60일선 우상향
    ma60_s = close.rolling(60).mean()
    if ma60_s.iloc[-1] >= ma60_s.iloc[-5]: score += 15

    # 4. 가격 위치 (15점) - 고점 대비 박스권 유지
    high_60 = close.iloc[-60:].max()
    if curr_close > high_60 * 0.85: score += 15
    elif curr_close > high_60 * 0.70: score += 10

    # 5. 변동성 축소 (15점) - VCP 패턴
    range_10 = (close.iloc[-10:].max() - close.iloc[-10:].min()) / (curr_close + 1e-9)
    if range_10 < 0.05: score += 15
    elif range_10 < 0.08: score += 10

    # 6. 저점 높이기 (10점)
    if close.iloc[-1] >= close.iloc[-2] >= close.iloc[-3]: score += 10

    return score

def get_trade_levels(close):
    high, low = close.iloc[-10:].max(), close.iloc[-10:].min()
    return high * 1.005, low * 0.98

# ==========================================
# 🚀 메인 스캐너 실행 로직
# ==========================================
def run_scanner():
    print("🚀 [등급별 매집 스캐너] 가동...")
    
    last_date = get_safe_business_day()
    start_date = (datetime.strptime(last_date, "%Y%m%d") - timedelta(days=150)).strftime("%Y%m%d")

    try:
        # 종목명 매핑
        names = {**stock.get_market_ticker_name("KOSPI"), **stock.get_market_ticker_name("KOSDAQ")}
        
        # 시장 데이터 로드
        kospi_df = stock.get_market_cap(last_date, market="KOSPI")
        kosdaq_df = stock.get_market_cap(last_date, market="KOSDAQ")

        if kospi_df.empty or kosdaq_df.empty:
            send_telegram(f"⚠️ {last_date} 데이터가 비어있습니다. (KRX 서버 업데이트 대기)")
            return

        # 분석 대상: 시총 상위 (K300 + Q400)
        tickers = kospi_df.sort_values('시가총액', ascending=False).head(300).index.tolist() + \
                  kosdaq_df.sort_values('시가총액', ascending=False).head(400).index.tolist()
        
        print(f"🔍 분석 시작: {len(tickers)}개 종목 (기준일: {last_date})")

    except Exception as e:
        send_telegram(f"❌ 초기 로딩 실패: {e}")
        return

    A_list, B_list, C_list = [], [], []

    for idx, ticker in enumerate(tickers):
        try:
            df = stock.get_market_ohlcv_by_date(start_date, last_date, ticker)
            if len(df) < 75: continue

            close, vol = df['종가'].astype(float), df['거래량'].astype(float)
            score = calculate_score(close, vol)
            entry, stop = get_trade_levels(close)

            # 돌파 직전 필터 (5일 고가 대비 -2% 이내)
            is_near_breakout = close.iloc[-1] >= (close.iloc[-5:].max() * 0.98)

            item = {"name": names.get(ticker, ticker), "price": close.iloc[-1], "score": score, "entry": entry, "stop": stop}

            if score >= 75 and is_near_breakout: A_list.append(item)
            elif score >= 65: B_list.append(item)
            elif score >= 55: C_list.append(item)

            if idx % 100 == 0: print(f" 진행 중... ({idx}/{len(tickers)})")
            time.sleep(0.04) # IP 차단 방지

        except: continue

    # ==========================================
    # 📢 결과 리포트 생성 및 전송
    # ==========================================
    report = f"<b>📊 [등급별 매집 리포트]</b>\n📅 기준일: {last_date}\n"
    report += "━━━━━━━━━━━━━━━━━━\n\n"

    # A급 (즉시 매매)
    report += "<b>🔥 A급 (즉시 관찰)</b>\n"
    if A_list:
        for i in sorted(A_list, key=lambda x: x['score'], reverse=True)[:5]:
            report += f"• <b>{i['name']}</b> ({i['score']}점)\n"
            report += f"  현재: {int(i['price']):,} | 🚀 {int(i['entry']):,} / ⛔ {int(i['stop']):,}\n\n"
    else: report += "대상 없음\n\n"

    # B급 (관찰)
    report += "<b>👀 B급 (관찰)</b>\n"
    if B_list:
        report += ", ".join([f"<b>{x['name']}</b>({x['score']})" for x in sorted(B_list, key=lambda x: x['score'], reverse=True)[:8]]) + "\n\n"
    else: report += "없음\n\n"

    # C급 (초기 매집)
    report += "<b>🌱 C급 (매집 중)</b>\n"
    if C_list:
        report += ", ".join([f"{x['name']}" for x in sorted(C_list, key=lambda x: x['score'], reverse=True)[:10]])
    else: report += "없음"

    send_telegram(report)
    print(f"✅ 스캔 완료! (A:{len(A_list)}, B:{len(B_list)}, C:{len(C_list)})")

if __name__ == "__main__":
    run_scanner()
