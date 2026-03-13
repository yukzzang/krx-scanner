import os
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import time

# 텔레그램 설정 로드 (GitHub Secrets)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def get_krx_tickers():
    print("🔎 종목 리스트 수집 시작...")
    try:
        # GitHub Actions 환경에서도 차단되지 않는 안정적인 데이터 경로
        url = "https://raw.githubusercontent.com/mrstock/KoreaStockCode/master/KoreaStockCode.csv"
        df = pd.read_csv(url, dtype={'code': str})
        
        # 시장에 따른 티커 생성 (.KS 또는 .KQ)
        df['ticker'] = np.where(df['market'] == 'KOSPI', df['code'] + ".KS", df['code'] + ".KQ")
        
        # 전체 리스트 중 시총 상위권인 앞부분 400개만 스캔 (차단 방지 및 속도 향상)
        tickers = df['ticker'].tolist()[:400]
        print(f"🚀 {len(tickers)}개 티커 로드 성공")
        return tickers
    except Exception as e:
        print(f"⚠️ 리스트 로드 실패 ({e}). 비상용 대형주 리스트로 전환합니다.")
        return ["005930.KS", "000660.KS", "035420.KS", "035720.KS", "005380.KS", "068270.KS", "005490.KS"]

def main():
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("❌ 텔레그램 TOKEN/ID 설정을 확인하세요.")
        return

    tickers = get_krx_tickers()
    found_stocks = []
    
    print("⏳ 시가총액 5,000억 이상 종목 필터링 중...")

    for i, t in enumerate(tickers):
        try:
            stock = yf.Ticker(t)
            # fast_info를 사용하면 일반 info보다 훨씬 빠르게 시총을 가져옵니다.
            m_cap = stock.fast_info.get('market_cap')
            
            if m_cap and m_cap >= 500_000_000_000: # 5,000억 원
                current_price = stock.fast_info.get('last_price')
                found_stocks.append({
                    "ticker": t,
                    "price": int(current_price) if current_price else 0,
                    "m_cap": round(m_cap / 100_000_000_000, 1) # 단위: 천억
                })
                print(f"🎯 포착: {t} (시총: {found_stocks[-1]['m_cap']}천억)")
        except:
            continue
        
        # 20개마다 짧은 휴식 (서버 차단 방어)
        if i % 20 == 0:
            time.sleep(0.5)
        
        # 메시지 너무 길어지는 것 방지 (최대 20개)
        if len(found_stocks) >= 20:
            break

    if found_stocks:
        # 시총 높은 순으로 정렬
        found_stocks.sort(key=lambda x: x['m_cap'], reverse=True)
        
        msg = "🏢 **국내주식 시총 5,000억 이상 종목**\n\n"
        for s in found_stocks:
            msg += f"✅ *{s['ticker']}*\n"
            msg += f"   - 현재가: {s['price']:,}원 | 시총: {s['m_cap']}천억\n\n"
        
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})
        print("✅ 텔레그램 전송 완료")
    else:
        print("📭 조건에 맞는 종목이 없습니다.")

if __name__ == "__main__":
    main()
