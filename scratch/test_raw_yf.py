import requests
res = requests.get(
    'https://query2.finance.yahoo.com/v8/finance/chart/SCHD',
    params={'interval': '1d', 'range': '5d'},
    headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
)
print("SCHD Status:", res.status_code)
print("SCHD Meta:", res.json().get('chart', {}).get('result', [])[0].get('meta', {}))
closes = res.json().get('chart', {}).get('result', [])[0].get('indicators', {}).get('quote', [{}])[0].get('close', [])
print("SCHD Closes:", closes)
