import sys
import os
sys.path.append(os.path.abspath('.'))

# Load .env first if it exists
if os.path.exists('.env'):
    with open('.env') as f:
        for line in f:
            if '=' in line and not line.startswith('#'):
                k, v = line.strip().split('=', 1)
                os.environ[k] = v

from app import _run_price_update_logic

results = _run_price_update_logic()
print("=== Price Update Logic Results ===")
print("Stocks updated:", len(results.get('stocks', [])))
print("ETFs updated:", len(results.get('etf', [])))
print("Crypto updated:", len(results.get('crypto', [])))
print("Split plans updated:", len(results.get('split_plans', [])))
print("\n=== Errors ===")
for err in results.get('errors', []):
    print(err)
