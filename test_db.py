from database import get_db
try:
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT id, category FROM etf LIMIT 1")
    print(cur.fetchone())
    db.close()
except Exception as e:
    print(f"Error: {e}")
