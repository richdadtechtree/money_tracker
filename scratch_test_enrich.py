import os
import psycopg2
from database import get_db

# Mock rows_to_list or other things if needed
def rows_to_list(rows):
    return [dict(r) for r in rows]

conn = get_db()
cur = conn.cursor()

# Get real_estate
cur.execute("SELECT * FROM real_estate")
rows = cur.fetchall()
cur.close()

from app import _re_enrich
enriched = _re_enrich(conn, rows)
print("--- Enriched Current Real Estate ---")
for r in enriched:
    print({k: r[k] for k in ['id', 'name', 'purchase_price', 'current_price', 'deposit', 'real_inv', 'net_gain', 'real_roi']})

conn.close()
