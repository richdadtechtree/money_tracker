from app import app
with app.test_client() as client:
    resp = client.get('/api/etf')
    print("Status:", resp.status_code)
