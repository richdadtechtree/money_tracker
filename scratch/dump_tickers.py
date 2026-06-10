from database import get_db

conn = get_db()
cur = conn.cursor()

print("=== All Stocks ===")
cur.execute("SELECT id, name, ticker, current_price, ath FROM stocks ORDER BY id")
for r in cur.fetchall():
    print(dict(r))

print("\n=== All ETFs ===")
cur.execute("SELECT id, name, ticker, current_price, ath FROM etf ORDER BY id")
for r in cur.fetchall():
    print(dict(r))

conn.close()
