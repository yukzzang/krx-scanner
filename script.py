import os
import yfinance as yf
import pandas as pd
import requests
import time

# 텔레그램 설정 로드
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def get_krx_tickers():
    """
    안정적으로 종목 리스트를 확보하기 위해 
    주요 지수(KOSPI 200, KOSDAQ 150) 종목 리스트를 활용합니다.
    """
    print("🔎 종목 리스트 수집 시작...")
    try:
        url = "https://raw.githubusercontent.com/mrstock/KoreaStockCode/master/KoreaStockCode.csv"
        df = pd.read_csv(url, dtype={'code': str})
        df['full_code'] = df.apply(lambda x: f"{x['code']}.KS" if x['market'] == 'KOSPI' else f"{x['code']}.KQ", axis=1)
        # 전체 중 상위 500개만 스캔 (IP 차단 방지용)
        return df['full_code'].tolist()[:500]
    except:
        # 실패 시 비상용 대형주 리스트
        return ["005930.KS", "000660.KS", "035420.KS", "035720.KS", "005380.KS"]

def main():
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("❌ 텔레그램 설정이 없습니다.")
        return

    tickers = get_krx_tickers()
    found_stocks = []
    
    print(f"🚀 총 {len(tickers)}개 종목 중 시총 5,000억 이상 필터링 시작...")

    for i, t in enumerate(tickers):
        try:
            # 주가 및 종목 정보 가져오기
            stock = yf.Ticker(t)
            info = stock.info
            
            # 시가총액(marketCap) 확인
            m_cap = info.get('marketCap')
            
            if m_cap and m_cap >= 500_000_000_000:  # 5,000억 원 이상
                name = info.get('shortName', t)
                price = info.get('currentPrice', 0)
                found_stocks.append({
                    "name": name,
                    "ticker": t,
                    "m_cap": round(m_cap / 100_000_000_000, 1), # 0000억 단위
                    "price": price
                })
                print(f"🎯 포착: {name} (시총: {found_stocks[-1]['m_cap']}천억)")
        except Exception:
            continue
        
        # 10개마다 짧은 휴식 (서버 차단 방지)
        if i % 10 == 0:
            time.sleep(0.2)
        
        # GitHub Actions 시간 제한 고려 (최대 30개까지만 찾으면 중단)
        if len(found_stocks) >= 30:
            break

    # 메시지 작성 및 전송
    if found_stocks:
        msg = "🏢 **국내주식 시총 5,000억 이상 종목**\n\n"
        for s in found_stocks:
            msg += f"✅ *{s['name']}* ({s['ticker']})\n"
            msg += f"   - 현재가: {int(s['price']):,}원 | 시총: {s['m_cap']}천억\n\n"
        
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})
        print("✅ 텔레그램 전송 성공")
    else:
        print("📭 조건에 맞는 종목이 없습니다.")

if __name__ == "__main__":
    main()
