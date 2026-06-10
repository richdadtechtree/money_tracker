import sys
import os
sys.path.append(os.path.abspath('.'))

from app import app
client = app.test_client()

with client.session_transaction() as sess:
    sess['user'] = {
        'email': 'bbonoyo@gmail.com',
        'name': 'Test User'
    }

res = client.post('/api/cash-auto-adjustments/recalc-foreign')
print("Status:", res.status_code)
print("Response:", res.get_json())
