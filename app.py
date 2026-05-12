from flask import Flask, render_template, request, jsonify, Response
from flask_cors import CORS
from database import get_db, init_db
from datetime import datetime, date
import json, os, shutil, sqlite3, re, csv, io, requests as http_req

try:
    import yfinance as yf
    HAS_YFINANCE = True
except ImportError:
    HAS_YFINANCE = False

try:
    from pykrx import stock as krx_stock
    HAS_PYKRX = True
except ImportError:
    HAS_PYKRX = False

try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

try:
    import xlrd
    HAS_XLRD = True
except ImportError:
    HAS_XLRD = False

app = Flask(__name__)
CORS(app)

from flask.json.provider import DefaultJSONProvider
class CustomJSONProvider(DefaultJSONProvider):
    def default(self, obj):
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        return super().default(obj)
app.json = CustomJSONProvider(app)

# ── 페이지 라우터 ────────────────────────────────────────────
@app.route('/')
def dashboard():
    return render_template('dashboard.html')

@app.route('/income')
def income():
    return render_template('income.html')

@app.route('/budget')
def budget():
    return render_template('budget.html')

@app.route('/cards')
def cards():
    return render_template('cards.html')

@app.route('/investments')
def investments():
    return render_template('investments.html')

@app.route('/realestate')
def realestate():
    return render_template('realestate.html')

@app.route('/loans')
def loans():
    return render_template('loans.html')

@app.route('/pension')
def pension():
    return render_template('pension.html')

@app.route('/cash')
def cash():
    return render_template('cash.html')

@app.route('/goals')
def goals():
    return render_template('goals.html')

@app.route('/monthly')
def monthly():
    return render_template('monthly.html')

@app.route('/tech-tree')
def tech_tree():
    return render_template('tech_tree.html')


# ── 공통 헬퍼 ────────────────────────────────────────────────
def rows_to_list(rows):
    res = []
    for r in rows:
        d = dict(r)
        for k, v in d.items():
            if isinstance(v, (date, datetime)):
                d[k] = v.isoformat()
        res.append(d)
    return res


# ── API: 수입 ────────────────────────────────────────────────
@app.route('/api/income', methods=['GET', 'POST'])
def api_income():
    db = get_db()
    if request.method == 'GET':
        year  = request.args.get('year')
        month = request.args.get('month')
        query = "SELECT * FROM income"
        params = []
        if year and month:
            query += " WHERE to_char(date::date, 'YYYY') = %s AND to_char(date::date, 'MM') = %s"
            params = [year, month.zfill(2)]
        query += " ORDER BY date DESC"
        cur = db.cursor()
        cur.execute(query, params)
        rows = cur.fetchall()
        cur.close()
        db.close()
        return jsonify(rows_to_list(rows))

    data = request.json
    base_date_str = data['date']          # 'YYYY-MM-DD'
    is_recurring  = data.get('is_recurring', False)
    repeat_months = int(data.get('repeat_months') or 1)

    if is_recurring and repeat_months > 1:
        # base_date 에서 repeat_months 개월치를 순서대로 INSERT
        from datetime import date as _date
        import calendar as _cal

        base_date = _date.fromisoformat(base_date_str)
        for i in range(repeat_months):
            y = base_date.year + (base_date.month - 1 + i) // 12
            m = (base_date.month - 1 + i) % 12 + 1
            # 말일 초과 보정 (예: 1월31일 → 2월28일)
            d = min(base_date.day, _cal.monthrange(y, m)[1])
            tx_date = _date(y, m, d).isoformat()
            cur = db.cursor()
            cur.execute(
            "INSERT INTO income (date, category, name, memo, amount) VALUES (%s,%s,%s,%s,%s)",
            (tx_date, data.get('category'), data.get('name'), data.get('memo'), data['amount'])
            )
            cur.close()
    else:
        cur = db.cursor()
        cur.execute(
        "INSERT INTO income (date, category, name, memo, amount) VALUES (%s,%s,%s,%s,%s)",
        (base_date_str, data.get('category'), data.get('name'), data.get('memo'), data['amount'])
        )
        cur.close()

    db.commit()
    db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/income/<int:rid>', methods=['PUT', 'DELETE'])
def api_income_detail(rid):
    db = get_db()
    if request.method == 'PUT':
        data = request.json
        cur = db.cursor()
        cur.execute(
        "UPDATE income SET date=%s, category=%s, name=%s, memo=%s, amount=%s WHERE id=%s",
        (data.get('date'), data.get('category'), data.get('name'),
        data.get('memo'), data.get('amount', 0), rid)
        )
        cur.close()
        db.commit()
        db.close()
        return jsonify({'ok': True})
    cur = db.cursor()
    cur.execute("DELETE FROM income WHERE id = %s", (rid,))
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True})


# ── API: 가계부 ──────────────────────────────────────────────
def _sync_card_tx(db, budget_id, data):
    """budget 저장 시 card_tx 자동 동기화"""
    card_id = data.get('card_id') or None
    if card_id:
        cur = db.cursor()
        cur.execute("SELECT id FROM card_tx WHERE budget_id = %s", (budget_id,))
        existing = cur.fetchone()
        cur.close()
        if existing:
            cur = db.cursor()
            cur.execute(
            "UPDATE card_tx SET card_id=%s, date=%s, name=%s, category=%s, amount=%s, memo=%s WHERE budget_id=%s",
            (card_id, data.get('date'), data.get('name'), data.get('category'),
            data.get('amount', 0), data.get('memo'), budget_id)
            )
            cur.close()
        else:
            cur = db.cursor()
            cur.execute(
            "INSERT INTO card_tx (card_id, date, name, category, amount, installment, memo, budget_id) VALUES (%s,%s,%s,%s,%s,1,%s,%s)",
            (card_id, data.get('date'), data.get('name'), data.get('category'),
            data.get('amount', 0), data.get('memo'), budget_id)
            )
            cur.close()
    else:
        cur = db.cursor()
        cur.execute("DELETE FROM card_tx WHERE budget_id = %s", (budget_id,))
        cur.close()


@app.route('/api/budget', methods=['GET', 'POST'])
def api_budget():
    db = get_db()
    if request.method == 'GET':
        year  = request.args.get('year')
        month = request.args.get('month')
        query = """SELECT b.*, c.card_name
                   FROM budget b
                   LEFT JOIN card_info c ON b.card_id = c.id"""
        params = []
        if year and month:
            query += " WHERE to_char(b.date::date, 'YYYY') = %s AND to_char(b.date::date, 'MM') = %s"
            params = [year, month.zfill(2)]
        query += " ORDER BY b.date DESC"
        cur = db.cursor()
        cur.execute(query, params)
        rows = cur.fetchall()
        cur.close()
        db.close()
        return jsonify(rows_to_list(rows))

    data = request.json
    cur = db.cursor()
    cur.execute(
    "INSERT INTO budget (date, category, name, type, payment_method, amount, memo, card_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
    (data['date'], data.get('category'), data.get('name'), data.get('type'),
    data.get('payment_method'), data['amount'], data.get('memo'),
    data.get('card_id') or None)
    )
    budget_id = cur.fetchone()[0]
    cur.close()
    _sync_card_tx(db, budget_id, data)
    db.commit()
    db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/budget/<int:rid>', methods=['PUT', 'DELETE'])
def api_budget_detail(rid):
    db = get_db()
    if request.method == 'PUT':
        data = request.json
        cur = db.cursor()
        cur.execute(
        "UPDATE budget SET date=%s, category=%s, name=%s, type=%s, payment_method=%s, amount=%s, memo=%s, card_id=%s WHERE id=%s",
        (data.get('date'), data.get('category'), data.get('name'), data.get('type'),
        data.get('payment_method'), data.get('amount', 0), data.get('memo'),
        data.get('card_id') or None, rid)
        )
        cur.close()
        _sync_card_tx(db, rid, data)
        db.commit()
        db.close()
        return jsonify({'ok': True})
    cur = db.cursor()
    cur.execute("DELETE FROM card_tx WHERE budget_id = %s", (rid,))
    cur.close()
    cur = db.cursor()
    cur.execute("DELETE FROM budget WHERE id = %s", (rid,))
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True})


# ── API: 카드 정보 ───────────────────────────────────────────
@app.route('/api/cards', methods=['GET', 'POST'])
def api_cards():
    db = get_db()
    if request.method == 'GET':
        cur = db.cursor()
        cur.execute("SELECT * FROM card_info ORDER BY card_num")
        rows = cur.fetchall()
        cur.close()
        db.close()
        return jsonify(rows_to_list(rows))

    data = request.json
    cur = db.cursor()
    cur.execute(
    "INSERT INTO card_info (card_num, card_name, limit_amount, payment_day, billing_day, benefit) VALUES (%s,%s,%s,%s,%s,%s)",
    (data['card_num'], data.get('card_name'), data.get('limit_amount', 0),
    data.get('payment_day'), data.get('billing_day'), data.get('benefit'))
    )
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/cards/<int:cid>', methods=['PUT', 'DELETE'])
def api_card_detail(cid):
    db = get_db()
    if request.method == 'PUT':
        data = request.json
        cur = db.cursor()
        cur.execute(
        "UPDATE card_info SET card_num=%s, card_name=%s, limit_amount=%s, payment_day=%s, billing_day=%s, benefit=%s WHERE id=%s",
        (data.get('card_num'), data.get('card_name'), data.get('limit_amount', 0),
        data.get('payment_day'), data.get('billing_day'), data.get('benefit'), cid)
        )
        cur.close()
        db.commit()
        db.close()
        return jsonify({'ok': True})
    cur = db.cursor()
    cur.execute("DELETE FROM card_info WHERE id = %s", (cid,))
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True})


# ── API: 카드 거래내역 ───────────────────────────────────────
@app.route('/api/card-tx', methods=['GET', 'POST'])
def api_card_tx():
    db = get_db()
    if request.method == 'GET':
        card_id = request.args.get('card_id')
        year    = request.args.get('year')
        month   = request.args.get('month')
        query   = "SELECT t.*, c.card_name FROM card_tx t LEFT JOIN card_info c ON t.card_id = c.id"
        params  = []
        conds   = []
        if card_id:
            conds.append("t.card_id = %s"); params.append(card_id)
        if year and month:
            conds.append("to_char(t.date::date, 'YYYY') = %s"); params.append(year)
            conds.append("to_char(t.date::date, 'MM') = %s"); params.append(month.zfill(2))
        if conds:
            query += " WHERE " + " AND ".join(conds)
        query += " ORDER BY t.date DESC"
        cur = db.cursor()
        cur.execute(query, params)
        rows = cur.fetchall()
        cur.close()
        total = sum(r['amount'] for r in rows)
        # 카테고리별 집계 (없는 건 → '미분류')
        cat_map = {}
        for r in rows:
            cat = r['category'] or '미분류'
            cat_map[cat] = cat_map.get(cat, 0) + r['amount']
        by_category = sorted(
            [{'category': c, 'total': t} for c, t in cat_map.items()],
            key=lambda x: x['total'], reverse=True
        )
        # 자금 그룹별 집계
        cur = db.cursor()
        cur.execute("SELECT id, name FROM fund_groups")
        fund_group_names = {r['id']: r['name'] for r in cur.fetchall()}
        cur.close()
        fund_map = {}
        for r in rows:
            gid = r['fund_group_id']
            name = fund_group_names.get(gid, '미지정') if gid else '미지정'
            fund_map[name] = fund_map.get(name, 0) + r['amount']
        by_fund_group = sorted(
            [{'name': n, 'total': t} for n, t in fund_map.items()],
            key=lambda x: x['total'], reverse=True
        )
        db.close()
        return jsonify({'rows': rows_to_list(rows), 'total': total,
                        'by_category': by_category, 'by_fund_group': by_fund_group})

    data = request.json
    cur = db.cursor()
    cur.execute(
    "INSERT INTO card_tx (card_id, date, name, category, amount, installment, memo) VALUES (%s,%s,%s,%s,%s,%s,%s)",
    (data.get('card_id'), data['date'], data.get('name'), data.get('category'),
    data['amount'], data.get('installment', 1), data.get('memo'))
    )
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/card-tx/<int:rid>', methods=['PUT', 'DELETE'])
def api_card_tx_detail(rid):
    db = get_db()
    if request.method == 'PUT':
        data = request.json
        category = data.get('category') or ''
        locked = 1 if category else 0
        fund_group_id = data.get('fund_group_id')
        fund_group_locked = 1 if fund_group_id else 0
        cur = db.cursor()
        cur.execute(
        "UPDATE card_tx SET card_id=%s, date=%s, name=%s, category=%s, amount=%s, installment=%s, memo=%s,"
        " category_locked=%s, fund_group_id=%s, fund_group_locked=%s WHERE id=%s",
        (data.get('card_id'), data.get('date'), data.get('name'), category,
        data.get('amount', 0), data.get('installment', 1), data.get('memo'),
        locked, fund_group_id, fund_group_locked, rid)
        )
        cur.close()
        db.commit()
        db.close()
        return jsonify({'ok': True})
    cur = db.cursor()
    cur.execute("DELETE FROM card_tx WHERE id = %s", (rid,))
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True})


@app.route('/api/card-tx/bulk', methods=['DELETE'])
def api_card_tx_bulk_delete():
    data = request.json or {}
    ids  = data.get('ids', [])
    if not ids:
        return jsonify({'error': 'ids가 필요합니다'}), 400
    db = get_db()
    placeholders = ','.join('%s' * len(ids))
    cur = db.cursor()
    cur.execute(f"DELETE FROM card_tx WHERE id IN ({placeholders})", ids)
    deleted = cur.rowcount
    cur.close()
    db.commit(); db.close()
    return jsonify({'ok': True, 'deleted': deleted})


@app.route('/api/card-tx/auto-categorize', methods=['POST'])
def api_card_tx_auto_categorize():
    data    = request.json or {}
    card_id = data.get('card_id')
    year    = data.get('year')
    month   = data.get('month')

    db = get_db()
    query  = "SELECT id, name FROM card_tx WHERE category_locked = 0"
    params = []
    if card_id:
        query += " AND card_id = %s"; params.append(card_id)
    if year and month:
        query += " AND to_char(date::date, 'YYYY') = %s AND to_char(date::date, 'MM') = %s"
        params += [year, month.zfill(2)]

    cur = db.cursor()
    cur.execute(query, params)
    rows = cur.fetchall()
    cur.close()
    updated = 0
    for row in rows:
        hint = _get_category_hint(db, row['name'])
        if hint:
            cur = db.cursor()
            cur.execute("UPDATE card_tx SET category=%s WHERE id=%s", (hint, row['id']))
            cur.close()
            updated += 1
    db.commit()
    db.close()
    return jsonify({'ok': True, 'updated': updated})


# ── API: 주식 ────────────────────────────────────────────────
@app.route('/api/stocks', methods=['GET', 'POST'])
def api_stocks():
    db = get_db()
    if request.method == 'GET':
        cur = db.cursor()
        cur.execute("""
        SELECT s.id, s.name, s.ticker, s.current_price, s.dividend, s.memo,
        COALESCE(SUM(CASE WHEN t.tx_type='buy'  THEN t.quantity ELSE 0 END), 0) AS buy_qty,
        COALESCE(SUM(CASE WHEN t.tx_type='sell' THEN t.quantity ELSE 0 END), 0) AS sell_qty,
        COALESCE(SUM(CASE WHEN t.tx_type='buy'  THEN t.price * t.quantity + t.fee ELSE 0 END), 0) AS total_buy_amount,
        COALESCE(SUM(CASE WHEN t.tx_type='sell' THEN t.price * t.quantity - t.fee ELSE 0 END), 0) AS total_sell_amount
        FROM stocks s
        LEFT JOIN stock_tx t ON t.stock_id = s.id
        GROUP BY s.id
        ORDER BY s.name
        """)
        rows = cur.fetchall()
        cur.close()
        result = []
        for row in rows:
            r = dict(row)
            qty      = r['buy_qty'] - r['sell_qty']
            avg      = round(r['total_buy_amount'] / r['buy_qty']) if r['buy_qty'] else 0
            eval_amt = round(qty * r['current_price'])
            cost_amt = round(qty * avg)
            r['quantity']       = qty
            r['avg_price']      = avg
            r['eval_amount']    = eval_amt
            r['unrealized_pnl'] = eval_amt - cost_amt
            r['return_rate']    = round((eval_amt - cost_amt) / cost_amt * 100, 2) if cost_amt else 0
            r['realized_pnl']   = round(r['total_sell_amount'] - r['sell_qty'] * avg) if r['sell_qty'] else 0
            result.append(r)
        db.close()
        return jsonify(result)

    data = request.json
    cur = db.cursor()
    cur.execute(
    "INSERT INTO stocks (name, ticker, current_price, dividend, memo) VALUES (%s,%s,%s,%s,%s)",
    (data.get('name'), data.get('ticker'),
    data.get('current_price', 0), data.get('dividend', 0), data.get('memo'))
    )
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/stocks/<int:rid>', methods=['PUT', 'DELETE'])
def api_stocks_detail(rid):
    db = get_db()
    if request.method == 'PUT':
        data = request.json
        cur = db.cursor()
        cur.execute(
        "UPDATE stocks SET name=%s, ticker=%s, current_price=%s, dividend=%s, memo=%s WHERE id=%s",
        (data.get('name'), data.get('ticker'),
        data.get('current_price', 0), data.get('dividend', 0), data.get('memo'), rid)
        )
        cur.close()
        db.commit()
        db.close()
        return jsonify({'ok': True})
    cur = db.cursor()
    cur.execute("DELETE FROM stock_tx WHERE stock_id = %s", (rid,))
    cur.close()
    cur = db.cursor()
    cur.execute("DELETE FROM stocks WHERE id = %s", (rid,))
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True})


# ── API: 주식 거래내역 ────────────────────────────────────────
@app.route('/api/stock-tx', methods=['GET', 'POST'])
def api_stock_tx():
    db = get_db()
    if request.method == 'GET':
        stock_id = request.args.get('stock_id')
        query  = "SELECT t.*, s.name, s.ticker FROM stock_tx t LEFT JOIN stocks s ON t.stock_id = s.id"
        params = []
        if stock_id:
            query += " WHERE t.stock_id = %s"
            params.append(stock_id)
        query += " ORDER BY t.tx_date DESC, t.id DESC"
        cur = db.cursor()
        cur.execute(query, params)
        rows = cur.fetchall()
        cur.close()
        db.close()
        return jsonify(rows_to_list(rows))

    data = request.json
    cur = db.cursor()
    cur.execute(
    "INSERT INTO stock_tx (stock_id, tx_date, tx_type, price, quantity, fee, memo) VALUES (%s,%s,%s,%s,%s,%s,%s)",
    (data.get('stock_id'), data.get('tx_date'), data.get('tx_type'),
    data.get('price', 0), data.get('quantity', 0), data.get('fee', 0), data.get('memo'))
    )
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/stock-tx/<int:rid>', methods=['PUT', 'DELETE'])
def api_stock_tx_detail(rid):
    db = get_db()
    if request.method == 'PUT':
        data = request.json
        cur = db.cursor()
        cur.execute(
        "UPDATE stock_tx SET stock_id=%s, tx_date=%s, tx_type=%s, price=%s, quantity=%s, fee=%s, memo=%s WHERE id=%s",
        (data.get('stock_id'), data.get('tx_date'), data.get('tx_type'),
        data.get('price', 0), data.get('quantity', 0), data.get('fee', 0), data.get('memo'), rid)
        )
        cur.close()
        db.commit()
        db.close()
        return jsonify({'ok': True})
    cur = db.cursor()
    cur.execute("DELETE FROM stock_tx WHERE id = %s", (rid,))
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True})


# ── API: ETF ─────────────────────────────────────────────────
@app.route('/api/etf', methods=['GET', 'POST'])
def api_etf():
    db = get_db()
    if request.method == 'GET':
        cur = db.cursor()
        cur.execute("SELECT * FROM etf ORDER BY name")
        rows = cur.fetchall()
        cur.close()
        db.close()
        return jsonify(rows_to_list(rows))

    data = request.json
    cur = db.cursor()
    cur.execute(
    "INSERT INTO etf (name, ticker, buy_date, buy_price, quantity, current_price, etf_type, memo) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
    (data.get('name'), data.get('ticker'), data.get('buy_date'),
    data.get('buy_price', 0), data.get('quantity', 0),
    data.get('current_price', 0), data.get('etf_type'), data.get('memo'))
    )
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/etf/<int:rid>', methods=['PUT', 'DELETE'])
def api_etf_detail(rid):
    db = get_db()
    if request.method == 'PUT':
        data = request.json
        cur = db.cursor()
        cur.execute(
        "UPDATE etf SET name=%s, ticker=%s, buy_date=%s, buy_price=%s, quantity=%s, current_price=%s, etf_type=%s, memo=%s WHERE id=%s",
        (data.get('name'), data.get('ticker'), data.get('buy_date'),
        data.get('buy_price', 0), data.get('quantity', 0),
        data.get('current_price', 0), data.get('etf_type'), data.get('memo'), rid)
        )
        cur.close()
        db.commit()
        db.close()
        return jsonify({'ok': True})
    cur = db.cursor()
    cur.execute("DELETE FROM etf WHERE id = %s", (rid,))
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True})


# ── API: 코인 ────────────────────────────────────────────────
@app.route('/api/crypto', methods=['GET', 'POST'])
def api_crypto():
    db = get_db()
    if request.method == 'GET':
        cur = db.cursor()
        cur.execute("SELECT * FROM crypto ORDER BY name")
        rows = cur.fetchall()
        cur.close()
        db.close()
        return jsonify(rows_to_list(rows))

    data = request.json
    cur = db.cursor()
    cur.execute(
    "INSERT INTO crypto (name, symbol, exchange, buy_date, buy_price, quantity, current_price, memo) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
    (data.get('name'), data.get('symbol'), data.get('exchange'), data.get('buy_date'),
    data.get('buy_price', 0), data.get('quantity', 0),
    data.get('current_price', 0), data.get('memo'))
    )
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/crypto/<int:rid>', methods=['PUT', 'DELETE'])
def api_crypto_detail(rid):
    db = get_db()
    if request.method == 'PUT':
        data = request.json
        cur = db.cursor()
        cur.execute(
        "UPDATE crypto SET name=%s, symbol=%s, exchange=%s, buy_date=%s, buy_price=%s, quantity=%s, current_price=%s, memo=%s WHERE id=%s",
        (data.get('name'), data.get('symbol'), data.get('exchange'), data.get('buy_date'),
        data.get('buy_price', 0), data.get('quantity', 0),
        data.get('current_price', 0), data.get('memo'), rid)
        )
        cur.close()
        db.commit()
        db.close()
        return jsonify({'ok': True})
    cur = db.cursor()
    cur.execute("DELETE FROM crypto WHERE id = %s", (rid,))
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True})


# ── API: 현재가 업데이트 ─────────────────────────────────────
import time

def _is_krx_ticker(ticker: str) -> bool:
    """6자리 숫자면 국내 KRX 종목으로 판단"""
    return bool(re.match(r'^\d{6}$', ticker))


def _fetch_krx_price(ticker: str) -> float | None:
    """pykrx로 국내 주식 최근 종가 조회"""
    if not HAS_PYKRX:
        return None
    try:
        from datetime import date, timedelta
        end = date.today().strftime('%Y%m%d')
        start = (date.today() - timedelta(days=7)).strftime('%Y%m%d')
        df = krx_stock.get_market_ohlcv_by_date(start, end, ticker)
        if not df.empty:
            return float(df['종가'].iloc[-1])
    except Exception:
        pass
    return None


def _fetch_yf_price(ticker: str) -> float | None:
    """yfinance로 해외 주식/ETF 현재가 조회 (국내 6자리는 .KS/.KQ 변환 fallback)"""
    if not HAS_YFINANCE:
        return None
    yf_sym = (ticker + '.KS') if _is_krx_ticker(ticker) else ticker
    
    import requests
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
    })
    
    for attempt in range(2):
        try:
            t_obj = yf.Ticker(yf_sym, session=session)
            # 1. fast_info 우선 조회
            info = t_obj.fast_info
            price = info.last_price
            if price and price > 0:
                return float(price)
            
            # 2. fast_info 실패 시 history 백업 조회
            df = t_obj.history(period='1d')
            if not df.empty:
                return float(df['Close'].iloc[-1])
                
            # KS → KQ fallback
            if yf_sym.endswith('.KS'):
                t_obj2 = yf.Ticker(ticker + '.KQ', session=session)
                info2 = t_obj2.fast_info
                price2 = info2.last_price
                if price2 and price2 > 0:
                    return float(price2)
                df2 = t_obj2.history(period='1d')
                if not df2.empty:
                    return float(df2['Close'].iloc[-1])
        except Exception:
            if attempt == 0:
                time.sleep(1)
    return None


def _fetch_stock_price(ticker: str) -> float | None:
    """국내는 pykrx 우선, 실패 시 yfinance. 해외는 yfinance."""
    if _is_krx_ticker(ticker):
        price = _fetch_krx_price(ticker)
        if price:
            return price
    return _fetch_yf_price(ticker)



def _fetch_coingecko_prices(symbols: list[str]) -> dict[str, float]:
    """CoinGecko로 심볼 목록의 KRW 현재가 조회. {symbol_upper: price}"""
    if not symbols:
        return {}
    try:
        # 심볼 → id 매핑 (캐싱 없이 간단히 /simple/price의 ids 파라미터로 처리)
        # CoinGecko simple/price는 id(슬러그)를 받으므로 먼저 목록에서 id 획득
        list_res = http_req.get(
            'https://api.coingecko.com/api/v3/coins/list',
            timeout=10
        )
        if not list_res.ok:
            return {}
        coin_list = list_res.json()
        sym_upper = [s.upper() for s in symbols]
        # 심볼 → id 매핑 (동일 심볼 여러 개일 수 있어 첫 번째 사용)
        sym_to_id = {}
        for coin in coin_list:
            s = coin['symbol'].upper()
            if s in sym_upper and s not in sym_to_id:
                sym_to_id[s] = coin['id']

        ids = list(sym_to_id.values())
        if not ids:
            return {}

        price_res = http_req.get(
            'https://api.coingecko.com/api/v3/simple/price',
            params={'ids': ','.join(ids), 'vs_currencies': 'krw'},
            timeout=10
        )
        if not price_res.ok:
            return {}
        price_data = price_res.json()

        result = {}
        for sym, cid in sym_to_id.items():
            p = price_data.get(cid, {}).get('krw')
            if p:
                result[sym] = float(p)
        return result
    except Exception:
        return {}


@app.route('/api/price-update', methods=['POST'])
def api_price_update():
    """등록된 모든 종목(주식/ETF/코인)의 현재가를 외부 API로 조회 후 DB 업데이트"""
    db = get_db()
    results = {'stocks': [], 'etf': [], 'crypto': [], 'errors': []}

    # ── 주식 ──
    cur = db.cursor()
    cur.execute("SELECT id, name, ticker FROM stocks WHERE ticker IS NOT NULL AND ticker != ''")
    stock_rows = cur.fetchall()
    cur.close()

    for row in stock_rows:
        sid, name, ticker = row['id'], row['name'], row['ticker']
        price = _fetch_stock_price(ticker)
        if price:
            cur = db.cursor()
            cur.execute("UPDATE stocks SET current_price = %s WHERE id = %s", (price, sid))
            cur.close()
            results['stocks'].append({'id': sid, 'name': name, 'ticker': ticker, 'price': price, 'ok': True})
        else:
            results['errors'].append(f"주식 [{name}({ticker})]: 가격 조회 실패")
            results['stocks'].append({'id': sid, 'name': name, 'ticker': ticker, 'price': None, 'ok': False})

    # ── ETF ──
    cur = db.cursor()
    cur.execute("SELECT id, name, ticker FROM etf WHERE ticker IS NOT NULL AND ticker != ''")
    etf_rows = cur.fetchall()
    cur.close()

    for row in etf_rows:
        eid, name, ticker = row['id'], row['name'], row['ticker']
        price = _fetch_stock_price(ticker)
        if price:
            cur = db.cursor()
            cur.execute("UPDATE etf SET current_price = %s WHERE id = %s", (price, eid))
            cur.close()
            results['etf'].append({'id': eid, 'name': name, 'ticker': ticker, 'price': price, 'ok': True})
        else:
            results['errors'].append(f"ETF [{name}({ticker})]: 가격 조회 실패")
            results['etf'].append({'id': eid, 'name': name, 'ticker': ticker, 'price': None, 'ok': False})

    # ── 코인 ──
    cur = db.cursor()
    cur.execute("SELECT id, name, symbol FROM crypto WHERE symbol IS NOT NULL AND symbol != ''")
    crypto_rows = cur.fetchall()
    cur.close()

    if crypto_rows:
        symbols = [row['symbol'] for row in crypto_rows]
        cg_prices = _fetch_coingecko_prices(symbols)

        for row in crypto_rows:
            cid, name, symbol = row['id'], row['name'], row['symbol']
            price = cg_prices.get(symbol.upper())
            if price:
                cur = db.cursor()
                cur.execute("UPDATE crypto SET current_price = %s WHERE id = %s", (price, cid))
                cur.close()
                results['crypto'].append({'id': cid, 'name': name, 'symbol': symbol, 'price': price, 'ok': True})
            else:
                results['errors'].append(f"코인 [{name}({symbol})]: 가격 조회 실패")
                results['crypto'].append({'id': cid, 'name': name, 'symbol': symbol, 'price': None, 'ok': False})

    db.commit()
    db.close()
    return jsonify(results)


# ── API: 거주지 ──────────────────────────────────────────────
@app.route('/api/residence', methods=['GET', 'POST'])
def api_residence():
    db = get_db()
    if request.method == 'GET':
        cur = db.cursor()
        cur.execute("SELECT * FROM residence ORDER BY id DESC")
        rows = cur.fetchall()
        cur.close()
        db.close()
        return jsonify(rows_to_list(rows))

    data = request.json
    cur = db.cursor()
    cur.execute(
    "INSERT INTO residence (address, deposit, monthly_rent, maintenance, start_date, end_date) VALUES (%s,%s,%s,%s,%s,%s)",
    (data.get('address'), data.get('deposit', 0), data.get('monthly_rent', 0),
    data.get('maintenance', 0), data.get('start_date'), data.get('end_date'))
    )
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/residence/<int:rid>', methods=['PUT', 'DELETE'])
def api_residence_detail(rid):
    db = get_db()
    if request.method == 'PUT':
        data = request.json
        cur = db.cursor()
        cur.execute(
        "UPDATE residence SET address=%s, deposit=%s, monthly_rent=%s, maintenance=%s, start_date=%s, end_date=%s WHERE id=%s",
        (data.get('address'), data.get('deposit', 0), data.get('monthly_rent', 0),
        data.get('maintenance', 0), data.get('start_date'), data.get('end_date'), rid)
        )
        cur.close()
        db.commit()
        db.close()
        return jsonify({'ok': True})
    cur = db.cursor()
    cur.execute("DELETE FROM residence WHERE id = %s", (rid,))
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True})


# ── API: 부동산 ──────────────────────────────────────────────
def _re_enrich(db, rows):
    """real_estate 목록에 현재 계약 정보·비용 집계·실수익률 추가"""
    result = []
    for r in rows:
        rid = r['id']
        # 현재 유효 계약 (end_date 가장 최근)
        cur = db.cursor()
        cur.execute(
        "SELECT * FROM tenant_contracts WHERE real_estate_id=%s ORDER BY end_date DESC LIMIT 1", (rid,)
        )
        contract = cur.fetchone()
        cur.close()
        # 취득비용 합계
        cur = db.cursor()
        cur.execute(
        "SELECT COALESCE(SUM(amount),0) as v FROM property_costs "
        "WHERE real_estate_id=%s AND cost_type='취득비용'", (rid,)
        )
        acq_cost = cur.fetchone()['v']
        cur.close()
        # 순손익에 반영될 비용/수익 합계 (amount: 수익=양수, 비용=음수)
        cur = db.cursor()
        cur.execute(
        "SELECT COALESCE(SUM(CASE WHEN cost_type='임대수익' THEN amount ELSE -amount END),0) as v "
        "FROM property_costs WHERE real_estate_id=%s", (rid,)
        )
        net_extra = cur.fetchone()['v']
        cur.close()

        deposit = contract['deposit'] if contract else 0
        purchase = r['purchase_price']
        current  = r['current_price']
        real_inv = purchase - deposit + acq_cost   # 실투자금
        net_gain = (current - purchase) + net_extra  # 순손익
        real_roi = round(net_gain / real_inv * 100, 1) if real_inv > 0 else None

        row = dict(r)
        row['contract_type']  = contract['contract_type'] if contract else None
        row['deposit']        = deposit
        row['monthly_rent']   = contract['monthly_rent'] if contract else 0
        row['contract_end']   = contract['end_date'] if contract else None
        row['real_inv']       = real_inv
        row['net_gain']       = net_gain
        row['real_roi']       = real_roi
        result.append(row)
    return result


@app.route('/api/real-estate', methods=['GET', 'POST'])
def api_real_estate():
    db = get_db()
    if request.method == 'GET':
        cur = db.cursor()
        cur.execute("SELECT * FROM real_estate ORDER BY name")
        rows = cur.fetchall()
        cur.close()
        result = _re_enrich(db, rows)
        db.close()
        return jsonify(result)

    data = request.json
    cur = db.cursor()
    cur.execute(
    "INSERT INTO real_estate (name, re_type, purchase_date, purchase_price, current_price, memo) VALUES (%s,%s,%s,%s,%s,%s)",
    (data.get('name'), data.get('re_type'), data.get('purchase_date'),
    data.get('purchase_price', 0), data.get('current_price', 0), data.get('memo'))
    )
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/real-estate/<int:rid>', methods=['PUT', 'DELETE'])
def api_real_estate_detail(rid):
    db = get_db()
    if request.method == 'PUT':
        data = request.json
        cur = db.cursor()
        cur.execute(
        "UPDATE real_estate SET name=%s, re_type=%s, purchase_date=%s, purchase_price=%s, current_price=%s, memo=%s WHERE id=%s",
        (data.get('name'), data.get('re_type'), data.get('purchase_date'),
        data.get('purchase_price', 0), data.get('current_price', 0), data.get('memo'), rid)
        )
        cur.close()
        db.commit()
        db.close()
        return jsonify({'ok': True})
    cur = db.cursor()
    cur.execute("DELETE FROM real_estate WHERE id = %s", (rid,))
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True})


@app.route('/api/re-summary')
def api_re_summary():
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM real_estate")
    rows = cur.fetchall()
    cur.close()
    enriched = _re_enrich(db, rows)
    db.close()
    total_purchase = sum(r['purchase_price'] for r in enriched)
    total_deposit  = sum(r['deposit'] for r in enriched)
    total_real_inv = sum(r['real_inv'] for r in enriched)
    total_net_gain = sum(r['net_gain'] for r in enriched)
    avg_roi = round(total_net_gain / total_real_inv * 100, 1) if total_real_inv > 0 else None
    return jsonify({
        'count': len(enriched),
        'total_purchase': total_purchase,
        'total_deposit': total_deposit,
        'total_real_inv': total_real_inv,
        'total_net_gain': total_net_gain,
        'avg_roi': avg_roi,
    })


@app.route('/api/re-expiring')
def api_re_expiring():
    """3개월 이내 만료 계약 목록"""
    db = get_db()
    cur = db.cursor()
    cur.execute("""
    SELECT c.*, r.name as re_name
    FROM tenant_contracts c
    JOIN real_estate r ON c.real_estate_id = r.id
    WHERE c.end_date IS NOT NULL
    AND c.end_date >= CURRENT_DATE
    AND c.end_date <= CURRENT_DATE + INTERVAL '3 months'
    ORDER BY c.end_date
    """)
    rows = cur.fetchall()
    cur.close()
    db.close()
    return jsonify(rows_to_list(rows))


@app.route('/api/tenant-contracts', methods=['GET', 'POST'])
def api_tenant_contracts():
    db = get_db()
    if request.method == 'GET':
        rid = request.args.get('real_estate_id')
        cur = db.cursor()
        cur.execute(
        "SELECT * FROM tenant_contracts WHERE real_estate_id=%s ORDER BY end_date DESC", (rid,)
        )
        rows = cur.fetchall()
        cur.close()
        db.close()
        return jsonify(rows_to_list(rows))
    d = request.json or {}
    cur = db.cursor()
    cur.execute(
    "INSERT INTO tenant_contracts (real_estate_id, contract_type, deposit, monthly_rent, start_date, end_date, memo)"
    " VALUES (%s,%s,%s,%s,%s,%s,%s)",
    (d.get('real_estate_id'), d.get('contract_type'), d.get('deposit', 0),
    d.get('monthly_rent', 0), d.get('start_date'), d.get('end_date'), d.get('memo'))
    )
    cur.close()
    db.commit(); db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/tenant-contracts/<int:rid>', methods=['PUT', 'DELETE'])
def api_tenant_contracts_detail(rid):
    db = get_db()
    if request.method == 'DELETE':
        cur = db.cursor()
        cur.execute("DELETE FROM tenant_contracts WHERE id=%s", (rid,))
        cur.close()
        db.commit(); db.close()
        return jsonify({'ok': True})
    d = request.json or {}
    cur = db.cursor()
    cur.execute(
    "UPDATE tenant_contracts SET contract_type=%s, deposit=%s, monthly_rent=%s, start_date=%s, end_date=%s, memo=%s WHERE id=%s",
    (d.get('contract_type'), d.get('deposit', 0), d.get('monthly_rent', 0),
    d.get('start_date'), d.get('end_date'), d.get('memo'), rid)
    )
    cur.close()
    db.commit(); db.close()
    return jsonify({'ok': True})


@app.route('/api/property-costs', methods=['GET', 'POST'])
def api_property_costs():
    db = get_db()
    if request.method == 'GET':
        rid = request.args.get('real_estate_id')
        cur = db.cursor()
        cur.execute(
        "SELECT * FROM property_costs WHERE real_estate_id=%s ORDER BY date DESC", (rid,)
        )
        rows = cur.fetchall()
        cur.close()
        db.close()
        return jsonify(rows_to_list(rows))
    d = request.json or {}
    cur = db.cursor()
    cur.execute(
    "INSERT INTO property_costs (real_estate_id, cost_type, name, amount, date, memo) VALUES (%s,%s,%s,%s,%s,%s)",
    (d.get('real_estate_id'), d.get('cost_type'), d.get('name'),
    d.get('amount', 0), d.get('date'), d.get('memo'))
    )
    cur.close()
    db.commit(); db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/property-costs/<int:rid>', methods=['PUT', 'DELETE'])
def api_property_costs_detail(rid):
    db = get_db()
    if request.method == 'DELETE':
        cur = db.cursor()
        cur.execute("DELETE FROM property_costs WHERE id=%s", (rid,))
        cur.close()
        db.commit(); db.close()
        return jsonify({'ok': True})
    d = request.json or {}
    cur = db.cursor()
    cur.execute(
    "UPDATE property_costs SET cost_type=%s, name=%s, amount=%s, date=%s, memo=%s WHERE id=%s",
    (d.get('cost_type'), d.get('name'), d.get('amount', 0),
    d.get('date'), d.get('memo'), rid)
    )
    cur.close()
    db.commit(); db.close()
    return jsonify({'ok': True})


# ── API: 대출 ────────────────────────────────────────────────
@app.route('/api/loans', methods=['GET', 'POST'])
def api_loans():
    db = get_db()
    if request.method == 'GET':
        cur = db.cursor()
        cur.execute("SELECT * FROM loans ORDER BY name")
        rows = cur.fetchall()
        cur.close()
        db.close()
        return jsonify(rows_to_list(rows))

    data = request.json
    cur = db.cursor()
    cur.execute(
    "INSERT INTO loans (name, institution, principal, remaining, monthly_payment, interest_rate, loan_date, end_date, memo) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
    (data.get('name'), data.get('institution'), data.get('principal', 0),
    data.get('remaining', 0), data.get('monthly_payment', 0),
    data.get('interest_rate', 0), data.get('loan_date'), data.get('end_date'), data.get('memo'))
    )
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/loans/<int:rid>', methods=['PUT', 'DELETE'])
def api_loans_detail(rid):
    db = get_db()
    if request.method == 'PUT':
        data = request.json
        cur = db.cursor()
        cur.execute(
        "UPDATE loans SET name=%s, institution=%s, principal=%s, remaining=%s, monthly_payment=%s, interest_rate=%s, loan_date=%s, end_date=%s, memo=%s WHERE id=%s",
        (data.get('name'), data.get('institution'), data.get('principal', 0),
        data.get('remaining', 0), data.get('monthly_payment', 0),
        data.get('interest_rate', 0), data.get('loan_date'), data.get('end_date'), data.get('memo'), rid)
        )
        cur.close()
        db.commit()
        db.close()
        return jsonify({'ok': True})
    cur = db.cursor()
    cur.execute("DELETE FROM loans WHERE id = %s", (rid,))
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True})


# ── API: 연금 ────────────────────────────────────────────────
@app.route('/api/pension', methods=['GET', 'POST'])
def api_pension():
    db = get_db()
    if request.method == 'GET':
        cur = db.cursor()
        cur.execute("SELECT * FROM pension ORDER BY pension_type, name")
        rows = cur.fetchall()
        cur.close()
        db.close()
        return jsonify(rows_to_list(rows))

    data = request.json
    cur = db.cursor()
    cur.execute(
    "INSERT INTO pension (pension_type, name, institution, monthly_payment, accumulated, return_rate, memo) VALUES (%s,%s,%s,%s,%s,%s,%s)",
    (data.get('pension_type'), data.get('name'), data.get('institution'),
    data.get('monthly_payment', 0), data.get('accumulated', 0),
    data.get('return_rate', 0), data.get('memo'))
    )
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/pension/<int:rid>', methods=['PUT', 'DELETE'])
def api_pension_detail(rid):
    db = get_db()
    if request.method == 'PUT':
        data = request.json
        cur = db.cursor()
        cur.execute(
        "UPDATE pension SET pension_type=%s, name=%s, institution=%s, monthly_payment=%s, accumulated=%s, return_rate=%s, memo=%s WHERE id=%s",
        (data.get('pension_type'), data.get('name'), data.get('institution'),
        data.get('monthly_payment', 0), data.get('accumulated', 0),
        data.get('return_rate', 0), data.get('memo'), rid)
        )
        cur.close()
        db.commit()
        db.close()
        return jsonify({'ok': True})
    cur = db.cursor()
    cur.execute("DELETE FROM pension WHERE id = %s", (rid,))
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True})


# ── API: 목표저축 ────────────────────────────────────────────
@app.route('/api/goals', methods=['GET', 'POST'])
def api_goals():
    db = get_db()
    if request.method == 'GET':
        cur = db.cursor()
        cur.execute("SELECT * FROM goals ORDER BY target_date")
        rows = cur.fetchall()
        cur.close()
        db.close()
        return jsonify(rows_to_list(rows))

    data = request.json
    cur = db.cursor()
    cur.execute(
    "INSERT INTO goals (name, target_amount, current_amount, monthly_saving, target_date, memo) VALUES (%s,%s,%s,%s,%s,%s)",
    (data.get('name'), data.get('target_amount', 0), data.get('current_amount', 0),
    data.get('monthly_saving', 0), data.get('target_date'), data.get('memo'))
    )
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/goals/<int:rid>', methods=['PUT', 'DELETE'])
def api_goals_detail(rid):
    db = get_db()
    if request.method == 'PUT':
        data = request.json
        cur = db.cursor()
        cur.execute(
        "UPDATE goals SET name=%s, target_amount=%s, current_amount=%s, monthly_saving=%s, target_date=%s, memo=%s WHERE id=%s",
        (data.get('name'), data.get('target_amount', 0), data.get('current_amount', 0),
        data.get('monthly_saving', 0), data.get('target_date'), data.get('memo'), rid)
        )
        cur.close()
        db.commit()
        db.close()
        return jsonify({'ok': True})
    cur = db.cursor()
    cur.execute("DELETE FROM goals WHERE id = %s", (rid,))
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True})


# ── API: 현금/예금 ───────────────────────────────────────────
@app.route('/api/cash-deposits', methods=['GET', 'POST'])
def api_cash_deposits():
    db = get_db()
    if request.method == 'GET':
        cur = db.cursor()
        cur.execute("SELECT * FROM cash_deposits ORDER BY name")
        rows = cur.fetchall()
        cur.close()
        db.close()
        return jsonify(rows_to_list(rows))

    data = request.json
    today = date.today().isoformat()
    cur = db.cursor()
    cur.execute(
    "INSERT INTO cash_deposits (name, amount, memo, updated_date) VALUES (%s,%s,%s,%s)",
    (data.get('name'), data.get('amount', 0), data.get('memo'), today)
    )
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/cash-deposits/<int:rid>', methods=['PUT', 'DELETE'])
def api_cash_deposits_detail(rid):
    db = get_db()
    if request.method == 'PUT':
        data = request.json
        today = date.today().isoformat()
        cur = db.cursor()
        cur.execute(
        "UPDATE cash_deposits SET name=%s, amount=%s, memo=%s, updated_date=%s WHERE id=%s",
        (data.get('name'), data.get('amount', 0), data.get('memo'), today, rid)
        )
        cur.close()
        db.commit()
        db.close()
        return jsonify({'ok': True})
    cur = db.cursor()
    cur.execute("DELETE FROM cash_deposits WHERE id = %s", (rid,))
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True})

# ── API: 대시보드 집계 ───────────────────────────────────────
@app.route('/api/dashboard')
def api_dashboard():
    db = get_db()
    today = date.today()
    year  = request.args.get('year',  today.strftime('%Y'))
    month = request.args.get('month', today.strftime('%m'))
    ym    = f"{year}-{month.zfill(2)}"

    # 소득 현황 (오늘 이후 날짜의 반복 수입 등은 제외)
    # 근로소득: 급여, 사업소득
    cur = db.cursor()
    cur.execute(
    "SELECT COALESCE(SUM(amount),0) FROM income "
    "WHERE to_char(date::date, 'YYYY-MM') = %s AND category IN ('급여', '사업소득') AND date <= CURRENT_DATE",
    (ym,)
    )
    labor_inc = cur.fetchone()[0]
    cur.close()

    # 자생소득: 그 외 모든 수입
    cur = db.cursor()
    cur.execute(
    "SELECT COALESCE(SUM(amount),0) FROM income "
    "WHERE to_char(date::date, 'YYYY-MM') = %s AND category NOT IN ('급여', '사업소득') AND date <= CURRENT_DATE",
    (ym,)
    )
    passive_inc = cur.fetchone()[0]
    cur.close()

    # 이번달 수입 합계
    cur = db.cursor()
    cur.execute(
    "SELECT COALESCE(SUM(amount),0) as total FROM income WHERE to_char(date::date, 'YYYY-MM') = %s AND date <= CURRENT_DATE", (ym,)
    )
    income_total = cur.fetchone()['total']
    cur.close()

    # 이번달 지출 합계
    cur = db.cursor()
    cur.execute(
    "SELECT COALESCE(SUM(amount),0) as total FROM budget WHERE to_char(date::date, 'YYYY-MM') = %s AND date <= CURRENT_DATE", (ym,)
    )
    expense_total = cur.fetchone()['total']
    cur.close()

    # 이번달 카드 지출
    cur = db.cursor()
    cur.execute(
    "SELECT COALESCE(SUM(amount),0) as total FROM card_tx WHERE to_char(date::date, 'YYYY-MM') = %s AND date <= CURRENT_DATE", (ym,)
    )
    card_total = cur.fetchone()['total']
    cur.close()

    # 주식 평가액 (stock_tx 기반)
    cur = db.cursor()
    cur.execute("""
    SELECT COALESCE(SUM(s.current_price * (
    SELECT COALESCE(SUM(CASE WHEN tx_type='buy' THEN quantity ELSE -quantity END), 0)
    FROM stock_tx WHERE stock_id = s.id
    )), 0) AS val FROM stocks s
    """)
    stocks_val = cur.fetchone()['val']
    cur.close()

    # ETF 평가액
    cur = db.cursor()
    cur.execute(
    "SELECT COALESCE(SUM(current_price * quantity),0) as val FROM etf"
    )
    etf_val = cur.fetchone()['val']
    cur.close()

    # 코인 평가액
    cur = db.cursor()
    cur.execute(
    "SELECT COALESCE(SUM(current_price * quantity),0) as val FROM crypto"
    )
    crypto_val = cur.fetchone()['val']
    cur.close()

    # 부동산 현재가 (시세 - 임대보증금 + 거주보증금)
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(current_price),0) FROM real_estate")
    re_total_price = cur.fetchone()[0]
    cur.close()
    cur = db.cursor()
    cur.execute("""
    SELECT COALESCE(SUM(deposit), 0) FROM tenant_contracts 
    WHERE id IN (SELECT MAX(id) FROM tenant_contracts GROUP BY real_estate_id)
    """)
    re_total_deposit = cur.fetchone()[0]
    cur.close()
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(deposit), 0) FROM residence")
    residence_deposit = cur.fetchone()[0]
    cur.close()
    re_val = re_total_price - re_total_deposit + residence_deposit

    # 연금 누적액
    cur = db.cursor()
    cur.execute(
    "SELECT COALESCE(SUM(accumulated),0) as val FROM pension"
    )
    pension_val = cur.fetchone()['val']
    cur.close()

    # 현금/예금
    cur = db.cursor()
    cur.execute(
    "SELECT COALESCE(SUM(amount),0) as val FROM cash_deposits"
    )
    cash_val = cur.fetchone()['val']
    cur.close()

    # 대출 잔액
    cur = db.cursor()
    cur.execute(
    "SELECT COALESCE(SUM(remaining),0) as total FROM loans"
    )
    loan_total = cur.fetchone()['total']
    cur.close()

    total_assets = stocks_val + etf_val + crypto_val + re_val + pension_val + cash_val
    net_worth = total_assets - loan_total

    # 이번달 수입 카테고리별
    cur = db.cursor()
    cur.execute(
    "SELECT category, SUM(amount) as total FROM income WHERE to_char(date::date, 'YYYY-MM') = %s GROUP BY category",
    (ym,)
    )
    income_by_cat = cur.fetchall()
    cur.close()

    # 이번달 지출 카테고리별
    cur = db.cursor()
    cur.execute(
    "SELECT category, SUM(amount) as total FROM budget WHERE to_char(date::date, 'YYYY-MM') = %s GROUP BY category",
    (ym,)
    )
    expense_by_cat = cur.fetchall()
    cur.close()

    # 대출 목록
    cur = db.cursor()
    cur.execute(
    "SELECT name, remaining FROM loans ORDER BY remaining DESC"
    )
    loans_list = cur.fetchall()
    cur.close()

    # 목표저축 목록
    cur = db.cursor()
    cur.execute(
    "SELECT name, target_amount, current_amount FROM goals ORDER BY target_date"
    )
    goals_list = cur.fetchall()
    cur.close()

    # 투자 수익률
    cur = db.cursor()
    cur.execute(
    "SELECT COALESCE(SUM(price * quantity + fee),0) AS c FROM stock_tx WHERE tx_type='buy'"
    )
    stocks_cost = cur.fetchone()['c']
    cur.close()
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(buy_price * quantity),0) as c FROM etf")
    etf_cost = cur.fetchone()['c']
    cur.close()
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(buy_price * quantity),0) as c FROM crypto")
    crypto_cost = cur.fetchone()['c']
    cur.close()

    db.close()

    return jsonify({
        'income_total':    income_total,
        'expense_total':   expense_total + card_total,
        'net_worth':       net_worth,
        'total_assets':    total_assets,
        'loan_total':      loan_total,
        'asset_breakdown': {
            'stocks':  stocks_val,
            'etf':     etf_val,
            'crypto':  crypto_val,
            'realestate': re_val,
            'pension': pension_val,
            'cash':    cash_val,
        },
        'income_by_cat':  rows_to_list(income_by_cat),
        'expense_by_cat': rows_to_list(expense_by_cat),
        'loans':          rows_to_list(loans_list),
        'goals':          rows_to_list(goals_list),
        'investment_returns': {
            'stocks':  {'cost': stocks_cost, 'value': stocks_val},
            'etf':     {'cost': etf_cost,    'value': etf_val},
            'crypto':  {'cost': crypto_cost, 'value': crypto_val},
        },
    })


@app.route('/api/tech-tree-data')
def api_tech_tree_data():
    db = get_db()
    # 자산 현황
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(s.current_price * (SELECT COALESCE(SUM(CASE WHEN tx_type='buy' THEN quantity ELSE -quantity END), 0) FROM stock_tx WHERE stock_id = s.id)), 0) FROM stocks s")
    stocks_val = cur.fetchone()[0]
    cur.close()
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(current_price * quantity),0) FROM etf")
    etf_val = cur.fetchone()[0]
    cur.close()
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(current_price * quantity),0) FROM crypto")
    crypto_val = cur.fetchone()[0]
    cur.close()
    # 부동산 가치 계산 (현재 시세 총합 - 임대 보증금 총합)
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(current_price),0) FROM real_estate")
    re_total_price = cur.fetchone()[0]
    cur.close()
    # 각 부동산별 가장 최근 계약의 보증금 합계
    cur = db.cursor()
    cur.execute("""
    SELECT COALESCE(SUM(deposit), 0) FROM tenant_contracts 
    WHERE id IN (SELECT MAX(id) FROM tenant_contracts GROUP BY real_estate_id)
    """)
    re_total_deposit = cur.fetchone()[0]
    cur.close()
    
    # 거주지 보증금 (본인이 돌려받을 돈이므로 자산에 포함)
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(deposit), 0) FROM residence")
    residence_deposit = cur.fetchone()[0]
    cur.close()
    
    re_val = re_total_price - re_total_deposit + residence_deposit
    
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(amount),0) FROM cash_deposits")
    cash_val = cur.fetchone()[0]
    cur.close()
    # 목표저축 누계액 포함 (총 목표 설정용 제외)
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(current_amount), 0) FROM goals WHERE name != '자본주의테크트리'")
    goal_savings = cur.fetchone()[0]
    cur.close()
    cash_val += goal_savings
    
    # 연금 자산 추가
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(accumulated),0) FROM pension")
    pension_val = cur.fetchone()[0]
    cur.close()
    
    # 소득 현황 (이번달 기준, 오늘 이후 날짜의 반복 수입 등은 제외)
    today = date.today()
    ym = today.strftime('%Y-%m')
    # 근로소득: 급여, 사업소득(자영업) - 수입관리 데이터에서 직접 집계
    cur = db.cursor()
    cur.execute(
    "SELECT COALESCE(SUM(amount),0) FROM income "
    "WHERE to_char(date::date, 'YYYY-MM') = %s AND category IN ('급여', '사업소득') AND date <= CURRENT_DATE", 
    (ym,)
    )
    labor_inc = cur.fetchone()[0]
    cur.close()
    
    # 자생소득: 그 외 모든 수입
    cur = db.cursor()
    cur.execute(
    "SELECT COALESCE(SUM(amount),0) FROM income "
    "WHERE to_char(date::date, 'YYYY-MM') = %s AND category NOT IN ('급여', '사업소득') AND date <= CURRENT_DATE", 
    (ym,)
    )
    passive_inc = cur.fetchone()[0]
    cur.close()

    # 부동산 월세(임대료) 자동 합산
    cur = db.cursor()
    cur.execute("""
    SELECT COALESCE(SUM(monthly_rent), 0) 
    FROM tenant_contracts 
    WHERE contract_type = '월세' 
    AND id IN (SELECT MAX(id) FROM tenant_contracts GROUP BY real_estate_id)
    """)
    rental_inc = cur.fetchone()[0]
    cur.close()
    
    # 전세 보증금 사적 레버리지 수익 계산 (보증금 * 4% / 12개월)
    cur = db.cursor()
    cur.execute("""
    SELECT COALESCE(SUM(deposit * 0.04 / 12), 0)
    FROM tenant_contracts 
    WHERE contract_type = '전세' 
    AND id IN (SELECT MAX(id) FROM tenant_contracts GROUP BY real_estate_id)
    """)
    leverage_inc = cur.fetchone()[0]
    cur.close()
    
    passive_inc += (rental_inc + leverage_inc)

    # 고정비(빨대) 합계 계산 (최근 3개월 내 2회 이상 발생한 동일 이름/금액 지출)
    cur = db.cursor()
    cur.execute("""
    SELECT name, amount, COUNT(*) as cnt, SUM(amount) as total
    FROM budget 
    WHERE date >= CURRENT_DATE - INTERVAL '3 months'
    GROUP BY name, amount
    HAVING COUNT(*) >= 2
    ORDER BY total DESC
    """)
    straws = cur.fetchall()
    cur.close()
    straw_total = sum(r['total'] / r['cnt'] for r in straws) # 월평균 고정비

    # 이번달 지출 합계 (가계부 + 카드 + 대출 상환액)
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(amount),0) FROM budget WHERE to_char(date::date, 'YYYY-MM') = %s", (ym,))
    expense_total = cur.fetchone()[0]
    cur.close()
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(amount),0) FROM card_tx WHERE to_char(date::date, 'YYYY-MM') = %s", (ym,))
    card_total = cur.fetchone()[0]
    cur.close()
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(monthly_payment), 0) FROM loans")
    loan_repayment = cur.fetchone()[0]
    cur.close()
    total_exp = expense_total + card_total + loan_repayment

    # [신규] 월간 변동성 계산 (이번달 순유입액 기준)
    # 실제 과거 스냅샷이 없으므로, 이번달 발생한 현금흐름과 투자내역을 바탕으로 추정치 산출
    monthly_stats = {
        'cash': {'change': (labor_inc + passive_inc) - total_exp, 'percent': 0},
        'stocks': {'change': 0, 'percent': 0},
        'real_estate': {'change': 0, 'percent': 0},
        'crypto': {'change': 0, 'percent': 0}
    }
    # 주식/코인 이번달 매수액 집계
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(price*quantity),0) FROM stock_tx WHERE to_char(tx_date::date, 'YYYY-MM') = %s AND tx_type='buy'", (ym,))
    s_buy = cur.fetchone()[0]
    cur.close()
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(price*quantity),0) FROM stock_tx WHERE to_char(tx_date::date, 'YYYY-MM') = %s AND tx_type='sell'", (ym,))
    s_sell = cur.fetchone()[0]
    cur.close()
    monthly_stats['stocks']['change'] = s_buy - s_sell
    
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(buy_price*quantity),0) FROM crypto WHERE to_char(buy_date::date, 'YYYY-MM') = %s", (ym,))
    c_buy = cur.fetchone()[0]
    cur.close()
    monthly_stats['crypto']['change'] = c_buy

    # 변동률 계산 (현재값 대비)
    def calc_pct(val, change):
        prev = val - change
        return round((change / prev * 100), 1) if prev > 0 else 0
    
    monthly_stats['cash']['percent'] = calc_pct(cash_val, monthly_stats['cash']['change'])
    monthly_stats['stocks']['percent'] = calc_pct(stocks_val + etf_val, monthly_stats['stocks']['change'])
    monthly_stats['crypto']['percent'] = calc_pct(crypto_val, monthly_stats['crypto']['change'])

    # 목표 자산
    cur = db.cursor()
    cur.execute("SELECT target_amount FROM goals WHERE name = '자본주의테크트리'")
    goal = cur.fetchone()
    cur.close()
    target_amount = goal[0] if goal else 1000000000 # 기본 10억

    # [신규] 월별 자산 스냅샷 자동 저장/업데이트
    cur = db.cursor()
    cur.execute("""
    INSERT INTO asset_snapshots (month, cash, stocks, real_estate, crypto, pension, total, updated_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
    ON CONFLICT(month) DO UPDATE SET
    cash=excluded.cash, stocks=excluded.stocks, real_estate=excluded.real_estate,
    crypto=excluded.crypto, pension=excluded.pension, total=excluded.total,
    updated_at=excluded.updated_at
    """, (ym, cash_val, stocks_val + etf_val, re_val, crypto_val, pension_val, 
    cash_val + stocks_val + etf_val + re_val + crypto_val + pension_val))
    cur.close()
    db.commit()

    db.close()
    return jsonify({
        'assets': {
            'cash': int(cash_val or 0),
            'stocks': int(stocks_val or 0) + int(etf_val or 0),
            'real_estate': int(re_val or 0),
            'crypto': int(crypto_val or 0),
            'pension': int(pension_val or 0)
        },
        'income': {
            'labor': int(labor_inc or 0),
            'passive': int(passive_inc or 0)
        },
        'expense': int(total_exp or 0),
        'straw_total': int(straw_total or 0),
        'target_amount': int(target_amount or 0),
        'monthly_stats': {
            k: {
                'change': int(v['change'] or 0),
                'percent': v['percent']
            } for k, v in monthly_stats.items()
        }
    })

@app.route('/api/straws')
def api_straws():
    """지출 중 매달 반복되는 '빨대'(고정비) 목록을 찾아 반환"""
    db = get_db()
    cur = db.cursor()
    cur.execute("""
    SELECT name, amount, category, COUNT(*) as cnt, MAX(date) as last_date
    FROM budget 
    GROUP BY name, amount
    HAVING cnt >= 2
    ORDER BY amount DESC
    """)
    rows = cur.fetchall()
    cur.close()
    db.close()
    return jsonify(rows_to_list(rows))

@app.route('/api/tech-tree-goal', methods=['POST'])
def api_tech_tree_goal():
    db = get_db()
    data = request.json
    target = data.get('target_amount', 1000000000)
    
    cur = db.cursor()
    cur.execute("SELECT id FROM goals WHERE name = '자본주의테크트리'")
    exists = cur.fetchone()
    cur.close()
    if exists:
        cur = db.cursor()
        cur.execute("UPDATE goals SET target_amount = %s WHERE name = '자본주의테크트리'", (target,))
        cur.close()
    else:
        cur = db.cursor()
        cur.execute("INSERT INTO goals (name, target_amount) VALUES ('자본주의테크트리', %s)", (target,))
        cur.close()
    
    db.commit()
    db.close()
    return jsonify({'ok': True})

# ── API: 자산별 히스토리 (최근 12개월) ──────────────────────────
@app.route('/api/asset-history')
def api_asset_history():
    db = get_db()
    today = date.today()
    history = []
    
    # 1. DB에 저장된 스냅샷 불러오기
    cur = db.cursor()
    cur.execute("SELECT * FROM asset_snapshots ORDER BY month DESC")
    snapshots = {r['month']: r for r in cur.fetchall()}
    cur.close()

    # 현재 실시간 자산 상태 (역산용 기준점)
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(amount),0) FROM cash_deposits")
    curr_cash = cur.fetchone()[0]
    cur.close()
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(current_amount), 0) FROM goals WHERE name != '자본주의테크트리'")
    curr_cash += cur.fetchone()[0]
    cur.close()
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(accumulated),0) FROM pension")
    curr_pension = cur.fetchone()[0]
    cur.close()
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(monthly_payment),0) FROM pension")
    p_monthly = cur.fetchone()[0]
    cur.close()
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(s.current_price * (SELECT COALESCE(SUM(CASE WHEN tx_type='buy' THEN quantity ELSE -quantity END), 0) FROM stock_tx WHERE stock_id = s.id)), 0) FROM stocks s")
    curr_stocks = cur.fetchone()[0]
    cur.close()
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(current_price * quantity),0) FROM etf")
    curr_stocks += cur.fetchone()[0]
    cur.close()
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(current_price * quantity),0) FROM crypto")
    curr_crypto = cur.fetchone()[0]
    cur.close()
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(current_price),0) FROM real_estate")
    re_price = cur.fetchone()[0]
    cur.close()
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(deposit), 0) FROM tenant_contracts WHERE id IN (SELECT MAX(id) FROM tenant_contracts GROUP BY real_estate_id)")
    re_dep = cur.fetchone()[0]
    cur.close()
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(deposit), 0) FROM residence")
    res_dep = cur.fetchone()[0]
    cur.close()
    curr_re = re_price - re_dep + res_dep

    # 거꾸로 12개월치 데이터 생성
    y, m = today.year, today.month
    for i in range(12):
        ym = f"{y}-{m:02d}"
        
        # 스냅샷이 있으면 스냅샷 데이터 사용, 없으면 역산 데이터 사용
        if ym in snapshots:
            s = snapshots[ym]
            history.append({
                'month': ym,
                'cash': s['cash'],
                'stocks': s['stocks'],
                'real_estate': s['real_estate'],
                'crypto': s['crypto'],
                'pension': s['pension']
            })
            # 역산 기준점도 해당 스냅샷으로 업데이트 (더 정확한 과거 추정을 위해)
            curr_cash, curr_stocks, curr_re, curr_crypto, curr_pension = s['cash'], s['stocks'], s['real_estate'], s['crypto'], s['pension']
        else:
            history.append({
                'month': ym,
                'cash': curr_cash,
                'stocks': curr_stocks,
                'real_estate': curr_re,
                'crypto': curr_crypto,
                'pension': curr_pension
            })
        
        # 이전 달로 되돌리기 위한 변동분 집계 (역산)
        cur = db.cursor()
        cur.execute("SELECT COALESCE(SUM(amount),0) FROM income WHERE to_char(date::date, 'YYYY-MM') = %s", (ym,))
        inc = cur.fetchone()[0]
        cur.close()
        cur = db.cursor()
        cur.execute("SELECT COALESCE(SUM(amount),0) FROM budget WHERE to_char(date::date, 'YYYY-MM') = %s", (ym,))
        exp = cur.fetchone()[0]
        cur.close()
        cur = db.cursor()
        cur.execute("SELECT COALESCE(SUM(amount),0) FROM card_tx WHERE to_char(date::date, 'YYYY-MM') = %s", (ym,))
        card = cur.fetchone()[0]
        cur.close()
        cur = db.cursor()
        cur.execute("SELECT COALESCE(SUM(price*quantity),0) FROM stock_tx WHERE to_char(tx_date::date, 'YYYY-MM') = %s AND tx_type='buy'", (ym,))
        s_buy = cur.fetchone()[0]
        cur.close()
        cur = db.cursor()
        cur.execute("SELECT COALESCE(SUM(price*quantity),0) FROM stock_tx WHERE to_char(tx_date::date, 'YYYY-MM') = %s AND tx_type='sell'", (ym,))
        s_sell = cur.fetchone()[0]
        cur.close()
        cur = db.cursor()
        cur.execute("SELECT COALESCE(SUM(buy_price*quantity),0) FROM crypto WHERE to_char(buy_date::date, 'YYYY-MM') = %s", (ym,))
        c_buy = cur.fetchone()[0]
        cur.close()
        
        curr_cash -= (inc - (exp + card) - (s_buy + c_buy) + s_sell)
        curr_stocks -= (s_buy - s_sell)
        curr_crypto -= c_buy
        curr_pension -= p_monthly
        
        m -= 1
        if m == 0: m = 12; y -= 1

    db.close()
    return jsonify(history[::-1])

# ── API: 자산별 상세 내역 조회 ──────────────────────────
@app.route('/api/tech-tree-detail')
def api_tech_tree_detail():
    db = get_db()
    ttype = request.args.get('type')
    ym = date.today().strftime('%Y-%m')
    
    res = []
    if ttype == 'labor':
        cur = db.cursor()
        cur.execute("SELECT date, name, amount, category FROM income WHERE to_char(date::date, 'YYYY-MM') = %s AND category IN ('급여', '사업소득') AND date <= CURRENT_DATE", (ym,))
        rows = cur.fetchall()
        cur.close()
        res = [{'date': r[0], 'name': r[1], 'amount': r[2], 'memo': r[3]} for r in rows]
    elif ttype == 'passive':
        cur = db.cursor()
        cur.execute("SELECT date, name, amount, category FROM income WHERE to_char(date::date, 'YYYY-MM') = %s AND category NOT IN ('급여', '사업소득') AND date <= CURRENT_DATE", (ym,))
        rows = cur.fetchall()
        cur.close()
        res = [{'date': r[0], 'name': r[1], 'amount': r[2], 'memo': r[3]} for r in rows]
        # 부동산 월세 수입 추가
        cur = db.cursor()
        cur.execute("""
        SELECT r.name, tc.monthly_rent 
        FROM tenant_contracts tc
        JOIN real_estate r ON tc.real_estate_id = r.id
        WHERE tc.contract_type = '월세' 
        AND tc.id IN (SELECT MAX(id) FROM tenant_contracts GROUP BY real_estate_id)
        """)
        rentals = cur.fetchall()
        cur.close()
        for rent in rentals:
            if rent[1] > 0:
                res.append({'date': '임대료', 'name': rent[0], 'amount': rent[1], 'memo': '부동산 월세'})
        
        # 전세 사적 레버리지 추가
        cur = db.cursor()
        cur.execute("""
        SELECT r.name, tc.deposit * 0.04 / 12 as amount
        FROM tenant_contracts tc
        JOIN real_estate r ON tc.real_estate_id = r.id
        WHERE tc.contract_type = '전세' 
        AND tc.id IN (SELECT MAX(id) FROM tenant_contracts GROUP BY real_estate_id)
        """)
        leverages = cur.fetchall()
        cur.close()
        for lev in leverages:
            if lev[1] > 0:
                res.append({'date': '레버리지', 'name': f"{lev[0]} (사적레버리지)", 'amount': int(lev[1]), 'memo': '전세금 기회비용(4%)'})
    elif ttype == 'expense':
        cur = db.cursor()
        cur.execute("SELECT date, name, amount, category FROM budget WHERE to_char(date::date, 'YYYY-MM') = %s", (ym,))
        b = cur.fetchall()
        cur.close()
        cur = db.cursor()
        cur.execute("SELECT date, name, amount, category FROM card_tx WHERE to_char(date::date, 'YYYY-MM') = %s", (ym,))
        c = cur.fetchall()
        cur.close()
        cur = db.cursor()
        cur.execute("SELECT '매월' as date, name, monthly_payment as amount, institution as category FROM loans")
        l = cur.fetchall()
        cur.close()
        res = [{'date': r[0], 'name': r[1], 'amount': r[2], 'memo': r[3]} for r in b + c + l]
    elif ttype == 'cash':
        cur = db.cursor()
        cur.execute("SELECT '현금' as date, name, amount, memo FROM cash_deposits")
        c = cur.fetchall()
        cur.close()
        cur = db.cursor()
        cur.execute("SELECT '목표' as date, name, current_amount as amount, memo FROM goals WHERE name != '자본주의테크트리'")
        g = cur.fetchall()
        cur.close()
        res = [{'date': r[0], 'name': r[1], 'amount': r[2], 'memo': r[3]} for r in c + g]
    elif ttype == 'stocks':
        cur = db.cursor()
        cur.execute("SELECT '주식' as date, name, (SELECT COALESCE(SUM(CASE WHEN tx_type='buy' THEN quantity ELSE -quantity END), 0) FROM stock_tx WHERE stock_id = s.id) * current_price as amount, ticker as memo FROM stocks s")
        s = cur.fetchall()
        cur.close()
        cur = db.cursor()
        cur.execute("SELECT 'ETF' as date, name, quantity * current_price as amount, ticker as memo FROM etf")
        e = cur.fetchall()
        cur.close()
        res = [{'date': r[0], 'name': r[1], 'amount': r[2], 'memo': r[3]} for r in s + e if r[2] > 0]
    elif ttype == 'real_estate':
        # 각 매물별 시세 - 최신 보증금(부채) 계산
        cur = db.cursor()
        cur.execute("""
        SELECT r.name, r.current_price, 
        COALESCE((SELECT deposit FROM tenant_contracts WHERE real_estate_id = r.id ORDER BY id DESC LIMIT 1), 0) as tenant_dep,
        r.memo
        FROM real_estate r
        """)
        rows = cur.fetchall()
        cur.close()
        res = [{'date': '부동산', 'name': r[0], 'amount': r[1] - r[2], 'memo': f"시세:{r[1]:,} / 보증금:-{r[2]:,}"} for r in rows]
        # 거주 보증금 추가 (내가 낸 돈이므로 자산)
        cur = db.cursor()
        cur.execute("SELECT address, deposit FROM residence")
        res_dep = cur.fetchall()
        cur.close()
        for rd in res_dep:
            res.append({'date': '거주보증금', 'name': rd[0], 'amount': rd[1], 'memo': '내가 낸 보증금'})
    elif ttype == 'crypto':
        cur = db.cursor()
        cur.execute("SELECT '코인' as date, name, quantity * current_price as amount, symbol as memo FROM crypto")
        rows = cur.fetchall()
        cur.close()
        res = [{'date': r[0], 'name': r[1], 'amount': r[2], 'memo': r[3]} for r in rows]
    elif ttype == 'pension':
        cur = db.cursor()
        cur.execute("SELECT pension_type as date, name, accumulated as amount, institution as memo FROM pension")
        rows = cur.fetchall()
        cur.close()
        res = [{'date': r[0], 'name': r[1], 'amount': r[2], 'memo': r[3]} for r in rows]

    db.close()
    return jsonify(res)


# ── API: 월별 결산 ───────────────────────────────────────────
@app.route('/api/monthly-summary')
def api_monthly_summary():
    db = get_db()
    year = request.args.get('year', date.today().strftime('%Y'))

    months = []
    for m in range(1, 13):
        ym = f"{year}-{m:02d}"
        # 미래 날짜의 수입(반복 수입 사전 등록분)은 해당 날짜가 돼야만 집계
        cur = db.cursor()
        cur.execute(
        "SELECT COALESCE(SUM(amount),0) as t FROM income"
        " WHERE to_char(date::date, 'YYYY-MM') = %s AND date <= CURRENT_DATE", (ym,)
        )
        inc = cur.fetchone()['t']
        cur.close()
        cur = db.cursor()
        cur.execute(
        "SELECT COALESCE(SUM(amount),0) as t FROM budget WHERE to_char(date::date, 'YYYY-MM') = %s", (ym,)
        )
        exp = cur.fetchone()['t']
        cur.close()
        cur = db.cursor()
        cur.execute(
        "SELECT COALESCE(SUM(amount),0) as t FROM card_tx WHERE to_char(date::date, 'YYYY-MM') = %s", (ym,)
        )
        card = cur.fetchone()['t']
        cur.close()
        months.append({
            'month':   ym,
            'income':  inc,
            'expense': exp + card,
            'saving':  inc - (exp + card),
        })

    db.close()
    return jsonify(months)


# ── 카드 엑셀 가져오기 ───────────────────────────────────────
_HINTS = {
    'date':        ['이용일', '이용일시', '거래일', '거래일자', '이용일자', '날짜', '결제일', '승인일', '사용일', '거래 일시'],
    'name':        ['이용가맹점', '가맹점명', '상호명', '가맹점', '이용처', '거래처', '내용', '적요', '사용처', '거래내용'],
    'amount':      ['이용금액', '결제금액', '거래금액', '금액', '승인금액', '사용금액', '국내이용금액'],
    'installment': ['할부', '할부개월', '할부개월수', '분할', '할부기간'],
    'category':    ['업종', '카테고리', '이용구분', '업종명', '분류'],
}

def _detect_header(rows):
    all_hints = [h for hs in _HINTS.values() for h in hs]
    best, idx = 0, 0
    for i, row in enumerate(rows[:15]):
        score = sum(1 for c in row if any(h in str(c) for h in all_hints))
        if score > best:
            best, idx = score, i
    return idx

def _detect_mapping(headers):
    m = {}
    for field, hints in _HINTS.items():
        for h in headers:
            if any(hint in str(h) for hint in hints):
                m[field] = h; break
    return m

def _parse_date(val):
    if val is None: return None
    if hasattr(val, 'strftime'): return val.strftime('%Y-%m-%d')
    s = str(val).strip().split(' ')[0].split('T')[0]
    m = re.match(r'(\d{4})[-./](\d{1,2})[-./](\d{1,2})', s)
    if m: return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.match(r'^(\d{4})(\d{2})(\d{2})$', s)
    if m: return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None

def _parse_amount(val):
    if val is None: return 0
    if isinstance(val, (int, float)): return int(abs(val))
    try: return int(abs(float(str(val).replace(',', '').replace(' ', ''))))
    except: return 0

def _parse_file(file_bytes, filename):
    rows = []
    name = filename.lower()
    if name.endswith('.csv'):
        for enc in ['utf-8-sig', 'cp949', 'euc-kr', 'utf-8']:
            try:
                text = file_bytes.decode(enc)
                rows = [[str(c).strip() for c in r]
                        for r in csv.reader(io.StringIO(text)) if any(c for c in r)]
                break
            except: continue
    elif name.endswith('.xls'):
        if not HAS_XLRD:
            return [], []
        wb = xlrd.open_workbook(file_contents=file_bytes)
        ws = wb.sheet_by_index(0)
        for i in range(ws.nrows):
            row_vals = []
            for j in range(ws.ncols):
                cell = ws.cell(i, j)
                if cell.ctype == xlrd.XL_CELL_DATE:
                    try:
                        t = xlrd.xldate.xldate_as_tuple(cell.value, wb.datemode)
                        row_vals.append(datetime(*t[:6]))
                    except:
                        row_vals.append(cell.value)
                else:
                    row_vals.append(cell.value)
            if any(v is not None and str(v).strip() for v in row_vals):
                rows.append(row_vals)
    else:  # .xlsx
        if not HAS_OPENPYXL:
            return [], []
        try:
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
            ws = wb.active
            rows = [[cell.value for cell in row] for row in ws.iter_rows()
                    if any(c.value is not None for c in row)]
        except Exception:
            return [], []
    if not rows: return [], []
    hi = _detect_header(rows)
    headers = [str(h).strip() if h is not None else f'컬럼{i}' for i, h in enumerate(rows[hi])]
    data    = [list(row) for row in rows[hi+1:]
               if any(v is not None and str(v).strip() for v in row)]
    return headers, data


@app.route('/api/card-excel/preview', methods=['POST'])
def api_card_excel_preview():
    f = request.files.get('file')
    if not f: return jsonify({'error': '파일이 없습니다'}), 400
    headers, data = _parse_file(f.read(), f.filename)
    if not headers: return jsonify({'error': '파일을 읽을 수 없습니다. xlsx 또는 csv를 올려주세요.'}), 400
    sample = [
        {h: (str(row[i]).strip() if i < len(row) and row[i] is not None else '')
         for i, h in enumerate(headers)}
        for row in data[:5]
    ]
    all_rows = [
        [(str(row[i]).strip() if i < len(row) and row[i] is not None else '') if not hasattr(row[i] if i < len(row) else None, 'strftime')
         else (row[i].strftime('%Y-%m-%d') if i < len(row) and row[i] is not None else '')
         for i in range(len(headers))]
        for row in data
    ]
    return jsonify({'headers': headers, 'mapping': _detect_mapping(headers),
                    'sample': sample, 'total': len(data), 'all_rows': all_rows})


@app.route('/api/card-excel/mapping/<int:card_id>', methods=['GET', 'POST'])
def api_card_excel_mapping(card_id):
    db = get_db()
    if request.method == 'GET':
        cur = db.cursor()
        cur.execute("SELECT mapping FROM card_mappings WHERE card_id=%s", (card_id,))
        row = cur.fetchone()
        cur.close()
        db.close()
        return jsonify(json.loads(row['mapping']) if row else {})
    cur = db.cursor()
    cur.execute("INSERT INTO card_mappings (card_id, mapping) VALUES (%s, %s) ON CONFLICT (card_id) DO UPDATE SET mapping = EXCLUDED.mapping",
    (card_id, json.dumps(request.json or {})))
    cur.close()
    db.commit(); db.close()
    return jsonify({'ok': True})


@app.route('/api/card-excel/import', methods=['POST'])
def api_card_excel_import():
    data     = request.json or {}
    card_id  = data.get('card_id')
    mapping  = data.get('mapping', {})
    headers  = data.get('headers', [])
    all_rows = data.get('all_rows', [])
    if not card_id or not mapping.get('date') or not mapping.get('amount'):
        return jsonify({'error': '카드, 날짜, 금액 컬럼은 필수입니다'}), 400

    hi = {h: i for i, h in enumerate(headers)}
    def get(row, col): return row[hi[col]] if col and col in hi and hi[col] < len(row) else ''

    db = get_db()
    inserted = skipped = duplicate = 0
    for row in all_rows:
        date_str = _parse_date(get(row, mapping['date']))
        amount   = _parse_amount(get(row, mapping['amount']))
        name     = str(get(row, mapping.get('name', '')) or '').strip()
        inst     = _parse_amount(get(row, mapping.get('installment', ''))) or 1
        category = str(get(row, mapping.get('category', '')) or '').strip()
        if not date_str or amount <= 0: skipped += 1; continue
        tmp_cur = db.cursor()
        tmp_cur.execute("SELECT id FROM card_tx WHERE card_id=%s AND date=%s AND name=%s AND amount=%s",
        (card_id, date_str, name, amount))
        exists = tmp_cur.fetchone()
        tmp_cur.close()
        if exists:
            duplicate += 1; continue
        # 카테고리가 없으면 힌트 자동 적용
        if not category and name:
            category = _get_category_hint(db, name)
        cur = db.cursor()
        cur.execute("INSERT INTO card_tx (card_id,date,name,category,amount,installment) VALUES (%s,%s,%s,%s,%s,%s)",
        (card_id, date_str, name, category, amount, inst))
        cur.close()
        inserted += 1
    db.commit(); db.close()
    return jsonify({'ok': True, 'inserted': inserted, 'skipped': skipped, 'duplicate': duplicate})


# ── API: 카테고리 자동 힌트 ──────────────────────────────────
def _get_category_hint(db, name):
    """가맹점명으로 카테고리 추천 (히스토리 → 키워드 규칙 순)"""
    name = (name or '').strip()
    if not name:
        return ''
    # 1. 히스토리: 동일 가맹점의 가장 최근 카테고리
    cur = db.cursor()
    cur.execute(
    "SELECT category FROM card_tx WHERE name=%s AND category IS NOT NULL AND category!='' "
    "ORDER BY date DESC LIMIT 1", (name,)
    )
    row = cur.fetchone()
    cur.close()
    if row:
        return row['category']
    # 2. 키워드 규칙 (긴 키워드 우선)
    cur = db.cursor()
    cur.execute(
    "SELECT keyword, category FROM card_category_rules ORDER BY LENGTH(keyword) DESC"
    )
    rules = cur.fetchall()
    cur.close()
    name_lower = name.lower()
    for rule in rules:
        if rule['keyword'].lower() in name_lower:
            return rule['category']
    return ''


@app.route('/api/card-category-hint')
def api_card_category_hint():
    name = request.args.get('name', '').strip()
    if not name:
        return jsonify({'category': ''})
    db = get_db()
    category = _get_category_hint(db, name)
    db.close()
    return jsonify({'category': category})


@app.route('/api/card-category-rules', methods=['GET', 'POST'])
def api_card_category_rules():
    db = get_db()
    if request.method == 'GET':
        cur = db.cursor()
        cur.execute("SELECT * FROM card_category_rules ORDER BY keyword")
        rows = cur.fetchall()
        cur.close()
        db.close()
        return jsonify(rows_to_list(rows))
    d = request.json or {}
    cur = db.cursor()
    cur.execute("INSERT INTO card_category_rules (keyword, category) VALUES (%s, %s)",
    (d.get('keyword', ''), d.get('category', '')))
    cur.close()
    db.commit(); db.close()
    return jsonify({'ok': True})


@app.route('/api/categories', methods=['GET', 'POST'])
def api_categories():
    db = get_db()
    if request.method == 'GET':
        cur = db.cursor()
        cur.execute("SELECT * FROM categories ORDER BY sort_order, name")
        rows = cur.fetchall()
        cur.close()
        db.close()
        return jsonify(rows_to_list(rows))
    d = request.json or {}
    cur = db.cursor()
    cur.execute("SELECT COALESCE(MAX(sort_order), -1) FROM categories")
    max_order = cur.fetchone()[0]
    cur.close()
    cur = db.cursor()
    cur.execute("INSERT INTO categories (name, sort_order) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING",
    (d.get('name', '').strip(), max_order + 1))
    cur.close()
    db.commit(); db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/categories/<int:rid>', methods=['PUT', 'DELETE'])
def api_categories_detail(rid):
    db = get_db()
    if request.method == 'DELETE':
        cur = db.cursor()
        cur.execute("DELETE FROM categories WHERE id=%s", (rid,))
        cur.close()
        db.commit(); db.close()
        return jsonify({'ok': True})
    d = request.json or {}
    cur = db.cursor()
    cur.execute("UPDATE categories SET name=%s WHERE id=%s", (d.get('name', '').strip(), rid))
    cur.close()
    db.commit(); db.close()
    return jsonify({'ok': True})


@app.route('/api/card-category-rules/<int:rid>', methods=['PUT', 'DELETE'])
def api_card_category_rules_detail(rid):
    db = get_db()
    if request.method == 'DELETE':
        cur = db.cursor()
        cur.execute("DELETE FROM card_category_rules WHERE id=%s", (rid,))
        cur.close()
        db.commit(); db.close()
        return jsonify({'ok': True})
    d = request.json or {}
    cur = db.cursor()
    cur.execute("UPDATE card_category_rules SET keyword=%s, category=%s WHERE id=%s",
    (d.get('keyword', ''), d.get('category', ''), rid))
    cur.close()
    db.commit(); db.close()
    return jsonify({'ok': True})


# ── API: 자금 그룹 ────────────────────────────────────────────
def _get_fund_group_hint(db, name):
    """가맹점명으로 자금 그룹 추천 (히스토리 → 키워드 규칙 순)"""
    name = (name or '').strip()
    if not name:
        return None
    # 1. 히스토리: 동일 가맹점의 가장 최근 자금 그룹
    cur = db.cursor()
    cur.execute(
    "SELECT fund_group_id FROM card_tx WHERE name=%s AND fund_group_id IS NOT NULL "
    "ORDER BY date DESC LIMIT 1", (name,)
    )
    row = cur.fetchone()
    cur.close()
    if row:
        return row['fund_group_id']
    # 2. 키워드 규칙 (긴 키워드 우선)
    cur = db.cursor()
    cur.execute(
    "SELECT keyword, fund_group_id FROM fund_group_rules ORDER BY LENGTH(keyword) DESC"
    )
    rules = cur.fetchall()
    cur.close()
    name_lower = name.lower()
    for rule in rules:
        if rule['keyword'].lower() in name_lower:
            return rule['fund_group_id']
    return None


@app.route('/fund-management')
def fund_management():
    return render_template('fund_management.html')


@app.route('/api/fund-groups', methods=['GET', 'POST'])
def api_fund_groups():
    db = get_db()
    if request.method == 'GET':
        cur = db.cursor()
        cur.execute("SELECT * FROM fund_groups ORDER BY sort_order, name")
        rows = cur.fetchall()
        cur.close()
        db.close()
        return jsonify(rows_to_list(rows))
    d = request.json or {}
    cur = db.cursor()
    cur.execute("SELECT COALESCE(MAX(sort_order), -1) FROM fund_groups")
    max_order = cur.fetchone()[0]
    cur.close()
    cur = db.cursor()
    cur.execute("INSERT INTO fund_groups (name, sort_order) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING",
    (d.get('name', '').strip(), max_order + 1))
    cur.close()
    db.commit(); db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/fund-groups/<int:rid>', methods=['PUT', 'DELETE'])
def api_fund_groups_detail(rid):
    db = get_db()
    if request.method == 'DELETE':
        cur = db.cursor()
        cur.execute("DELETE FROM fund_groups WHERE id=%s", (rid,))
        cur.close()
        db.commit(); db.close()
        return jsonify({'ok': True})
    d = request.json or {}
    cur = db.cursor()
    cur.execute("UPDATE fund_groups SET name=%s WHERE id=%s", (d.get('name', '').strip(), rid))
    cur.close()
    db.commit(); db.close()
    return jsonify({'ok': True})


@app.route('/api/fund-group-rules', methods=['GET', 'POST'])
def api_fund_group_rules():
    db = get_db()
    if request.method == 'GET':
        cur = db.cursor()
        cur.execute(
        "SELECT r.*, g.name as fund_group_name FROM fund_group_rules r "
        "LEFT JOIN fund_groups g ON r.fund_group_id = g.id ORDER BY r.keyword"
        )
        rows = cur.fetchall()
        cur.close()
        db.close()
        return jsonify(rows_to_list(rows))
    d = request.json or {}
    cur = db.cursor()
    cur.execute("INSERT INTO fund_group_rules (keyword, fund_group_id) VALUES (%s, %s)",
    (d.get('keyword', ''), d.get('fund_group_id')))
    cur.close()
    db.commit(); db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/fund-group-rules/<int:rid>', methods=['PUT', 'DELETE'])
def api_fund_group_rules_detail(rid):
    db = get_db()
    if request.method == 'DELETE':
        cur = db.cursor()
        cur.execute("DELETE FROM fund_group_rules WHERE id=%s", (rid,))
        cur.close()
        db.commit(); db.close()
        return jsonify({'ok': True})
    d = request.json or {}
    cur = db.cursor()
    cur.execute("UPDATE fund_group_rules SET keyword=%s, fund_group_id=%s WHERE id=%s",
    (d.get('keyword', ''), d.get('fund_group_id'), rid))
    cur.close()
    db.commit(); db.close()
    return jsonify({'ok': True})


@app.route('/api/monthly-fund-budgets', methods=['GET', 'POST'])
def api_monthly_fund_budgets():
    db = get_db()
    if request.method == 'GET':
        year  = request.args.get('year')
        month = request.args.get('month')
        cur = db.cursor()
        cur.execute(
        "SELECT b.*, g.name as fund_group_name FROM monthly_fund_budgets b "
        "LEFT JOIN fund_groups g ON b.fund_group_id = g.id "
        "WHERE b.year=%s AND b.month=%s ORDER BY g.sort_order, g.name",
        (year, int(month))
        )
        rows = cur.fetchall()
        cur.close()
        db.close()
        return jsonify(rows_to_list(rows))
    d = request.json or {}
    cur = db.cursor()
    cur.execute(
    "INSERT INTO monthly_fund_budgets (fund_group_id, year, month, budget_amount) VALUES (%s,%s,%s,%s) "
    "ON CONFLICT(fund_group_id, year, month) DO UPDATE SET budget_amount=excluded.budget_amount",
    (d.get('fund_group_id'), d.get('year'), d.get('month'), d.get('budget_amount', 0))
    )
    cur.close()
    db.commit(); db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/fund-summary')
def api_fund_summary():
    year  = request.args.get('year')
    month = request.args.get('month')
    db = get_db()
    # 자금 그룹별 실제 지출 집계
    cur = db.cursor()
    cur.execute(
    "SELECT g.id, g.name, g.sort_order, COALESCE(SUM(t.amount), 0) as actual "
    "FROM fund_groups g "
    "LEFT JOIN card_tx t ON t.fund_group_id = g.id "
    "  AND to_char(t.date::date, 'YYYY') = %s AND to_char(t.date::date, 'MM') = %s "
    "GROUP BY g.id ORDER BY g.sort_order, g.name",
    (year, month.zfill(2))
    )
    actuals = cur.fetchall()
    cur.close()
    cur = db.cursor()
    cur.execute(
    "SELECT fund_group_id, budget_amount FROM monthly_fund_budgets WHERE year=%s AND month=%s",
    (year, int(month))
    )
    budgets = {r['fund_group_id']: r['budget_amount'] for r in cur.fetchall()}
    cur.close()
    db.close()
    result = []
    for row in actuals:
        result.append({
            'id': row['id'],
            'name': row['name'],
            'actual': row['actual'],
            'budget': budgets.get(row['id'], 0),
        })
    return jsonify(result)


@app.route('/api/card-tx/auto-fund-group', methods=['POST'])
def api_card_tx_auto_fund_group():
    data    = request.json or {}
    card_id = data.get('card_id')
    year    = data.get('year')
    month   = data.get('month')

    db = get_db()
    query  = "SELECT id, name FROM card_tx WHERE fund_group_locked = 0"
    params = []
    if card_id:
        query += " AND card_id = %s"; params.append(card_id)
    if year and month:
        query += " AND to_char(date::date, 'YYYY') = %s AND to_char(date::date, 'MM') = %s"
        params += [year, month.zfill(2)]

    cur = db.cursor()
    cur.execute(query, params)
    rows = cur.fetchall()
    cur.close()
    updated = 0
    for row in rows:
        hint = _get_fund_group_hint(db, row['name'])
        if hint:
            cur = db.cursor()
            cur.execute("UPDATE card_tx SET fund_group_id=%s WHERE id=%s", (hint, row['id']))
            cur.close()
            updated += 1
    db.commit()
    db.close()
    return jsonify({'ok': True, 'updated': updated})


@app.route('/api/fund-group-hint')
def api_fund_group_hint():
    name = request.args.get('name', '').strip()
    if not name:
        return jsonify({'fund_group_id': None})
    db = get_db()
    fund_group_id = _get_fund_group_hint(db, name)
    db.close()
    return jsonify({'fund_group_id': fund_group_id})


# ── 동기화 페이지 ────────────────────────────────────────────
@app.route('/sync')
def sync_page():
    return render_template('sync.html')


SOURCE_FILES = [
    'app.py', 'database.py', 'requirements.txt',
    'templates/base.html', 'templates/dashboard.html',
    'templates/income.html', 'templates/budget.html',
    'templates/cards.html', 'templates/investments.html',
    'templates/realestate.html', 'templates/loans.html',
    'templates/pension.html', 'templates/goals.html',
    'templates/monthly.html', 'templates/sync.html',
    'templates/fund_management.html',
    'static/css/style.css', 'static/js/common.js', 'static/js/dashboard.js',
]

@app.route('/api/export-source')
def api_export_source():
    import base64
    files = {}
    base = os.path.dirname(os.path.abspath(__file__))
    for rel in SOURCE_FILES:
        path = os.path.join(base, rel.replace('/', os.sep))
        if os.path.exists(path):
            with open(path, 'rb') as f:
                files[rel] = base64.b64encode(f.read()).decode()
    return jsonify({'files': files})


@app.route('/api/compare-source', methods=['POST'])
def api_compare_source():
    import base64
    files = (request.json or {}).get('files', {})
    if not files:
        return jsonify({'error': '내용이 없습니다'}), 400
    base_dir = os.path.dirname(os.path.abspath(__file__))
    result = []
    for rel, b64 in files.items():
        dest = os.path.join(base_dir, rel.replace('/', os.sep))
        incoming = base64.b64decode(b64)
        if os.path.exists(dest):
            with open(dest, 'rb') as f:
                current = f.read()
            status = 'same' if incoming == current else 'changed'
        else:
            status = 'new'
        result.append({'file': rel, 'status': status, 'size': len(incoming)})
    return jsonify(result)


@app.route('/api/import-source', methods=['POST'])
def api_import_source():
    import base64
    files = (request.json or {}).get('files', {})
    if not files:
        return jsonify({'error': '내용이 없습니다'}), 400
    base = os.path.dirname(os.path.abspath(__file__))
    for rel, b64 in files.items():
        dest = os.path.join(base, rel.replace('/', os.sep))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, 'wb') as f:
            f.write(base64.b64decode(b64))
    return jsonify({'ok': True, 'count': len(files)})


@app.route('/api/export-text')
def api_export_text():
    return jsonify({'error': 'PostgreSQL 환경에서는 텍스트 백업 기능을 지원하지 않습니다.'}), 501


@app.route('/api/import-text', methods=['POST'])
def api_import_text():
    return jsonify({'error': 'PostgreSQL 환경에서는 텍스트 복구 기능을 지원하지 않습니다.'}), 501


if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)
