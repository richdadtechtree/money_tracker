from app import app
client = app.test_client()

def test_route(url):
    print(f"Testing {url} ...")
    res = client.get(url)
    print("Status:", res.status_code)
    try:
        data = res.get_json()
        print("Data length:", len(data) if isinstance(data, list) else "Not list")
        if data and isinstance(data, list):
            print("First item keys:", data[0].keys())
    except Exception as e:
        print("Data (raw):", res.get_data(as_text=True)[:200])

test_route('/api/stocks')
test_route('/api/etf')
test_route('/api/crypto')
test_route('/api/ipo')
