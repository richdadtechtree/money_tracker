import requests

tickers = ['KO', 'TSLA', 'AAPL', 'SCHD', 'QQQI', 'TQQQ']
for ticker in tickers:
    # Try with .US suffix
    sym = ticker + '.US'
    res = requests.get(
        f'https://stooq.com/q/l/?s={sym}&f=sd2t2ohlcv&h&e=csv',
        headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    )
    print(f"Ticker: {sym}, Status: {res.status_code}")
    if res.ok:
        lines = res.text.strip().split('\n')
        if len(lines) > 1:
            print("CSV line:", lines[1])
