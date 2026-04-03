import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import os
import time
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
# 📅 데이터 안전 날짜 찾기 (수정됨)
# ==========================================
def get_safe_business_day():
    # 현재 시간(한국 시간 고려) 기준 
    # 당일 데이터는 저녁 늦게 업데이트되므로, 안전하게 '어제'부터 역산 시작
    for i in range(1, 11): 
        target_d = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
        try:
            # 해당 날짜의 시가총액 데이터를 호출
            df = stock.get_market_cap(target_d)
            
            # '시가총액' 컬럼이 실제로 존재하고 데이터가 있는지 확인
            if not df.empty and '시가총액' in df.columns:
                print(f"✅ 데이터 확인됨: {target_d}")
                return target_d
        except:
            continue
    # 정 안되면 어제 날짜 강제 반환
    return (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")

# ==========================================
# 📊 점수 계산 및 레벨 설정 (이전과 동일)
# ==========================================
def calculate_score(close, vol):
    score = 0
    curr_close = close.iloc[-1]
    avg_vol_20 = vol.iloc[-21:-1].mean() + 1e-9
    vol_ratio = vol.iloc[-1] / avg_vol_20

    if 0.3 < vol_ratio < 0.7: score += 25
    elif 0.2 < vol_ratio < 1.0: score += 15

    ma5, ma20, ma60 = close.rolling(5).mean().iloc[-1], close.rolling(20).mean().iloc[-1], close.rolling(60).mean().iloc[-1]
    ma_gap = max(ma5, ma20, ma60) / (min(ma5, ma20, ma60) + 1e-9)
    if ma_gap < 1.03: score += 20
    elif ma_gap < 1.05: score += 10

    if close.rolling(60).mean().iloc[-1] >= close.rolling(60).mean().iloc[-5]: score += 15
    if curr_close > close.iloc[-60:].max() * 0.85: score += 15
    range_10 = (close.iloc[-10:].max() - close.iloc[-10:].min()) / (curr_close + 1e-9)
    if range_10 < 0.05: score += 15
    elif range_10 < 0.08: score += 10
    if close.iloc[-1] >= close.iloc[-2] >= close.iloc[-3]: score += 10
    return score

def get_trade_levels(close):
    return close.iloc[-10:].max() * 1.005, close.iloc[-10:].min() * 0.98

# ==========================================
# 🚀 메인 스캐너 (에러 방어 강화)
# ==========================================
def run_scanner():
    print("🚀 스캐너 시작...")
    
    last_date = get_safe_business_day()
    start_date = (datetime.strptime(last_date, "%Y%m%d") - timedelta(days=150)).strftime("%Y%m%d")

    try:
        names = {**stock.get_market_ticker_name("KOSPI"), **stock.get_market_ticker_name("KOSDAQ")}
        
        # ⚠️ KeyError 방지를 위한 개별 로드 및 검증
        df_k = stock.get_market_cap(last_date, market="KOSPI")
        df_q = stock.get_market_cap(last_date, market="KOSDAQ")

        if df_k.empty or '시가총액' not in df_k.columns:
            send_telegram(f"⚠️ {last_date} KOSPI 데이터 구조 오류 (업데이트 대기 중)")
            return

        tickers = df_k.sort_values('시가총액', ascending=False).head(300).index.tolist() + \
                  df_q.sort_values('시가총액', ascending=False).head(400).index.tolist()
        
        print(f"🔍 분석 대상: {len(tickers)}개 종목")

    except Exception as e:
        send_telegram(f"❌ 초기 로딩 실패: {str(e)}")
        return

    A_list, B_list, C_list = [], [], []

    for idx, ticker in enumerate(tickers):
        try:
            df = stock.get_market_ohlcv_by_date(start_date, last_date, ticker)
            if len(df) < 75: continue

            close, vol = df['종가'].astype(float), df['거래량'].astype(float)
            score = calculate_score(close, vol)
            entry, stop = get_trade_levels(close)
            is_near_breakout = close.iloc[-1] >= (close.iloc[-5:].max() * 0.98)

            item = {"name": names.get(ticker, ticker), "price": close.iloc[-1], "score": score, "entry": entry, "stop": stop}

            if score >= 75 and is_near_breakout: A_list.append(item)
            elif score >= 65: B_list.append(item)
            elif score >= 55: C_list.append(item)
            
            if idx % 100 == 0: print(f"进度: {idx}/{len(tickers)}")
            time.sleep(0.05)
        except: continue

    # 메시지 생성 (생략 - 이전과 동일)
    report = f"<b>📊 [등급별 매집 리포트]</b>\n📅 {last_date}\n━━━━━━━━━━━━━━━━━━\n\n"
    report += "<b>🔥 A급 (즉시 관찰)</b>\n"
    if A_list:
        for i in sorted(A_list, key=lambda x: x['score'], reverse=True)[:5]:
            report += f"• <b>{i['name']}</b> ({i['score']}점)\n  현재: {int(i['price']):,} | 🚀 {int(i['entry']):,} / ⛔ {int(i['stop']):,}\n\n"
    else: report += "대상 없음\n\n"
    
    report += "<b>👀 B급 (관찰)</b>\n"
    report += ", ".join([f"<b>{x['name']}</b>({x['score']})" for x in sorted(B_list, key=lambda x: x['score'], reverse=True)[:8]]) + "\n\n"
    
    report += "<b>🌱 C급 (매집 중)</b>\n"
    report += ", ".join([x['name'] for x in sorted(C_list, key=lambda x: x['score'], reverse=True)[:10]])

    send_telegram(report)
    print("✅ 스캔 완료")

if __name__ == "__main__":
    run_scanner()
