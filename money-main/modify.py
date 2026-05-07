import os
import re

def refactor_app_py():
    with open('app.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. ? -> %s
    content = content.replace('?', '%s')

    # 2. strftime('%Y-%m', date) -> to_char(date::date, 'YYYY-MM')
    content = re.sub(r"strftime\('%Y-%m',\s*([^)]+)\)", r"to_char(\1::date, 'YYYY-MM')", content)
    content = re.sub(r"strftime\('%Y',\s*([^)]+)\)", r"to_char(\1::date, 'YYYY')", content)
    content = re.sub(r"strftime\('%m',\s*([^)]+)\)", r"to_char(\1::date, 'MM')", content)

    # 3. db.execute() -> cur = db.cursor(); cur.execute(); cur.close()
    
    # We will use AST to safely replace `db.execute` patterns
    # Actually, a regex might be faster and safer for simple multi-line matching if done carefully,
    # but let's do a reliable AST transformer.
    import ast
    try:
        from ast import unparse
    except ImportError:
        pass
        # fallback to simple regex approach for multi-line
        pass

    # Simple approach: let's replace db.execute -> __db_execute(db, ...)
    # Wait, if we define a helper function at the top of app.py:
    # def db_execute(db, query, params=None):
    #     cur = db.cursor()
    #     if params: cur.execute(query, params)
    #     else: cur.execute(query)
    #     return cur
    # And then we replace `db.execute(` with `db_execute(db, `.
    # But wait! A cursor object in psycopg2 supports `.fetchone()`, `.fetchall()`.
    # And if we return the cursor, the caller can do `rows = db_execute(db, query).fetchall()`.
    # But wait, the cursor MUST be closed! If we just return `cur`, and they do `.fetchall()`, 
    # the cursor is never closed explicitly! It gets garbage collected, which does close it, 
    # but the user said "반드시 cur.close()로 닫아주는 로직 추가".
    
    # Let's write a smarter script that reads app.py and replaces `db.execute(...)` with `with db.cursor() as cur: cur.execute(...)`?
    # No, we will write a script that does it using `ast` and replaces it inline.

    lines = content.split('\n')
    new_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Edge case: existing = db.execute(...).fetchone()
        if 'db.execute(' in line:
            indent = line[:len(line) - len(line.lstrip())]
            
            stmt = line
            start_idx = stmt.find('db.execute(') + len('db.execute(') - 1
            paren_count = 0
            j = start_idx
            while True:
                while j < len(stmt):
                    if stmt[j] == '(': paren_count += 1
                    elif stmt[j] == ')': paren_count -= 1
                    if paren_count == 0:
                        break
                    j += 1
                if paren_count == 0:
                    break
                i += 1
                stmt += '\n' + lines[i]

            # stmt contains the entire statement (could be multiline)
            end_idx = j
            exec_args = stmt[start_idx+1:end_idx]
            
            # What follows db.execute(...)?
            # It could be `.fetchall()`, `.fetchone()[0]`, or nothing.
            suffix = stmt[end_idx+1:].strip()
            
            if stmt.lstrip().startswith('db.execute('):
                # pattern: db.execute(...)
                new_lines.append(f"{indent}cur = db.cursor()")
                # We need to preserve newlines in exec_args? exec_args might have newlines.
                exec_call = f"cur.execute({exec_args})"
                new_lines.extend([indent + l.lstrip() if idx>0 else indent + l.lstrip() for idx, l in enumerate(exec_call.split('\n'))])
                new_lines.append(f"{indent}cur.close()")
            else:
                # pattern: var = db.execute(...) or if db.execute(...)
                # This is tricky if it's inside `return db.execute(...)` or `if db.execute(...)`
                # Let's extract the variable assignment
                # "rows = db.execute(query, params).fetchall()" ->
                # cur = db.cursor()
                # cur.execute(query, params)
                # rows = cur.fetchall()
                # cur.close()
                
                # Check if it's an assignment
                eq_idx = stmt.find('=')
                if eq_idx != -1 and eq_idx < start_idx:
                    var_name = stmt[:eq_idx].strip()
                    new_lines.append(f"{indent}cur = db.cursor()")
                    exec_call = f"cur.execute({exec_args})"
                    new_lines.extend([indent + l.lstrip() if idx>0 else indent + l.lstrip() for idx, l in enumerate(exec_call.split('\n'))])
                    new_lines.append(f"{indent}{var_name} = cur{suffix}")
                    new_lines.append(f"{indent}cur.close()")
                else:
                    # Not a simple assignment. E.g. "total = sum(r['amount'] for r in db.execute(...).fetchall())"
                    # We will create a temp variable.
                    temp_var = "tmp_cur"
                    new_lines.append(f"{indent}{temp_var} = db.cursor()")
                    exec_call = f"{temp_var}.execute({exec_args})"
                    new_lines.extend([indent + l.lstrip() if idx>0 else indent + l.lstrip() for idx, l in enumerate(exec_call.split('\n'))])
                    
                    # replace db.execute(...) with tmp_cur
                    new_stmt = stmt[:stmt.find('db.execute(')] + temp_var + stmt[end_idx+1:]
                    new_lines.append(new_stmt)
                    new_lines.append(f"{indent}{temp_var}.close()")
        else:
            new_lines.append(line)
        i += 1

    with open('app.py', 'w', encoding='utf-8') as f:
        f.write('\n'.join(new_lines))

if __name__ == '__main__':
    refactor_app_py()
