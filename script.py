from pykrx import stock
import pandas as pd
import requests
from datetime import datetime

TOKEN = "텔레그램_BOT_TOKEN"
CHAT_ID = "텔레그램_CHAT_ID"

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": msg
    }
    requests.post(url, data=data)

def get_stocks():
    today = datetime.today().strftime("%Y%m%d")

    kospi = stock.get_market_cap_by_ticker(today, market="KOSPI")
    kosdaq = stock.get_market_cap_by_ticker(today, market="KOSDAQ")

    df = pd.concat([kospi, kosdaq])

    # 시총 5000억 이상
    filtered = df[df["시가총액"] >= 500000000000]

    result = ""
    for ticker in filtered.index:
        name = stock.get_market_ticker_name(ticker)
        cap = filtered.loc[ticker]["시가총액"]
        cap = round(cap / 100000000, 1)

        result += f"{name} ({ticker}) - {cap}억\n"

    send_telegram(result)

get_stocks()
