import os
import requests
import yfinance as yf
import pandas as pd

# 텔레그램 설정
def send_telegram_message(message):
    token = os.environ['TELEGRAM_TOKEN']
    chat_id = os.environ['TELEGRAM_CHAT_ID']
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {'chat_id': chat_id, 'text': message, 'parse_mode': 'Markdown'}
    requests.post(url, json=payload)

def check_stocks():
    # 관심 종목 리스트 (한국 주식은 .KS 또는 .KQ를 붙입니다)
    # 예: 삼성전자(005930.KS), SK하이닉스(000660.KS), 에코프로비엠(247540.KQ)
    target_stocks = ['005930.KS', '000660.KS', '247540.KQ', '035720.KS', 'NVDA', 'AAPL']
    
    found_list = []
    
    for symbol in target_stocks:
        ticker = yf.Ticker(symbol)
        # 최근 2일간의 데이터 가져오기
        df = ticker.history(period="2d")
        
        if len(df) < 2:
            continue
            
        prev_close = df['Close'].iloc[-2] # 전일 종가
        curr_close = df['Close'].iloc[-1] # 현재(당일) 종가
        
        # 수익률 계산
        change_percent = ((curr_close - prev_close) / prev_close) * 100
        
        # 조건 설정: 3% 이상 상승한 경우
        if change_percent >= 3.0:
            found_list.append(f"🚀 *{symbol}*\n현재가: {curr_close:,.0f}\n상승률: {change_percent:.2f}%")

    # 결과 전송
    if found_list:
        message = "✅ **오늘의 조건 만족 종목**\n\n" + "\n\n".join(found_list)
        send_telegram_message(message)
    else:
        # 조건에 맞는 게 없으면 알림을 안 보내거나 확인용 메시지만 보냄
        print("조건에 맞는 종목이 없습니다.")

if __name__ == "__main__":
    check_stocks()
