import sys
import os
import time

sys.path.append('/Users/leehyungjun/python work/money')

from app import app

client = app.test_client()

def test_endpoint(url):
    print(f"\nTesting: {url}")
    # Simulating session user info using a context manager
    with client.session_transaction() as sess:
        sess['user'] = {
            'email': 'bbonoyo@gmail.com',
            'name': 'Test User'
        }
    
    # First request (Cache Miss)
    start_time = time.time()
    res = client.get(url)
    elapsed = time.time() - start_time
    print(f"[First Run] Status: {res.status_code}, Time: {elapsed:.4f} seconds")
    
    # Second request (Cache Hit - should be < 5ms)
    start_time = time.time()
    res2 = client.get(url)
    elapsed2 = time.time() - start_time
    print(f"[Second Run] Status: {res2.status_code}, Time: {elapsed2:.4f} seconds")
    
    if res.status_code == 200:
        data = res.get_json()
        if isinstance(data, dict):
            if 'error' in data:
                print("Error returned in JSON:", data['error'])
            else:
                print("Keys:", list(data.keys()))
        elif isinstance(data, list):
            print(f"List length: {len(data)}")
    else:
        print("Raw Output (truncated):", res.get_data(as_text=True)[:150])

print("Running authenticated endpoint queries...")
test_endpoint('/api/tech-tree-data')
test_endpoint('/api/asset-history')
test_endpoint('/api/budget?year=2026&month=05')
test_endpoint('/api/real-estate')
