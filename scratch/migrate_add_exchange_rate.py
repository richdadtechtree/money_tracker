from database import get_db
import re

def is_foreign_ticker(ticker):
    return bool(ticker) and not bool(re.match(r'^\d{6}$', str(ticker)))

conn = get_db()
cur = conn.cursor()

print("Running migrations to add exchange_rate to transaction tables...")

# 1. Add column
try:
    cur.execute("ALTER TABLE stock_tx ADD COLUMN IF NOT EXISTS exchange_rate REAL DEFAULT 1.0")
    print("Added exchange_rate to stock_tx")
except Exception as e:
    print("Error adding to stock_tx:", e)

try:
    cur.execute("ALTER TABLE etf_tx ADD COLUMN IF NOT EXISTS exchange_rate REAL DEFAULT 1.0")
    print("Added exchange_rate to etf_tx")
except Exception as e:
    print("Error adding to etf_tx:", e)

conn.commit()

# 2. Update existing foreign stock transactions with exchange rates from cash adjustments or 1380.0
cur.execute("""
    SELECT t.id, t.price, t.quantity, t.fee, s.ticker
    FROM stock_tx t
    JOIN stocks s ON t.stock_id = s.id
""")
stock_txs = cur.fetchall()
for tx in stock_txs:
    if is_foreign_ticker(tx['ticker']):
        # check cash adjustment
        c2 = conn.cursor()
        c2.execute("SELECT amount FROM cash_auto_adjustments WHERE source_type='stock_tx' AND source_id=%s", (tx['id'],))
        row = c2.fetchone()
        rate = 1380.0
        if row:
            total_usd = float(tx['price']) * float(tx['quantity']) + float(tx['fee'] or 0)
            if total_usd > 0:
                rate = abs(float(row['amount'])) / total_usd
        c2.execute("UPDATE stock_tx SET exchange_rate=%s WHERE id=%s", (rate, tx['id']))
        c2.close()
        print(f"Updated stock_tx id {tx['id']} exchange_rate to {rate:.2f}")

# 3. Update existing foreign ETF transactions
cur.execute("""
    SELECT t.id, t.price, t.quantity, t.fee, e.ticker
    FROM etf_tx t
    JOIN etf e ON t.etf_id = e.id
""")
etf_txs = cur.fetchall()
for tx in etf_txs:
    if is_foreign_ticker(tx['ticker']):
        c2 = conn.cursor()
        c2.execute("SELECT amount FROM cash_auto_adjustments WHERE source_type='etf_tx' AND source_id=%s", (tx['id'],))
        row = c2.fetchone()
        rate = 1380.0
        if row:
            total_usd = float(tx['price']) * float(tx['quantity']) + float(tx['fee'] or 0)
            if total_usd > 0:
                rate = abs(float(row['amount'])) / total_usd
        c2.execute("UPDATE etf_tx SET exchange_rate=%s WHERE id=%s", (rate, tx['id']))
        c2.close()
        print(f"Updated etf_tx id {tx['id']} exchange_rate to {rate:.2f}")

conn.commit()
conn.close()
print("Migration complete!")
