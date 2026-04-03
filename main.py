import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import os
import time
from pykrx import stock

# ==========================================
# 🔧 환경 변수 및 설정
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print(f"\n📢 [스캔 리포트]\n{message}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={
            "chat_id": CHAT_ID, 
            "text": message, 
            "parse_mode": "HTML"
        }, timeout=10)
    except Exception as e:
        print(f"❌ 텔레그램 오류: {e}")

# ==========================================
# 📅 최근 영업일 검증 (오류 방지 핵심)
# ==========================================
def get_recent_business_day():
    # GitHub Actions 서버 시간 고려하여 오늘부터 역산
    for i in range(0, 10):
        d = (datetime.today() - timedelta(days=i)).strftime("%Y%m%d")
        try:
            # 단순히 종목 조회가 아니라 '시가총액' 데이터가 실제로 존재하는지 확인
            df = stock.get_market_cap(d)
            if not df.empty and '시가총액' in df.columns:
                return d
        except:
            continue
    return (datetime.today() - timedelta(days=1)).strftime("%Y%m%d")

# ==========================================
# 📊 점수 및 레벨 계산 로직
# ==========================================
def calculate_score(close, vol):
    score = 0
    curr_close = close.iloc[-1]
    avg_vol_20 = vol.iloc[-21:-1].mean() + 1e-9
    vol_ratio = vol.iloc[-1] / avg_vol_20

    # 1. 거래량 마름 (25점)
    if 0.3 < vol_ratio < 0.7: score += 25
    elif 0.2 < vol_ratio < 1.0: score += 15

    # 2. 이평선 수렴 (20점)
    ma5, ma20, ma60 = close.rolling(5).mean().iloc[-1], close.rolling(20).mean().iloc[-1], close.rolling(60).mean().iloc[-1]
    ma_gap = max(ma5, ma20, ma60) / min(ma5, ma20, ma60)
    if ma_gap < 1.03: score += 20
    elif ma_gap < 1.05: score += 10

    # 3. 추세/위치/변동성 (45점)
    if close.rolling(60).mean().iloc[-1] >= close.rolling(60).mean().iloc[-5]: score += 15
    if curr_close > close.iloc[-60:].max() * 0.85: score += 15
    range_10 = (close.iloc[-10:].max() - close.iloc[-10:].min()) / (curr_close + 1e-9)
    if range_10 < 0.05: score += 15
    elif range_10 < 0.08: score += 10

    # 4. 상승 압력 (10점)
    if close.iloc[-1] >= close.iloc[-2] >= close.iloc[-3]: score += 10
    return score

def get_trade_levels(close):
    high, low = close.iloc[-10:].max(), close.iloc[-10:].min()
    return high * 1.005, low * 0.98

# ==========================================
# 🚀 메인 스캐너 실행
# ==========================================
def run_scanner():
    print("🚀 등급별 매집 스캐너 가동 시작")
    
    last_date = get_recent_business_day()
    print(f"📅 데이터 기준일: {last_date}")
    
    start_date = (datetime.strptime(last_date, "%Y%m%d") - timedelta(days=150)).strftime("%Y%m%d")

    try:
        names = {**stock.get_market_ticker_name("KOSPI"), **stock.get_market_ticker_name("KOSDAQ")}
        
        # 시총 데이터 로드 및 에러 핸들링
        df_kospi_cap = stock.get_market_cap(last_date, market="KOSPI")
        df_kosdaq_cap = stock.get_market_cap(last_date, market="KOSDAQ")
        
        if df_kospi_cap.empty or df_kosdaq_cap.empty:
            print("⚠️ 해당 날짜의 시가총액 데이터가 아직 비어있습니다.")
            return

        kospi = df_kospi_cap.sort_values('시가총액', ascending=False).head(300).index.tolist()
        kosdaq = df_kosdaq_cap.sort_values('시가총액', ascending=False).head(400).index.tolist()
        tickers = kospi + kosdaq
    except Exception as e:
        print(f"❌ 초기 데이터 로딩 중 에러: {e}")
        return

    A_list, B_list, C_list = [], [], []

    print(f"🔍 {len(tickers)}개 종목 분석 중...")

    for ticker in tickers:
        try:
            df = stock.get_market_ohlcv_by_date(start_date, last_date, ticker)
            if len(df) < 75: continue
            
            close, vol = df['종가'].astype(float), df['거래량'].astype(float)
            score = calculate_score(close, vol)
            entry, stop = get_trade_levels(close)
            
            # 돌파 직전 필터
            recent_high_5 = close.iloc[-5:].max()
            is_near_breakout = close.iloc[-1] >= recent_high_5 * 0.98
            
            item = {
                "name": names.get(ticker, ticker), 
                "price": close.iloc[-1], 
                "score": score, 
                "entry": entry, 
                "stop": stop
            }

            if score >= 75 and is_near_breakout: A_list.append(item)
            elif score >= 65: B_list.append(item)
            elif score >= 55: C_list.append(item)
            
            time.sleep(0.04) # API 안정성 확보
        except: continue

    # 리포트 생성 및 전송
    msg = f"<b>📊 [등급별 매집 리포트]</b>\n📅 {last_date}\n"
    msg += "━━━━━━━━━━━━━━━━━━\n\n"

    msg += "<b>🔥 A급 (즉시 매매)</b>\n"
    if A_list:
        for i in sorted(A_list, key=lambda x: x['score'], reverse=True)[:5]:
            msg += f"• <b>{i['name']}</b> ({i['score']}점)\n"
            msg += f"  현재: {int(i['price']):,} | 🚀 {int(i['entry']):,} / ⛔ {int(i['stop']):,}\n\n"
    else: msg += "없음\n\n"

    msg += "<b>👀 B급 (관찰)</b>\n"
    msg += ", ".join([f"<b>{x['name']}</b>" for x in sorted(B_list, key=lambda x: x['score'], reverse=True)[:8]]) + "\n\n"

    msg += "<b>🌱 C급 (매집)</b>\n"
    msg += ", ".join([x['name'] for x in sorted(C_list, key=lambda x: x['score'], reverse=True)[:10]])

    send_telegram(msg)
    print(f"✅ 완료 | A:{len(A_list)} B:{len(B_list)} C:{len(C_list)}")

if __name__ == "__main__":
    run_scanner()
