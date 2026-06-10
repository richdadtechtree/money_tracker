import sys
import os
import requests as http_req
sys.path.append(os.path.abspath('.'))

from app import _is_krx_ticker, HAS_PYKRX

ticker = '122630'

# Test Naver basic API
try:
    res = http_req.get(
        f"https://m.stock.naver.com/api/stock/{ticker}/basic",
        headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://m.stock.naver.com/'},
        timeout=5
    )
    if res.ok:
        data = res.json()
        print("Naver mobile basic price:", data.get('closePrice'), data.get('currentPrice'))
except Exception as e:
    print("Naver mobile error:", e)

# Test Naver polling API
try:
    res = http_req.get(
        f"https://polling.finance.naver.com/api/realtime/domestic/stock/{ticker}",
        headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.naver.com/'},
        timeout=5
    )
    if res.ok:
        data = res.json()
        print("Naver polling price:", (data.get('datas') or [{}])[0].get('closePrice'), (data.get('datas') or [{}])[0].get('currentPrice'))
except Exception as e:
    print("Naver polling error:", e)

# Test Yahoo KS/KQ
try:
    for suffix in ['.KS', '.KQ']:
        sym = ticker + suffix
        res = http_req.get(
            f'https://query2.finance.yahoo.com/v8/finance/chart/{sym}',
            params={'interval': '1d', 'range': '5d'},
            headers={'User-Agent': 'Mozilla/5.0'},
            timeout=5
        )
        if res.ok:
            result = res.json().get('chart', {}).get('result', [])
            if result:
                closes = result[0].get('indicators', {}).get('quote', [{}])[0].get('close', [])
                closes = [c for c in closes if c is not None]
                print(f"Yahoo {sym} price:", closes[-1] if closes else None)
except Exception as e:
    print("Yahoo error:", e)
