from database import get_db

conn = get_db()
cur = conn.cursor()

print("=== cash_auto_adjustments ===")
cur.execute("SELECT * FROM cash_auto_adjustments WHERE source_type IN ('etf_tx', 'stock_tx') ORDER BY id")
for r in cur.fetchall():
    print(dict(r))

print("\n=== etf_tx (TQQQ buys) ===")
cur.execute("""
    SELECT t.id, t.etf_id, t.tx_date, t.tx_type, t.price, t.quantity, t.fee, e.name, e.ticker
    FROM etf_tx t JOIN etf e ON t.etf_id = e.id
    WHERE e.ticker = 'TQQQ'
""")
for r in cur.fetchall():
    print(dict(r))

conn.close()
