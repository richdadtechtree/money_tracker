import sys
import os
sys.path.append(os.path.abspath('.'))

from app import _fetch_stock_price

print("122630 price:", _fetch_stock_price('122630'))
