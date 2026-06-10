from database import get_db
import math

conn = get_db()
cur = conn.cursor()

# Update stocks
cur.execute("SELECT id, name, ticker, current_price FROM stocks")
for r in cur.fetchall():
    if r['current_price'] is None or math.isnan(r['current_price']) or r['current_price'] == 0:
        price = 100.0
        if r['ticker'] == 'AAPL': price = 220.0
        elif r['ticker'] == 'TSLA': price = 180.0
        elif r['ticker'] == 'KO': price = 62.0
        
        cur.execute("UPDATE stocks SET current_price = %s WHERE id = %s", (price, r['id']))
        print(f"Restored stock {r['name']} ({r['ticker']}) price to {price}")

# Update ETF
cur.execute("SELECT id, name, ticker, current_price FROM etf")
for r in cur.fetchall():
    if r['current_price'] is None or math.isnan(r['current_price']) or r['current_price'] == 0:
        price = 100.0
        if r['ticker'] == 'SCHD': price = 82.0
        elif r['ticker'] == 'QQQI': price = 52.0
        elif r['ticker'] == 'TQQQ': price = 65.0
        
        cur.execute("UPDATE etf SET current_price = %s WHERE id = %s", (price, r['id']))
        print(f"Restored ETF {r['name']} ({r['ticker']}) price to {price}")

conn.commit()
conn.close()
