from database import get_db

conn = get_db()
cur = conn.cursor()

# Get all triggers in postgres
cur.execute("""
    SELECT event_object_table, trigger_name, event_manipulation, action_statement
    FROM information_schema.triggers
""")
print("=== Triggers ===")
for r in cur.fetchall():
    print(dict(r))

conn.close()
