from flask import Flask, render_template, request, jsonify, Response, redirect, url_for, session
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from authlib.integrations.flask_client import OAuth
from flask_cors import CORS
from database import get_db, init_db, seed_user_defaults
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

app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

login_manager = LoginManager(app)
login_manager.login_view = 'login_page'

oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.environ.get('GOOGLE_CLIENT_ID'),
    client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
)

class User(UserMixin):
    def __init__(self, id, email, name, picture):
        self.id = id
        self.email = email
        self.name = name
        self.picture = picture

@login_manager.user_loader
def load_user(user_id):
    try:
        db = get_db()
        cur = db.cursor()
        cur.execute("SELECT id, email, name, picture FROM users WHERE id = %s", (int(user_id),))
        row = cur.fetchone()
        cur.close()
        db.close()
        if row:
            return User(row['id'], row['email'], row['name'], row['picture'])
    except Exception:
        pass
    return None

def uid():
    return current_user.id

from flask.json.provider import DefaultJSONProvider
class CustomJSONProvider(DefaultJSONProvider):
    def default(self, obj):
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        return super().default(obj)
app.json = CustomJSONProvider(app)

# ── 버전 정보 ────────────────────────────────────────────────
def _load_version():
    try:
        with open(os.path.join(os.path.dirname(__file__), 'version.json'), 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {"version": "1.00", "updated": ""}

@app.context_processor
def inject_version():
    v = _load_version()
    return {"APP_VERSION": v.get("version", "1.00"), "APP_UPDATED": v.get("updated", "")}

# ── 페이지 라우터 ────────────────────────────────────────────
@app.route('/')
@login_required
def dashboard():
    return render_template('dashboard.html')

@app.route('/income')
@login_required
def income():
    return render_template('income.html')

@app.route('/budget')
@login_required
def budget():
    return render_template('budget.html')

@app.route('/cards')
@login_required
def cards():
    return render_template('cards.html')

@app.route('/investments')
@login_required
def investments():
    return render_template('investments.html')

@app.route('/realestate')
@login_required
def realestate():
    return render_template('realestate.html')

@app.route('/loans')
@login_required
def loans():
    return render_template('loans.html')

@app.route('/pension')
@login_required
def pension():
    return render_template('pension.html')

@app.route('/cash')
@login_required
def cash():
    return render_template('cash.html')

@app.route('/goals')
@login_required
def goals():
    return render_template('goals.html')

@app.route('/monthly')
@login_required
def monthly():
    return render_template('monthly.html')

@app.route('/tech-tree')
@login_required
def tech_tree():
    return render_template('tech_tree.html')

@app.route('/analysis/calculator')
@login_required
def analysis_calculator():
    return render_template('analysis_calculator.html')

@app.route('/login')
def login_page():
    if current_user.is_authenticated:
        return redirect('/')
    return render_template('login.html')

@app.route('/auth/google')
def auth_google():
    redirect_uri = url_for('auth_google_callback', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/auth/google/callback')
def auth_google_callback():
    token = google.authorize_access_token()
    userinfo = token.get('userinfo') or {}
    google_id = userinfo.get('sub')
    email     = userinfo.get('email', '')
    name      = userinfo.get('name', '')
    picture   = userinfo.get('picture', '')
    if not google_id:
        return redirect('/login')
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT id, email, name, picture FROM users WHERE google_id = %s", (google_id,))
    row = cur.fetchone()
    is_new = False
    if row:
        user = User(row['id'], row['email'], row['name'], row['picture'])
        cur.execute("UPDATE users SET name=%s, picture=%s WHERE id=%s", (name, picture, user.id))
    else:
        cur.execute(
            "INSERT INTO users (google_id, email, name, picture) VALUES (%s,%s,%s,%s) RETURNING id",
            (google_id, email, name, picture)
        )
        new_id = cur.fetchone()[0]
        user = User(new_id, email, name, picture)
        is_new = True
    db.commit()
    cur.close()
    db.close()
    if is_new:
        seed_user_defaults(user.id)
    login_user(user, remember=True)
    return redirect('/')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect('/login')


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
@login_required
def api_income():
    db = get_db()
    if request.method == 'GET':
        year  = request.args.get('year')
        month = request.args.get('month')
        query = "SELECT * FROM income WHERE user_id = %s"
        params = [uid()]
        if year and month:
            query += " AND to_char(date::date, 'YYYY') = %s AND to_char(date::date, 'MM') = %s"
            params += [year, month.zfill(2)]
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
            "INSERT INTO income (date, category, name, memo, amount, user_id) VALUES (%s,%s,%s,%s,%s,%s)",
            (tx_date, data.get('category'), data.get('name'), data.get('memo'), data['amount'], uid())
            )
            cur.close()
    else:
        cur = db.cursor()
        cur.execute(
        "INSERT INTO income (date, category, name, memo, amount, user_id) VALUES (%s,%s,%s,%s,%s,%s)",
        (base_date_str, data.get('category'), data.get('name'), data.get('memo'), data['amount'], uid())
        )
        cur.close()

    db.commit()
    db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/income/<int:rid>', methods=['PUT', 'DELETE'])
@login_required
def api_income_detail(rid):
    db = get_db()
    if request.method == 'PUT':
        data = request.json
        cur = db.cursor()
        cur.execute(
        "UPDATE income SET date=%s, category=%s, name=%s, memo=%s, amount=%s WHERE id=%s AND user_id=%s",
        (data.get('date'), data.get('category'), data.get('name'),
        data.get('memo'), data.get('amount', 0), rid, uid())
        )
        cur.close()
        db.commit()
        db.close()
        return jsonify({'ok': True})
    cur = db.cursor()
    cur.execute("DELETE FROM income WHERE id = %s AND user_id = %s", (rid, uid()))
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True})


# ── API: 가계부 ──────────────────────────────────────────────
def _sync_card_tx(db, budget_id, data, user_id):
    """budget 저장 시 card_tx 자동 동기화"""
    card_id = data.get('card_id') or None
    if card_id:
        cur = db.cursor()
        cur.execute("SELECT id FROM card_tx WHERE budget_id = %s AND user_id = %s", (budget_id, user_id))
        existing = cur.fetchone()
        cur.close()
        if existing:
            cur = db.cursor()
            cur.execute(
            "UPDATE card_tx SET card_id=%s, date=%s, name=%s, category=%s, amount=%s, memo=%s WHERE budget_id=%s AND user_id=%s",
            (card_id, data.get('date'), data.get('name'), data.get('category'),
            data.get('amount', 0), data.get('memo'), budget_id, user_id)
            )
            cur.close()
        else:
            cur = db.cursor()
            cur.execute(
            "INSERT INTO card_tx (card_id, date, name, category, amount, installment, memo, budget_id, user_id) VALUES (%s,%s,%s,%s,%s,1,%s,%s,%s)",
            (card_id, data.get('date'), data.get('name'), data.get('category'),
            data.get('amount', 0), data.get('memo'), budget_id, user_id)
            )
            cur.close()
    else:
        cur = db.cursor()
        cur.execute("DELETE FROM card_tx WHERE budget_id = %s AND user_id = %s", (budget_id, user_id))
        cur.close()


@app.route('/api/budget', methods=['GET', 'POST'])
@login_required
def api_budget():
    db = get_db()
    if request.method == 'GET':
        year  = request.args.get('year')
        month = request.args.get('month')

        # 고정/변동지출 자동 생성 (해당 월에 아직 없는 경우)
        if year and month:
            try:
                ym = f"{year}-{month.zfill(2)}"
                cur = db.cursor()
                cur.execute("SELECT * FROM budget_recurring WHERE active = TRUE AND user_id = %s", (uid(),))
                recurrings = rows_to_list(cur.fetchall())
                cur.close()
                for rec in recurrings:
                    cur = db.cursor()
                    cur.execute(
                        "SELECT id FROM budget WHERE recurring_id=%s AND to_char(date::date,'YYYY-MM')=%s AND user_id=%s",
                        (rec['id'], ym, uid())
                    )
                    exists = cur.fetchone()
                    cur.close()
                    if not exists:
                        date_str = f"{year}-{month.zfill(2)}-01"
                        cur = db.cursor()
                        cur.execute(
                            "INSERT INTO budget (date,category,name,type,payment_method,amount,memo,card_id,recurring_id,user_id) "
                            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                            (date_str, rec['category'], rec['name'], rec['type'],
                             rec['payment_method'], rec['amount'], rec['memo'],
                             rec['card_id'], rec['id'], uid())
                        )
                        cur.close()
                db.commit()
            except Exception:
                db.rollback()

        query = """SELECT b.*, c.card_name
                   FROM budget b
                   LEFT JOIN card_info c ON b.card_id = c.id"""
        params = []
        if year and month:
            query += " WHERE b.user_id = %s AND to_char(b.date::date, 'YYYY') = %s AND to_char(b.date::date, 'MM') = %s"
            params = [uid(), year, month.zfill(2)]
        else:
            query += " WHERE b.user_id = %s"
            params = [uid()]
        query += " ORDER BY b.date DESC"
        cur = db.cursor()
        cur.execute(query, params)
        rows = cur.fetchall()
        cur.close()
        db.close()
        return jsonify(rows_to_list(rows))

    data = request.json
    type_ = data.get('type', '')
    recurring_id = None

    # 카테고리 미설정 시 규칙 자동 적용
    if not data.get('category'):
        auto_cat = _apply_budget_category_rule(db, data.get('name', ''))
        if auto_cat:
            data['category'] = auto_cat

    # 고정/변동지출이면 반복 마스터 생성 (테이블 미존재 시 무시)
    if type_ in ('고정지출', '변동지출'):
        try:
            cur = db.cursor()
            cur.execute(
                "INSERT INTO budget_recurring (name,category,type,payment_method,card_id,amount,memo,user_id) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (data.get('name'), data.get('category'), type_,
                 data.get('payment_method'), data.get('card_id') or None,
                 data['amount'], data.get('memo'), uid())
            )
            recurring_id = cur.fetchone()[0]
            cur.close()
        except Exception:
            db.rollback()
            recurring_id = None

    # recurring_id 컬럼 존재 여부에 따라 INSERT 분기
    cur = db.cursor()
    try:
        cur.execute(
            "INSERT INTO budget (date,category,name,type,payment_method,amount,memo,card_id,recurring_id,user_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (data['date'], data.get('category'), data.get('name'), type_,
             data.get('payment_method'), data['amount'], data.get('memo'),
             data.get('card_id') or None, recurring_id, uid())
        )
    except Exception:
        db.rollback()
        cur = db.cursor()
        cur.execute(
            "INSERT INTO budget (date,category,name,type,payment_method,amount,memo,card_id,user_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (data['date'], data.get('category'), data.get('name'), type_,
             data.get('payment_method'), data['amount'], data.get('memo'),
             data.get('card_id') or None, uid())
        )
    budget_id = cur.fetchone()[0]
    cur.close()
    _sync_card_tx(db, budget_id, data, uid())
    db.commit()
    db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/budget/receipt', methods=['POST'])
@login_required
def api_budget_receipt():
    if 'file' not in request.files:
        return jsonify({'error': '파일이 없습니다.'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '선택된 파일이 없습니다.'}), 400

    filename = file.filename
    img_bytes = file.read()

    tx_date = date.today().isoformat()
    amount = 0
    name = ''
    memo = f'영수증 첨부: {filename}'
    payment_method = '신용카드'
    type_ = '변동지출'
    category = ''

    # 1. 파일명에서 파싱
    date_m = re.search(r'(20\d{2})[-_.]?(\d{2})[-_.]?(\d{2})', filename)
    if date_m:
        tx_date = f"{date_m.group(1)}-{date_m.group(2)}-{date_m.group(3)}"

    amount_m = re.findall(r'(\d{1,3}(?:,\d{3})+|\d{3,7})\s*(?:원|KRW)', filename)
    if amount_m:
        amount = int(amount_m[-1].replace(',', ''))
    else:
        nums = re.findall(r'\d+', filename)
        for num in nums:
            val = int(num)
            if val >= 1000 and val != int(tx_date.replace('-', '')):
                amount = val
                break

    common_stores = {
        '스타벅스': '식비', '이마트': '쇼핑', '다이소': '쇼핑', '쿠팡': '쇼핑', 
        '택시': '교통비', 'CU': '식비', 'GS25': '식비', '세븐일레븐': '식비',
        '맥도날드': '식비', '카페': '식비', '식당': '식비', '파리바게뜨': '식비',
        '올리브영': '쇼핑', '주유소': '교통비', '병원': '의료비', '약국': '의료비'
    }
    for store, cat in common_stores.items():
        if store in filename:
            name = store
            category = cat
            break

    # 2. OCR 시도 (설치되어 있는 경우)
    extracted_text = ""
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(img_bytes))
        try:
            import pytesseract
            extracted_text = pytesseract.image_to_string(img, lang='kor+eng')
        except Exception:
            pass
    except Exception:
        pass

    if extracted_text:
        if amount == 0:
            amts = re.findall(r'(?:합계|금액|결제금액|총액|승인금액)\s*[:=]?\s*([\d,]+)\s*(?:원)?', extracted_text)
            if amts:
                amount = int(amts[0].replace(',', ''))
            else:
                nums = re.findall(r'\b\d{1,3}(?:,\d{3})+\b', extracted_text)
                if nums:
                    amount = int(nums[-1].replace(',', ''))
        
        if date_m is None:
            dt_m = re.search(r'(20\d{2})[-/.](\d{2})[-/.](\d{2})', extracted_text)
            if dt_m:
                tx_date = f"{dt_m.group(1)}-{dt_m.group(2)}-{dt_m.group(3)}"

        if not name:
            lines = [line.strip() for line in extracted_text.split('\n') if line.strip()]
            for line in lines:
                for store, cat in common_stores.items():
                    if store in line:
                        name = store
                        category = cat
                        break
                if name: break
            if not name and lines:
                cleaned = re.sub(r'[^\w\s]', '', lines[0]).strip()
                if cleaned and not cleaned.isdigit():
                    name = cleaned[:15]

    if not name:
        name = os.path.splitext(filename)[0][:15]
    if amount == 0:
        amount = 10000
    
    db = get_db()
    if not category:
        auto_cat = _apply_budget_category_rule(db, name)
        if auto_cat:
            category = auto_cat
        else:
            category = '식비'

    cur = db.cursor()
    try:
        cur.execute(
            "INSERT INTO budget (date, category, name, type, payment_method, amount, memo, user_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (tx_date, category, name, type_, payment_method, amount, memo, uid())
        )
        budget_id = cur.fetchone()[0]
        db.commit()
    except Exception as e:
        db.rollback()
        cur.close()
        db.close()
        return jsonify({'error': f'DB 저장 실패: {str(e)}'}), 500
    cur.close()
    db.close()

    return jsonify({
        'ok': True,
        'budget_id': budget_id,
        'parsed': {
            'date': tx_date,
            'category': category,
            'name': name,
            'amount': amount,
            'memo': memo
        }
    }), 201


@app.route('/api/budget/<int:rid>', methods=['PUT', 'DELETE'])
@login_required
def api_budget_detail(rid):
    db = get_db()
    if request.method == 'PUT':
        data = request.json
        type_ = data.get('type', '')

        # 현재 행의 recurring_id, date 조회 (컬럼 없으면 None)
        try:
            cur = db.cursor()
            cur.execute("SELECT recurring_id, date FROM budget WHERE id=%s AND user_id=%s", (rid, uid()))
            row = cur.fetchone()
            recurring_id = row[0] if row else None
            row_date     = row[1] if row else None
            cur.close()
        except Exception:
            db.rollback()
            recurring_id = None
            row_date     = None

        cur = db.cursor()
        cur.execute(
            "UPDATE budget SET date=%s,category=%s,name=%s,type=%s,payment_method=%s,amount=%s,memo=%s,card_id=%s WHERE id=%s AND user_id=%s",
            (data.get('date'), data.get('category'), data.get('name'), type_,
             data.get('payment_method'), data.get('amount', 0), data.get('memo'),
             data.get('card_id') or None, rid, uid())
        )
        cur.close()

        # 고정지출: 마스터 + 이후 모든 월 동기화
        if type_ == '고정지출' and recurring_id:
            try:
                cur = db.cursor()
                cur.execute(
                    "UPDATE budget_recurring SET name=%s,category=%s,payment_method=%s,card_id=%s,amount=%s,memo=%s WHERE id=%s AND user_id=%s",
                    (data.get('name'), data.get('category'), data.get('payment_method'),
                     data.get('card_id') or None, data.get('amount', 0), data.get('memo'), recurring_id, uid())
                )
                cur.close()
                cur = db.cursor()
                cur.execute(
                    "UPDATE budget SET name=%s,category=%s,payment_method=%s,card_id=%s,amount=%s,memo=%s "
                    "WHERE recurring_id=%s AND date > %s AND user_id=%s",
                    (data.get('name'), data.get('category'), data.get('payment_method'),
                     data.get('card_id') or None, data.get('amount', 0), data.get('memo'),
                     recurring_id, row_date, uid())
                )
                cur.close()
            except Exception:
                db.rollback()

        _sync_card_tx(db, rid, data, uid())

        # 카테고리가 설정된 경우 항목명을 키워드로 학습
        new_category = data.get('category', '')
        new_name     = data.get('name', '')
        rule_id = None
        if new_category and new_name:
            rule_id = _learn_budget_category(db, new_name, new_category)

        db.commit()
        db.close()
        return jsonify({'ok': True,
                        'learned':   rule_id is not None,
                        'rule_id':   rule_id,
                        'keyword':   new_name     if rule_id else None,
                        'category':  new_category if rule_id else None})

    # DELETE
    mode = request.args.get('mode', 'single')  # 'single' | 'forward'
    cur = db.cursor()
    cur.execute("SELECT recurring_id, date FROM budget WHERE id=%s AND user_id=%s", (rid, uid()))
    row = cur.fetchone()
    recurring_id = row[0] if row else None
    row_date     = row[1] if row else None
    cur.close()

    if mode == 'forward' and recurring_id:
        # 이 날짜 이후 + 이 행 포함 모두 삭제, 반복 비활성화
        cur = db.cursor()
        cur.execute(
            "DELETE FROM card_tx WHERE budget_id IN "
            "(SELECT id FROM budget WHERE recurring_id=%s AND date >= %s AND user_id=%s)",
            (recurring_id, row_date, uid())
        )
        cur.close()
        cur = db.cursor()
        cur.execute("DELETE FROM budget WHERE recurring_id=%s AND date >= %s AND user_id=%s", (recurring_id, row_date, uid()))
        cur.close()
        cur = db.cursor()
        cur.execute("UPDATE budget_recurring SET active=FALSE WHERE id=%s AND user_id=%s", (recurring_id, uid()))
        cur.close()
    else:
        cur = db.cursor()
        cur.execute("DELETE FROM card_tx WHERE budget_id=%s AND user_id=%s", (rid, uid()))
        cur.close()
        cur = db.cursor()
        cur.execute("DELETE FROM budget WHERE id=%s AND user_id=%s", (rid, uid()))
        cur.close()

    db.commit()
    db.close()
    return jsonify({'ok': True})


# ── API: 가계부 카테고리 ─────────────────────────────────────
@app.route('/api/budget-categories', methods=['GET', 'POST'])
@login_required
def api_budget_categories():
    db = get_db()
    cur = db.cursor()
    if request.method == 'GET':
        cur.execute("SELECT id, name FROM budget_categories WHERE user_id = %s ORDER BY sort_order, id", (uid(),))
        rows = cur.fetchall()
        db.close()
        return jsonify([{'id': r['id'], 'name': r['name']} for r in rows])
    data = request.json or {}
    name = (data.get('name') or '').strip()
    if not name:
        db.close()
        return jsonify({'error': 'name required'}), 400
    cur.execute("SELECT COALESCE(MAX(sort_order),0)+1 FROM budget_categories WHERE user_id = %s", (uid(),))
    next_order = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO budget_categories (name, sort_order, user_id) VALUES (%s, %s, %s)",
        (name, next_order, uid())
    )
    db.commit()
    db.close()
    return jsonify({'ok': True})

@app.route('/api/budget-categories/<int:cid>', methods=['DELETE'])
@login_required
def api_budget_category_delete(cid):
    db = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM budget_categories WHERE id=%s AND user_id=%s", (cid, uid()))
    db.commit()
    db.close()
    return jsonify({'ok': True})


# ── API: 가계부 자동 분류 규칙 ──────────────────────────────────
@app.route('/api/budget-category-rules', methods=['GET', 'POST'])
@login_required
def api_budget_category_rules():
    db = get_db()
    cur = db.cursor()
    if request.method == 'GET':
        cur.execute("SELECT id, keyword, category FROM budget_category_rules WHERE user_id = %s ORDER BY id DESC", (uid(),))
        rows = cur.fetchall()
        db.close()
        return jsonify(rows_to_list(rows))
    data = request.json or {}
    kw  = (data.get('keyword') or '').strip()
    cat = (data.get('category') or '').strip()
    if not kw or not cat:
        db.close()
        return jsonify({'error': 'keyword and category required'}), 400
    cur.execute("DELETE FROM budget_category_rules WHERE keyword=%s AND user_id=%s", (kw, uid()))
    cur.execute(
        "INSERT INTO budget_category_rules (keyword, category, user_id) VALUES (%s, %s, %s)",
        (kw, cat, uid())
    )
    db.commit()
    db.close()
    return jsonify({'ok': True})

@app.route('/api/budget-category-rules/<int:rid>', methods=['DELETE', 'PUT'])
@login_required
def api_budget_category_rule_detail(rid):
    db = get_db()
    cur = db.cursor()
    if request.method == 'PUT':
        data = request.json or {}
        kw  = (data.get('keyword') or '').strip()
        cat = (data.get('category') or '').strip()
        if kw and cat:
            cur.execute("DELETE FROM budget_category_rules WHERE id=%s AND user_id=%s", (rid, uid()))
            cur.execute(
                "INSERT INTO budget_category_rules (keyword, category, user_id) VALUES (%s, %s, %s)",
                (kw, cat, uid())
            )
    else:
        cur.execute("DELETE FROM budget_category_rules WHERE id=%s AND user_id=%s", (rid, uid()))
    db.commit()
    db.close()
    return jsonify({'ok': True})


def _apply_budget_category_rule(db, name):
    """항목명에 매칭되는 규칙이 있으면 카테고리를 반환."""
    if not name:
        return None
    try:
        cur = db.cursor()
        cur.execute(
            "SELECT keyword, category FROM budget_category_rules WHERE user_id = %s ORDER BY LENGTH(keyword) DESC",
            (uid(),)
        )
        rules = cur.fetchall()
        cur.close()
        name_lower = name.lower()
        for r in rules:
            if r['keyword'].lower() in name_lower:
                return r['category']
    except Exception:
        pass
    return None


def _learn_budget_category(db, name, category):
    """항목명을 키워드로 학습. 새로 등록된 경우 rule_id 반환, 아니면 None."""
    if not name or not category:
        return None
    try:
        cur = db.cursor()
        cur.execute("SELECT keyword FROM budget_category_rules WHERE user_id = %s", (uid(),))
        rules = cur.fetchall()
        cur.close()
        name_lower = name.lower()
        # 이미 커버되는 규칙이 있으면 등록하지 않음
        if any(r['keyword'].lower() in name_lower for r in rules):
            return None
        cur = db.cursor()
        cur.execute("DELETE FROM budget_category_rules WHERE keyword=%s AND user_id=%s", (name, uid()))
        cur.execute(
            "INSERT INTO budget_category_rules (keyword, category, user_id) VALUES (%s, %s, %s) RETURNING id",
            (name, category, uid())
        )
        row = cur.fetchone()
        cur.close()
        return row[0] if row else None
    except Exception:
        return None


# ── API: 카드 정보 ───────────────────────────────────────────
@app.route('/api/cards', methods=['GET', 'POST'])
@login_required
def api_cards():
    db = get_db()
    if request.method == 'GET':
        cur = db.cursor()
        cur.execute("SELECT * FROM card_info WHERE user_id = %s ORDER BY card_num", (uid(),))
        rows = cur.fetchall()
        cur.close()
        db.close()
        return jsonify(rows_to_list(rows))

    data = request.json
    cur = db.cursor()
    cur.execute(
    "INSERT INTO card_info (card_num, card_name, limit_amount, payment_day, billing_day, benefit, user_id) VALUES (%s,%s,%s,%s,%s,%s,%s)",
    (data['card_num'], data.get('card_name'), data.get('limit_amount', 0),
    data.get('payment_day'), data.get('billing_day'), data.get('benefit'), uid())
    )
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/cards/<int:cid>', methods=['PUT', 'DELETE'])
@login_required
def api_card_detail(cid):
    db = get_db()
    if request.method == 'PUT':
        data = request.json
        cur = db.cursor()
        cur.execute(
        "UPDATE card_info SET card_num=%s, card_name=%s, limit_amount=%s, payment_day=%s, billing_day=%s, benefit=%s WHERE id=%s AND user_id=%s",
        (data.get('card_num'), data.get('card_name'), data.get('limit_amount', 0),
        data.get('payment_day'), data.get('billing_day'), data.get('benefit'), cid, uid())
        )
        cur.close()
        db.commit()
        db.close()
        return jsonify({'ok': True})
    cur = db.cursor()
    cur.execute("DELETE FROM card_info WHERE id = %s AND user_id = %s", (cid, uid()))
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True})


# ── API: 카드 거래내역 ───────────────────────────────────────
@app.route('/api/card-tx', methods=['GET', 'POST'])
@login_required
def api_card_tx():
    db = get_db()
    if request.method == 'GET':
        card_id = request.args.get('card_id')
        year    = request.args.get('year')
        month   = request.args.get('month')
        query   = "SELECT t.*, c.card_name FROM card_tx t LEFT JOIN card_info c ON t.card_id = c.id"
        params  = []
        conds   = ["t.user_id = %s"]
        params.append(uid())
        if card_id:
            conds.append("t.card_id = %s"); params.append(card_id)
        if year and month:
            conds.append("to_char(t.date::date, 'YYYY') = %s"); params.append(year)
            conds.append("to_char(t.date::date, 'MM') = %s"); params.append(month.zfill(2))
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
        cur.execute("SELECT id, name FROM fund_groups WHERE user_id = %s", (uid(),))
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
    "INSERT INTO card_tx (card_id, date, name, category, amount, installment, memo, user_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
    (data.get('card_id'), data['date'], data.get('name'), data.get('category'),
    data['amount'], data.get('installment', 1), data.get('memo'), uid())
    )
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/card-tx/<int:rid>', methods=['PUT', 'DELETE'])
@login_required
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
        " category_locked=%s, fund_group_id=%s, fund_group_locked=%s WHERE id=%s AND user_id=%s",
        (data.get('card_id'), data.get('date'), data.get('name'), category,
        data.get('amount', 0), data.get('installment', 1), data.get('memo'),
        locked, fund_group_id, fund_group_locked, rid, uid())
        )
        cur.close()
        db.commit()
        db.close()
        return jsonify({'ok': True})
    cur = db.cursor()
    cur.execute("DELETE FROM card_tx WHERE id = %s AND user_id = %s", (rid, uid()))
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True})


@app.route('/api/card-tx/bulk', methods=['DELETE'])
@login_required
def api_card_tx_bulk_delete():
    data = request.json or {}
    ids  = data.get('ids', [])
    if not ids:
        return jsonify({'error': 'ids가 필요합니다'}), 400
    db = get_db()
    placeholders = ','.join('%s' * len(ids))
    cur = db.cursor()
    cur.execute(f"DELETE FROM card_tx WHERE id IN ({placeholders}) AND user_id = %s", ids + [uid()])
    deleted = cur.rowcount
    cur.close()
    db.commit(); db.close()
    return jsonify({'ok': True, 'deleted': deleted})


# ── API: 가계부 대조 ──────────────────────────────────────────
@app.route('/api/card-reconcile')
@login_required
def api_card_reconcile():
    """카드 거래내역 ↔ 가계부 자동 매칭"""
    card_id = request.args.get('card_id', type=int)
    year    = request.args.get('year',    type=int)
    month   = request.args.get('month',   type=int)
    if not all([card_id, year, month]):
        return jsonify({'error': 'card_id, year, month 필요'}), 400

    from datetime import timedelta
    first_day   = date(year, month, 1)
    last_month  = month % 12 + 1
    last_year   = year + (1 if month == 12 else 0)
    last_day    = date(last_year, last_month, 1) - timedelta(days=1)
    range_start = (first_day - timedelta(days=3)).isoformat()
    range_end   = (last_day  + timedelta(days=3)).isoformat()
    ym = f"{year}-{month:02d}"

    db  = get_db()
    cur = db.cursor()

    cur.execute("""
        SELECT id, date, name, category, amount, installment, memo
        FROM card_tx
        WHERE card_id = %s AND to_char(date::date, 'YYYY-MM') = %s AND user_id = %s
        ORDER BY date, id
    """, (card_id, ym, uid()))
    card_txs = rows_to_list(cur.fetchall())

    cur.execute("""
        SELECT id, date, name, category, amount, payment_method, memo
        FROM budget
        WHERE date >= %s AND date <= %s AND amount > 0 AND user_id = %s
        ORDER BY date, id
    """, (range_start, range_end, uid()))
    budget_entries = rows_to_list(cur.fetchall())
    cur.close(); db.close()

    used = set()
    result = []
    for tx in card_txs:
        tx_date   = date.fromisoformat(str(tx['date'])[:10])
        tx_amount = int(tx['amount'])
        best = None; best_days = 999
        for b in budget_entries:
            if b['id'] in used or int(b['amount']) != tx_amount:
                continue
            diff = abs((tx_date - date.fromisoformat(str(b['date'])[:10])).days)
            if diff <= 3 and diff < best_days:
                best_days = diff; best = b
        if best:
            used.add(best['id'])
            result.append({**tx, 'status': 'matched',
                           'budget_id': best['id'], 'budget_name': best['name'],
                           'budget_date': str(best['date'])[:10],
                           'budget_cat': best.get('category',''), 'date_diff': best_days})
        else:
            result.append({**tx, 'status': 'unmatched', 'budget_id': None})

    matched   = sum(1 for r in result if r['status'] == 'matched')
    unmatched = len(result) - matched
    return jsonify({'items': result, 'matched': matched,
                    'unmatched': unmatched, 'total': len(result)})


@app.route('/api/card-reconcile/add-budget', methods=['POST'])
@login_required
def api_card_reconcile_add_budget():
    """미매칭 카드 거래를 가계부에 일괄 추가"""
    data        = request.json or {}
    card_tx_ids = data.get('card_tx_ids', [])
    card_id     = data.get('card_id')
    if not card_tx_ids:
        return jsonify({'ok': True, 'added': 0})

    db  = get_db()
    cur = db.cursor()
    placeholders = ','.join(['%s'] * len(card_tx_ids))
    cur.execute(f"SELECT id, date, name, category, amount, memo FROM card_tx WHERE id IN ({placeholders}) AND user_id = %s",
                card_tx_ids + [uid()])
    txs = rows_to_list(cur.fetchall())
    added = 0
    for tx in txs:
        cur.execute("""
            INSERT INTO budget (date, category, name, type, payment_method, amount, memo, card_id, user_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (str(tx['date'])[:10], tx.get('category') or '', tx.get('name') or '',
              '변동', '카드', int(tx['amount']), tx.get('memo') or '', card_id, uid()))
        added += 1
    cur.close(); db.commit(); db.close()
    return jsonify({'ok': True, 'added': added})


@app.route('/api/card-tx/auto-categorize', methods=['POST'])
@login_required
def api_card_tx_auto_categorize():
    data    = request.json or {}
    card_id = data.get('card_id')
    year    = data.get('year')
    month   = data.get('month')

    db = get_db()
    query  = "SELECT id, name FROM card_tx WHERE category_locked = 0 AND user_id = %s"
    params = [uid()]
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
            cur.execute("UPDATE card_tx SET category=%s WHERE id=%s AND user_id=%s", (hint, row['id'], uid()))
            cur.close()
            updated += 1
    db.commit()
    db.close()
    return jsonify({'ok': True, 'updated': updated})


# ── API: 주식 ────────────────────────────────────────────────
@app.route('/api/stocks', methods=['GET', 'POST'])
@login_required
def api_stocks():
    db = get_db()
    if request.method == 'GET':
        cur = db.cursor()
        cur.execute("""
        SELECT s.id, s.name, s.ticker, s.current_price, s.dividend, s.memo, s.category,
        COALESCE(SUM(CASE WHEN t.tx_type='buy'  THEN t.quantity ELSE 0 END), 0) AS buy_qty,
        COALESCE(SUM(CASE WHEN t.tx_type='sell' THEN t.quantity ELSE 0 END), 0) AS sell_qty,
        COALESCE(SUM(CASE WHEN t.tx_type='buy'  THEN t.price * t.quantity ELSE 0 END), 0) AS total_buy_amount,
        COALESCE(SUM(CASE WHEN t.tx_type='sell' THEN t.price * t.quantity ELSE 0 END), 0) AS total_sell_amount
        FROM stocks s
        LEFT JOIN stock_tx t ON t.stock_id = s.id
        WHERE s.user_id = %s
        GROUP BY s.id
        ORDER BY s.name
        """, (uid(),))
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
            r['avg_price']      = avg if qty > 0 else None
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
    "INSERT INTO stocks (name, ticker, current_price, dividend, memo, category, user_id) VALUES (%s,%s,%s,%s,%s,%s,%s)",
    (data.get('name'), data.get('ticker'),
    data.get('current_price', 0), data.get('dividend', 0), data.get('memo'), data.get('category'), uid())
    )
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/stocks/<int:rid>', methods=['PUT', 'DELETE'])
@login_required
def api_stocks_detail(rid):
    db = get_db()
    if request.method == 'PUT':
        data = request.json
        cur = db.cursor()
        cur.execute(
        "UPDATE stocks SET name=%s, ticker=%s, current_price=%s, dividend=%s, memo=%s, category=%s WHERE id=%s AND user_id=%s",
        (data.get('name'), data.get('ticker'),
        data.get('current_price', 0), data.get('dividend', 0), data.get('memo'), data.get('category'), rid, uid())
        )
        cur.close()
        db.commit()
        db.close()
        return jsonify({'ok': True})
    cur = db.cursor()
    cur.execute("DELETE FROM stock_tx WHERE stock_id = %s AND stock_id IN (SELECT id FROM stocks WHERE user_id = %s)", (rid, uid()))
    cur.close()
    cur = db.cursor()
    cur.execute("DELETE FROM stocks WHERE id = %s AND user_id = %s", (rid, uid()))
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True})


# ── API: 주식 구분 카테고리 ──────────────────────────────────
@app.route('/api/stock-categories', methods=['GET', 'POST'])
@login_required
def api_stock_categories():
    db = get_db()
    cur = db.cursor()
    if request.method == 'GET':
        cur.execute("SELECT id, name FROM stock_categories WHERE user_id = %s ORDER BY sort_order, id", (uid(),))
        rows = rows_to_list(cur.fetchall())
        cur.close(); db.close()
        return jsonify(rows)
    data = request.json
    cur.execute("SELECT COALESCE(MAX(sort_order),0)+1 FROM stock_categories WHERE user_id = %s", (uid(),))
    order = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO stock_categories (name, sort_order, user_id) VALUES (%s, %s, %s)",
        (data.get('name'), order, uid())
    )
    cur.close(); db.commit(); db.close()
    return jsonify({'ok': True}), 201

@app.route('/api/stock-categories/<int:cid>', methods=['DELETE'])
@login_required
def api_stock_category_delete(cid):
    db = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM stock_categories WHERE id=%s AND user_id=%s", (cid, uid()))
    cur.close(); db.commit(); db.close()
    return jsonify({'ok': True})


# ── API: 주식 거래내역 ────────────────────────────────────────
@app.route('/api/stock-tx', methods=['GET', 'POST'])
@login_required
def api_stock_tx():
    db = get_db()
    if request.method == 'GET':
        stock_id = request.args.get('stock_id')
        query  = "SELECT t.*, s.name, s.ticker FROM stock_tx t LEFT JOIN stocks s ON t.stock_id = s.id WHERE s.user_id = %s"
        params = [uid()]
        if stock_id:
            query += " AND t.stock_id = %s"
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
@login_required
def api_stock_tx_detail(rid):
    db = get_db()
    if request.method == 'PUT':
        data = request.json
        cur = db.cursor()
        cur.execute(
        "UPDATE stock_tx SET stock_id=%s, tx_date=%s, tx_type=%s, price=%s, quantity=%s, fee=%s, memo=%s WHERE id=%s AND stock_id IN (SELECT id FROM stocks WHERE user_id=%s)",
        (data.get('stock_id'), data.get('tx_date'), data.get('tx_type'),
        data.get('price', 0), data.get('quantity', 0), data.get('fee', 0), data.get('memo'), rid, uid())
        )
        cur.close()
        db.commit()
        db.close()
        return jsonify({'ok': True})
    cur = db.cursor()
    cur.execute("DELETE FROM stock_tx WHERE id = %s AND stock_id IN (SELECT id FROM stocks WHERE user_id=%s)", (rid, uid()))
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True})


# ── API: ETF ─────────────────────────────────────────────────
@app.route('/api/etf', methods=['GET', 'POST'])
@login_required
def api_etf():
    db = get_db()
    if request.method == 'GET':
        cur = db.cursor()
        cur.execute("""
        SELECT e.id, e.name, e.ticker, e.current_price, e.etf_type, e.memo,
          COALESCE(SUM(CASE WHEN t.tx_type='buy'  THEN t.quantity ELSE 0 END), 0) AS buy_qty,
          COALESCE(SUM(CASE WHEN t.tx_type='sell' THEN t.quantity ELSE 0 END), 0) AS sell_qty,
          COALESCE(SUM(CASE WHEN t.tx_type='buy'  THEN t.price * t.quantity ELSE 0 END), 0) AS total_buy_amount,
          COALESCE(SUM(CASE WHEN t.tx_type='sell' THEN t.price * t.quantity ELSE 0 END), 0) AS total_sell_amount
        FROM etf e
        LEFT JOIN etf_tx t ON t.etf_id = e.id
        WHERE e.user_id = %s
        GROUP BY e.id
        ORDER BY e.name
        """, (uid(),))
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
            r['avg_price']      = avg if qty > 0 else None
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
    "INSERT INTO etf (name, ticker, current_price, etf_type, memo, user_id) VALUES (%s,%s,%s,%s,%s,%s)",
    (data.get('name'), data.get('ticker'),
    data.get('current_price', 0), data.get('etf_type'), data.get('memo'), uid())
    )
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/etf/<int:rid>', methods=['PUT', 'DELETE'])
@login_required
def api_etf_detail(rid):
    db = get_db()
    if request.method == 'PUT':
        data = request.json
        cur = db.cursor()
        cur.execute(
        "UPDATE etf SET name=%s, ticker=%s, current_price=%s, etf_type=%s, memo=%s WHERE id=%s AND user_id=%s",
        (data.get('name'), data.get('ticker'),
        data.get('current_price', 0), data.get('etf_type'), data.get('memo'), rid, uid())
        )
        cur.close()
        db.commit()
        db.close()
        return jsonify({'ok': True})
    cur = db.cursor()
    cur.execute("DELETE FROM etf_tx WHERE etf_id = %s AND etf_id IN (SELECT id FROM etf WHERE user_id=%s)", (rid, uid()))
    cur.execute("DELETE FROM etf WHERE id = %s AND user_id=%s", (rid, uid()))
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True})


# ── API: ETF 거래내역 ──────────────────────────────────────────
@app.route('/api/etf-tx', methods=['GET', 'POST'])
@login_required
def api_etf_tx():
    db = get_db()
    if request.method == 'GET':
        etf_id = request.args.get('etf_id')
        query  = "SELECT t.*, e.name, e.ticker FROM etf_tx t LEFT JOIN etf e ON t.etf_id = e.id WHERE e.user_id = %s"
        params = [uid()]
        if etf_id:
            query += " AND t.etf_id = %s"
            params.append(etf_id)
        query += " ORDER BY t.tx_date DESC, t.id DESC"
        cur = db.cursor()
        cur.execute(query, params)
        rows = cur.fetchall()
        cur.close(); db.close()
        return jsonify(rows_to_list(rows))

    data = request.json
    cur = db.cursor()
    cur.execute(
    "INSERT INTO etf_tx (etf_id, tx_date, tx_type, price, quantity, fee, memo) VALUES (%s,%s,%s,%s,%s,%s,%s)",
    (data.get('etf_id'), data.get('tx_date'), data.get('tx_type'),
    data.get('price', 0), data.get('quantity', 0), data.get('fee', 0), data.get('memo'))
    )
    cur.close()
    db.commit(); db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/etf-tx/<int:rid>', methods=['PUT', 'DELETE'])
@login_required
def api_etf_tx_detail(rid):
    db = get_db()
    if request.method == 'DELETE':
        cur = db.cursor()
        cur.execute("DELETE FROM etf_tx WHERE id = %s AND etf_id IN (SELECT id FROM etf WHERE user_id=%s)", (rid, uid()))
        cur.close()
        db.commit(); db.close()
        return jsonify({'ok': True})
    data = request.json
    cur = db.cursor()
    cur.execute(
    "UPDATE etf_tx SET etf_id=%s, tx_date=%s, tx_type=%s, price=%s, quantity=%s, fee=%s, memo=%s WHERE id=%s AND etf_id IN (SELECT id FROM etf WHERE user_id=%s)",
    (data.get('etf_id'), data.get('tx_date'), data.get('tx_type'),
    data.get('price', 0), data.get('quantity', 0), data.get('fee', 0), data.get('memo'), rid, uid())
    )
    cur.close()
    db.commit(); db.close()
    return jsonify({'ok': True})


# ── API: 코인 ────────────────────────────────────────────────
@app.route('/api/crypto', methods=['GET', 'POST'])
@login_required
def api_crypto():
    db = get_db()
    if request.method == 'GET':
        cur = db.cursor()
        cur.execute("SELECT * FROM crypto WHERE user_id = %s ORDER BY name", (uid(),))
        rows = cur.fetchall()
        cur.close()
        db.close()
        return jsonify(rows_to_list(rows))

    data = request.json
    cur = db.cursor()
    cur.execute(
    "INSERT INTO crypto (name, symbol, exchange, buy_date, buy_price, quantity, current_price, memo, user_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
    (data.get('name'), data.get('symbol'), data.get('exchange'), data.get('buy_date'),
    data.get('buy_price', 0), data.get('quantity', 0),
    data.get('current_price', 0), data.get('memo'), uid())
    )
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/crypto/<int:rid>', methods=['PUT', 'DELETE'])
@login_required
def api_crypto_detail(rid):
    db = get_db()
    if request.method == 'PUT':
        data = request.json
        cur = db.cursor()
        cur.execute(
        "UPDATE crypto SET name=%s, symbol=%s, exchange=%s, buy_date=%s, buy_price=%s, quantity=%s, current_price=%s, memo=%s WHERE id=%s AND user_id=%s",
        (data.get('name'), data.get('symbol'), data.get('exchange'), data.get('buy_date'),
        data.get('buy_price', 0), data.get('quantity', 0),
        data.get('current_price', 0), data.get('memo'), rid, uid())
        )
        cur.close()
        db.commit()
        db.close()
        return jsonify({'ok': True})
    cur = db.cursor()
    cur.execute("DELETE FROM crypto WHERE id = %s AND user_id = %s", (rid, uid()))
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True})


# ── API: 공모주 ──────────────────────────────────────────────
@app.route('/api/ipo', methods=['GET', 'POST'])
@login_required
def api_ipo():
    db = get_db()
    if request.method == 'GET':
        cur = db.cursor()
        cur.execute("SELECT * FROM ipo WHERE user_id = %s ORDER BY listing_date DESC, id DESC", (uid(),))
        rows = cur.fetchall()
        cur.close()
        db.close()
        return jsonify(rows_to_list(rows))

    data = request.json
    cur = db.cursor()
    cur.execute(
        "INSERT INTO ipo (name, listing_date, ipo_price, quantity, realized_pnl, fee, memo, user_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (data.get('name'), data.get('listing_date'), data.get('ipo_price', 0),
         data.get('quantity', 0), data.get('realized_pnl', 0), data.get('fee', 0), data.get('memo'), uid())
    )
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/ipo/<int:rid>', methods=['PUT', 'DELETE'])
@login_required
def api_ipo_detail(rid):
    db = get_db()
    if request.method == 'PUT':
        data = request.json
        cur = db.cursor()
        cur.execute(
            "UPDATE ipo SET name=%s, listing_date=%s, ipo_price=%s, quantity=%s, realized_pnl=%s, fee=%s, memo=%s WHERE id=%s AND user_id=%s",
            (data.get('name'), data.get('listing_date'), data.get('ipo_price', 0),
             data.get('quantity', 0), data.get('realized_pnl', 0), data.get('fee', 0), data.get('memo'), rid, uid())
        )
        cur.close()
        db.commit()
        db.close()
        return jsonify({'ok': True})
    cur = db.cursor()
    cur.execute("DELETE FROM ipo WHERE id = %s AND user_id = %s", (rid, uid()))
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True})


# ── API: 현재가 업데이트 ─────────────────────────────────────
import time

def _is_krx_ticker(ticker: str) -> bool:
    """6자리 숫자면 국내 KRX 종목으로 판단"""
    return bool(re.match(r'^\d{6}$', ticker))


import sys

def _fetch_alphavantage_price(ticker: str) -> float | None:
    """Alpha Vantage API로 현재가 조회 (env: ALPHAVANTAGE_API_KEY 필요)"""
    api_key = os.environ.get('ALPHAVANTAGE_API_KEY', '').strip()
    if not api_key:
        return None
    # 국내 6자리 → .KS 접미사
    av_sym = (ticker + '.KSC') if _is_krx_ticker(ticker) else ticker
    try:
        res = http_req.get(
            'https://www.alphavantage.co/query',
            params={'function': 'GLOBAL_QUOTE', 'symbol': av_sym, 'apikey': api_key},
            timeout=10
        )
        if not res.ok:
            print(f'[price] alphavantage HTTP {res.status_code} for {av_sym}', file=sys.stderr)
            return None
        data = res.json().get('Global Quote', {})
        price_str = data.get('05. price', '')
        if price_str:
            return float(price_str)
        print(f'[price] alphavantage no price for {av_sym}: {res.text[:200]}', file=sys.stderr)
    except Exception as e:
        print(f'[price] alphavantage error {ticker}: {e}', file=sys.stderr)
    return None


def _fetch_stooq_price(ticker: str) -> float | None:
    """Stooq CSV 피드로 주식 현재가(종가) 조회"""
    try:
        stooq_sym = (ticker + '.kr') if _is_krx_ticker(ticker) else ticker
        res = http_req.get(
            f'https://stooq.com/q/l/?s={stooq_sym}&f=sd2t2ohlcv&h&e=csv',
            timeout=8,
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        print(f'[price] stooq {stooq_sym}: status={res.status_code} body={res.text[:100]}', file=sys.stderr)
        if not res.ok:
            return None
        lines = [line.strip() for line in res.text.strip().split('\n') if line.strip()]
        if len(lines) < 2:
            return None
        headers = [h.strip().lower() for h in lines[0].split(',')]
        parts = [p.strip() for p in lines[1].split(',')]
        if 'close' in headers:
            idx = headers.index('close')
            if idx < len(parts):
                close = parts[idx]
                if close and close not in ('N/D', '0', ''):
                    return float(close)
    except Exception as e:
        print(f'[price] stooq error {ticker}: {e}', file=sys.stderr)
    return None


def _fetch_yf_direct_price(ticker: str) -> float | None:
    """Yahoo Finance v8 API 직접 호출 (regularMarketPrice 또는 Close 종가 반영)"""
    try:
        yf_sym = (ticker + '.KS') if _is_krx_ticker(ticker) else ticker
        res = http_req.get(
            f'https://query2.finance.yahoo.com/v8/finance/chart/{yf_sym}',
            params={'interval': '1d', 'range': '5d'},
            headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'},
            timeout=8
        )
        print(f'[price] yf_direct {yf_sym}: status={res.status_code} body={res.text[:100]}', file=sys.stderr)
        if not res.ok:
            return None
        result = res.json().get('chart', {}).get('result', [])
        if result:
            market_price = result[0].get('meta', {}).get('regularMarketPrice')
            if market_price is not None:
                return float(market_price)
            closes = result[0].get('indicators', {}).get('quote', [{}])[0].get('close', [])
            closes = [c for c in closes if c is not None]
            if closes:
                return float(closes[-1])
    except Exception as e:
        print(f'[price] yf_direct error {ticker}: {e}', file=sys.stderr)
    return None


def _fetch_stock_price(ticker: str) -> float | None:
    """pykrx (국내) / yfinance (해외) 우선 시도 후 외부 HTTP API 순차 시도"""
    if _is_krx_ticker(ticker):
        # 1순위: pykrx
        if HAS_PYKRX:
            try:
                import datetime
                today_str = datetime.date.today().strftime("%Y%m%d")
                prev_str = (datetime.date.today() - datetime.timedelta(days=7)).strftime("%Y%m%d")
                df = krx_stock.get_market_ohlcv_by_date(prev_str, today_str, ticker)
                if not df.empty and '종가' in df.columns:
                    return float(df['종가'].iloc[-1])
            except Exception as e:
                print(f'[price] pykrx error {ticker}: {e}', file=sys.stderr)

        # 2순위: 네이버 모바일 주식 API (HTML 스크래핑보다 안정적)
        try:
            res = http_req.get(
                f"https://m.stock.naver.com/api/stock/{ticker}/basic",
                headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://m.stock.naver.com/'},
                timeout=5
            )
            if res.ok:
                data = res.json()
                price = data.get('closePrice') or data.get('currentPrice')
                if price:
                    return float(str(price).replace(',', ''))
        except Exception as e:
            print(f'[price] naver mobile API error {ticker}: {e}', file=sys.stderr)

        # 3순위: 네이버 금융 시세 API
        try:
            res = http_req.get(
                f"https://polling.finance.naver.com/api/realtime/domestic/stock/{ticker}",
                headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.naver.com/'},
                timeout=5
            )
            if res.ok:
                data = res.json()
                price = (data.get('datas') or [{}])[0].get('closePrice') or \
                        (data.get('datas') or [{}])[0].get('currentPrice')
                if price:
                    return float(str(price).replace(',', ''))
        except Exception as e:
            print(f'[price] naver polling API error {ticker}: {e}', file=sys.stderr)

        # 4순위: Yahoo Finance KS/KQ 심볼
        try:
            for suffix in ['.KS', '.KQ']:
                sym = ticker + suffix
                res = http_req.get(
                    f'https://query2.finance.yahoo.com/v8/finance/chart/{sym}',
                    params={'interval': '1d', 'range': '5d'},
                    headers={'User-Agent': 'Mozilla/5.0'},
                    timeout=5
                )
                if res.ok:
                    result = res.json().get('chart', {}).get('result', [])
                    if result:
                        closes = result[0].get('indicators', {}).get('quote', [{}])[0].get('close', [])
                        closes = [c for c in closes if c is not None]
                        if closes:
                            return float(closes[-1])
        except Exception as e:
            print(f'[price] yahoo KS/KQ error {ticker}: {e}', file=sys.stderr)

    else:
        if HAS_YFINANCE:
            try:
                t = yf.Ticker(ticker)
                hist = t.history(period="5d")
                if not hist.empty and 'Close' in hist.columns:
                    return float(hist['Close'].iloc[-1])
            except Exception as e:
                print(f'[price] yfinance error {ticker}: {e}', file=sys.stderr)

    price = _fetch_alphavantage_price(ticker)
    if price:
        return price
    price = _fetch_stooq_price(ticker)
    if price:
        return price
    price = _fetch_yf_direct_price(ticker)
    if price:
        return price
    return None



def _fetch_crypto_prices(symbols: list[str]) -> dict[str, float]:
    """업비트(Upbit) API 우선 조회 후, 실패 시 CoinGecko로 KRW 현재가 조회. {symbol_upper: price}"""
    if not symbols:
        return {}
    result = {}

    # 1. 업비트 API 시도 (예: BTC -> KRW-BTC)
    for sym in symbols:
        sym_upper = sym.upper()
        try:
            market = f"KRW-{sym_upper}"
            res = http_req.get(f"https://api.upbit.com/v1/ticker?markets={market}", timeout=5, headers={'User-Agent': 'Mozilla/5.0'})
            if res.ok:
                data = res.json()
                if data and isinstance(data, list) and len(data) > 0:
                    trade_price = data[0].get('trade_price')
                    if trade_price:
                        result[sym_upper] = float(trade_price)
                        continue
        except Exception as e:
            print(f'[price] upbit error {sym}: {e}', file=sys.stderr)

    # 2. 업비트에서 조회 실패한 심볼에 대해 CoinGecko 시도
    remaining = [sym for sym in symbols if sym.upper() not in result]
    for sym in remaining:
        sym_upper = sym.upper()
        try:
            # /search 로 심볼 → coin id 획득 (전체 목록 다운로드 대신)
            search_res = http_req.get(
                'https://api.coingecko.com/api/v3/search',
                params={'query': sym},
                timeout=8
            )
            if not search_res.ok:
                continue
            coins = search_res.json().get('coins', [])
            coin_id = None
            for coin in coins:
                if coin.get('symbol', '').upper() == sym_upper:
                    coin_id = coin['id']
                    break
            if not coin_id:
                continue

            price_res = http_req.get(
                'https://api.coingecko.com/api/v3/simple/price',
                params={'ids': coin_id, 'vs_currencies': 'krw'},
                timeout=8
            )
            if not price_res.ok:
                continue
            p = price_res.json().get(coin_id, {}).get('krw')
            if p:
                result[sym_upper] = float(p)
        except Exception:
            continue
    return result


@app.route('/api/price-update', methods=['POST'])
@login_required
def api_price_update():
    """등록된 모든 종목(주식/ETF/코인)의 현재가를 외부 API로 조회 후 DB 업데이트"""
    import traceback
    db = get_db()
    results = {'stocks': [], 'etf': [], 'crypto': [], 'errors': []}

    try:
        # ── 주식 ──
        cur = db.cursor()
        cur.execute("SELECT id, name, ticker FROM stocks WHERE ticker IS NOT NULL AND ticker != '' AND user_id = %s", (uid(),))
        stock_rows = cur.fetchall()
        cur.close()

        for row in stock_rows:
            sid, name, ticker = row['id'], row['name'], row['ticker']
            try:
                price = _fetch_stock_price(ticker)
            except Exception as e:
                price = None
                results['errors'].append(f"주식 [{name}({ticker})]: {e}")
            if price:
                cur = db.cursor()
                cur.execute("UPDATE stocks SET current_price = %s WHERE id = %s AND user_id = %s", (price, sid, uid()))
                cur.close()
                results['stocks'].append({'id': sid, 'name': name, 'ticker': ticker, 'price': price, 'ok': True})
            else:
                if not any(f"주식 [{name}({ticker})]" in e for e in results['errors']):
                    results['errors'].append(f"주식 [{name}({ticker})]: 가격 조회 실패")
                results['stocks'].append({'id': sid, 'name': name, 'ticker': ticker, 'price': None, 'ok': False})

        # ── ETF ──
        cur = db.cursor()
        cur.execute("SELECT id, name, ticker FROM etf WHERE ticker IS NOT NULL AND ticker != '' AND user_id = %s", (uid(),))
        etf_rows = cur.fetchall()
        cur.close()

        for row in etf_rows:
            eid, name, ticker = row['id'], row['name'], row['ticker']
            try:
                price = _fetch_stock_price(ticker)
            except Exception as e:
                price = None
                results['errors'].append(f"ETF [{name}({ticker})]: {e}")
            if price:
                cur = db.cursor()
                cur.execute("UPDATE etf SET current_price = %s WHERE id = %s AND user_id = %s", (price, eid, uid()))
                cur.close()
                results['etf'].append({'id': eid, 'name': name, 'ticker': ticker, 'price': price, 'ok': True})
            else:
                if not any(f"ETF [{name}({ticker})]" in e for e in results['errors']):
                    results['errors'].append(f"ETF [{name}({ticker})]: 가격 조회 실패")
                results['etf'].append({'id': eid, 'name': name, 'ticker': ticker, 'price': None, 'ok': False})

        # ── 코인 ──
        cur = db.cursor()
        cur.execute("SELECT id, name, symbol FROM crypto WHERE symbol IS NOT NULL AND symbol != '' AND user_id = %s", (uid(),))
        crypto_rows = cur.fetchall()
        cur.close()

        if crypto_rows:
            symbols = [row['symbol'] for row in crypto_rows]
            try:
                cg_prices = _fetch_crypto_prices(symbols)
            except Exception as e:
                cg_prices = {}
                results['errors'].append(f"코인 가격 조회 오류: {e}")

            for row in crypto_rows:
                cid, name, symbol = row['id'], row['name'], row['symbol']
                price = cg_prices.get(symbol.upper())
                if price:
                    cur = db.cursor()
                    cur.execute("UPDATE crypto SET current_price = %s WHERE id = %s AND user_id = %s", (price, cid, uid()))
                    cur.close()
                    results['crypto'].append({'id': cid, 'name': name, 'symbol': symbol, 'price': price, 'ok': True})
                else:
                    results['errors'].append(f"코인 [{name}({symbol})]: 가격 조회 실패")
                    results['crypto'].append({'id': cid, 'name': name, 'symbol': symbol, 'price': None, 'ok': False})

        db.commit()
    except Exception as e:
        results['errors'].append(f"서버 오류: {traceback.format_exc()}")
    finally:
        db.close()

    return jsonify(results)


@app.route('/api/price-test')
@login_required
def api_price_test():
    """주식 가격 소스별 진단 (예: /api/price-test?ticker=005930)"""
    ticker = request.args.get('ticker', '005930')
    av_key = os.environ.get('ALPHAVANTAGE_API_KEY', '')
    result = {'ticker': ticker, 'av_key_set': bool(av_key), 'sources': {}}

    # 1. Alpha Vantage
    try:
        av_sym = (ticker + '.KSC') if _is_krx_ticker(ticker) else ticker
        r = http_req.get('https://www.alphavantage.co/query',
            params={'function': 'GLOBAL_QUOTE', 'symbol': av_sym, 'apikey': av_key or 'demo'},
            timeout=10)
        result['sources']['alphavantage'] = {'status': r.status_code, 'body': r.text[:300]}
    except Exception as e:
        result['sources']['alphavantage'] = {'error': str(e)}

    # 2. Stooq
    try:
        stooq_sym = (ticker + '.kr') if _is_krx_ticker(ticker) else ticker
        r = http_req.get(f'https://stooq.com/q/l/?s={stooq_sym}&f=sd2t2ohlcv&h&e=csv',
            timeout=8, headers={'User-Agent': 'Mozilla/5.0'})
        result['sources']['stooq'] = {'status': r.status_code, 'body': r.text[:300]}
    except Exception as e:
        result['sources']['stooq'] = {'error': str(e)}

    # 3. Yahoo Finance 직접
    try:
        yf_sym = (ticker + '.KS') if _is_krx_ticker(ticker) else ticker
        r = http_req.get(f'https://query2.finance.yahoo.com/v8/finance/chart/{yf_sym}',
            params={'interval': '1d', 'range': '5d'},
            headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'},
            timeout=8)
        result['sources']['yahoo'] = {'status': r.status_code, 'body': r.text[:300]}
    except Exception as e:
        result['sources']['yahoo'] = {'error': str(e)}

    return jsonify(result)


# ── API: USD/KRW 환율 ────────────────────────────────────────
_exchange_rate_cache = {'rate': 1380.0, 'last_updated': 0}

def get_current_exchange_rate():
    import time
    now = time.time()
    # 1시간 동안 캐시 유지
    if now - _exchange_rate_cache['last_updated'] < 3600:
        return _exchange_rate_cache['rate']

    try:
        r = http_req.get(
            'https://query2.finance.yahoo.com/v8/finance/chart/USDKRW=X',
            params={'interval': '1d', 'range': '5d'},
            headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'},
            timeout=3
        )
        if r.ok:
            result = r.json().get('chart', {}).get('result', [])
            if result:
                closes = result[0].get('indicators', {}).get('quote', [{}])[0].get('close', [])
                closes = [c for c in closes if c is not None]
                if closes:
                    rate = round(closes[-1], 2)
                    _exchange_rate_cache['rate'] = rate
                    _exchange_rate_cache['last_updated'] = now
                    return rate
    except Exception:
        pass
    
    # 실패 시 캐시 수명을 살짝 늘려(5분) 잦은 재시도 방지
    _exchange_rate_cache['last_updated'] = now - 3300 
    return _exchange_rate_cache['rate']

def is_foreign_ticker(ticker):
    return bool(ticker) and not bool(re.match(r'^\d{6}$', str(ticker)))

def get_stocks_total_value(db, ex_rate, user_id=None):
    cur = db.cursor()
    where = "WHERE s.user_id = %s" if user_id else ""
    params = (user_id,) if user_id else ()
    cur.execute(f"""
    SELECT s.ticker, s.current_price,
    COALESCE(SUM(CASE WHEN t.tx_type='buy'  THEN t.quantity ELSE 0 END), 0) AS buy_qty,
    COALESCE(SUM(CASE WHEN t.tx_type='sell' THEN t.quantity ELSE 0 END), 0) AS sell_qty
    FROM stocks s
    LEFT JOIN stock_tx t ON t.stock_id = s.id
    {where}
    GROUP BY s.id
    """, params)
    rows = cur.fetchall()
    cur.close()
    total = 0.0
    for r in rows:
        qty = r['buy_qty'] - r['sell_qty']
        eval_amt = round(qty * r['current_price'])
        if is_foreign_ticker(r['ticker']):
            total += eval_amt * ex_rate
        else:
            total += eval_amt
    return float(total)

def get_etf_total_value(db, ex_rate, user_id=None):
    cur = db.cursor()
    where = "WHERE e.user_id = %s" if user_id else ""
    params = (user_id,) if user_id else ()
    cur.execute(f"""
    SELECT e.ticker, e.current_price,
    COALESCE(SUM(CASE WHEN t.tx_type='buy'  THEN t.quantity ELSE 0 END), 0) AS buy_qty,
    COALESCE(SUM(CASE WHEN t.tx_type='sell' THEN t.quantity ELSE 0 END), 0) AS sell_qty
    FROM etf e
    LEFT JOIN etf_tx t ON t.etf_id = e.id
    {where}
    GROUP BY e.id
    """, params)
    rows = cur.fetchall()
    cur.close()
    total = 0.0
    for r in rows:
        qty = r['buy_qty'] - r['sell_qty']
        eval_amt = round(qty * r['current_price'])
        if is_foreign_ticker(r['ticker']):
            total += eval_amt * ex_rate
        else:
            total += eval_amt
    return float(total)

def get_stocks_total_and_cost(db, ex_rate, user_id=None):
    cur = db.cursor()
    where = "WHERE s.user_id = %s" if user_id else ""
    params = (user_id,) if user_id else ()
    cur.execute(f"""
    SELECT s.ticker, s.current_price,
    COALESCE(SUM(CASE WHEN t.tx_type='buy'  THEN t.quantity ELSE 0 END), 0) AS buy_qty,
    COALESCE(SUM(CASE WHEN t.tx_type='sell' THEN t.quantity ELSE 0 END), 0) AS sell_qty,
    COALESCE(SUM(CASE WHEN t.tx_type='buy'  THEN t.price * t.quantity ELSE 0 END), 0) AS total_buy_amt
    FROM stocks s
    LEFT JOIN stock_tx t ON t.stock_id = s.id
    {where}
    GROUP BY s.id
    """, params)
    rows = cur.fetchall()
    cur.close()
    val = 0.0
    cost = 0.0
    for r in rows:
        qty = r['buy_qty'] - r['sell_qty']
        avg = (r['total_buy_amt'] / r['buy_qty']) if r['buy_qty'] > 0 else 0
        eval_amt = round(qty * r['current_price'])
        cost_amt = round(qty * avg)
        if is_foreign_ticker(r['ticker']):
            val += eval_amt * ex_rate
            cost += cost_amt * ex_rate
        else:
            val += eval_amt
            cost += cost_amt
    return (float(val), float(cost))

def get_etf_total_and_cost(db, ex_rate, user_id=None):
    cur = db.cursor()
    where = "WHERE e.user_id = %s" if user_id else ""
    params = (user_id,) if user_id else ()
    cur.execute(f"""
    SELECT e.ticker, e.current_price,
    COALESCE(SUM(CASE WHEN t.tx_type='buy'  THEN t.quantity ELSE 0 END), 0) AS buy_qty,
    COALESCE(SUM(CASE WHEN t.tx_type='sell' THEN t.quantity ELSE 0 END), 0) AS sell_qty,
    COALESCE(SUM(CASE WHEN t.tx_type='buy'  THEN t.price * t.quantity ELSE 0 END), 0) AS total_buy_amt
    FROM etf e
    LEFT JOIN etf_tx t ON t.etf_id = e.id
    {where}
    GROUP BY e.id
    """, params)
    rows = cur.fetchall()
    cur.close()
    val = 0.0
    cost = 0.0
    for r in rows:
        qty = r['buy_qty'] - r['sell_qty']
        avg = (r['total_buy_amt'] / r['buy_qty']) if r['buy_qty'] > 0 else 0
        eval_amt = round(qty * r['current_price'])
        cost_amt = round(qty * avg)
        if is_foreign_ticker(r['ticker']):
            val += eval_amt * ex_rate
            cost += cost_amt * ex_rate
        else:
            val += eval_amt
            cost += cost_amt
    return (float(val), float(cost))

@app.route('/api/exchange-rate')
@login_required
def api_exchange_rate():
    """Yahoo Finance에서 USD/KRW 환율 조회. 실패 시 1380 반환"""
    return jsonify({'rate': get_current_exchange_rate()})


# ── API: 거주지 ──────────────────────────────────────────────
@app.route('/api/residence', methods=['GET', 'POST'])
@login_required
def api_residence():
    db = get_db()
    if request.method == 'GET':
        cur = db.cursor()
        cur.execute("SELECT * FROM residence WHERE user_id = %s ORDER BY id DESC", (uid(),))
        rows = cur.fetchall()
        cur.close()
        db.close()
        return jsonify(rows_to_list(rows))

    data = request.json
    cur = db.cursor()
    cur.execute(
    "INSERT INTO residence (address, deposit, monthly_rent, maintenance, start_date, end_date, user_id) VALUES (%s,%s,%s,%s,%s,%s,%s)",
    (data.get('address'), data.get('deposit', 0), data.get('monthly_rent', 0),
    data.get('maintenance', 0), data.get('start_date'), data.get('end_date'), uid())
    )
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/residence/<int:rid>', methods=['PUT', 'DELETE'])
@login_required
def api_residence_detail(rid):
    db = get_db()
    if request.method == 'PUT':
        data = request.json
        cur = db.cursor()
        cur.execute(
        "UPDATE residence SET address=%s, deposit=%s, monthly_rent=%s, maintenance=%s, start_date=%s, end_date=%s WHERE id=%s AND user_id=%s",
        (data.get('address'), data.get('deposit', 0), data.get('monthly_rent', 0),
        data.get('maintenance', 0), data.get('start_date'), data.get('end_date'), rid, uid())
        )
        cur.close()
        db.commit()
        db.close()
        return jsonify({'ok': True})
    cur = db.cursor()
    cur.execute("DELETE FROM residence WHERE id = %s AND user_id = %s", (rid, uid()))
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
@login_required
def api_real_estate():
    db = get_db()
    if request.method == 'GET':
        cur = db.cursor()
        cur.execute("SELECT * FROM real_estate WHERE user_id = %s ORDER BY name", (uid(),))
        rows = cur.fetchall()
        cur.close()
        result = _re_enrich(db, rows)
        db.close()
        return jsonify(result)

    data = request.json
    cur = db.cursor()
    cur.execute(
    "INSERT INTO real_estate (name, re_type, purchase_date, purchase_price, current_price, memo, user_id) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
    (data.get('name'), data.get('re_type'), data.get('purchase_date'),
    data.get('purchase_price', 0), data.get('current_price', 0), data.get('memo'), uid())
    )
    new_id = cur.fetchone()[0]
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True, 'id': new_id}), 201


@app.route('/api/real-estate/<int:rid>', methods=['PUT', 'DELETE'])
@login_required
def api_real_estate_detail(rid):
    db = get_db()
    if request.method == 'PUT':
        data = request.json
        cur = db.cursor()
        cur.execute(
        "UPDATE real_estate SET name=%s, re_type=%s, purchase_date=%s, purchase_price=%s, current_price=%s, memo=%s WHERE id=%s AND user_id=%s",
        (data.get('name'), data.get('re_type'), data.get('purchase_date'),
        data.get('purchase_price', 0), data.get('current_price', 0), data.get('memo'), rid, uid())
        )
        cur.close()
        db.commit()
        db.close()
        return jsonify({'ok': True})
    cur = db.cursor()
    cur.execute("DELETE FROM real_estate WHERE id = %s AND user_id = %s", (rid, uid()))
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True})


@app.route('/api/re-summary')
@login_required
def api_re_summary():
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM real_estate WHERE user_id = %s", (uid(),))
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
@login_required
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
    AND r.user_id = %s
    ORDER BY c.end_date
    """, (uid(),))
    rows = cur.fetchall()
    cur.close()
    db.close()
    return jsonify(rows_to_list(rows))


@app.route('/api/tenant-contracts', methods=['GET', 'POST'])
@login_required
def api_tenant_contracts():
    db = get_db()
    if request.method == 'GET':
        rid = request.args.get('real_estate_id')
        cur = db.cursor()
        cur.execute(
        "SELECT tc.* FROM tenant_contracts tc JOIN real_estate r ON tc.real_estate_id = r.id WHERE tc.real_estate_id=%s AND r.user_id=%s ORDER BY tc.end_date DESC", (rid, uid())
        )
        rows = cur.fetchall()
        cur.close()
        db.close()
        return jsonify(rows_to_list(rows))
    d = request.json or {}
    cur = db.cursor()
    cur.execute(
    "INSERT INTO tenant_contracts (real_estate_id, contract_type, deposit, monthly_rent, start_date, end_date, memo, user_id)"
    " VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
    (d.get('real_estate_id'), d.get('contract_type'), d.get('deposit', 0),
    d.get('monthly_rent', 0), d.get('start_date'), d.get('end_date'), d.get('memo'), uid())
    )
    cur.close()
    db.commit(); db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/tenant-contracts/<int:rid>', methods=['PUT', 'DELETE'])
@login_required
def api_tenant_contracts_detail(rid):
    db = get_db()
    if request.method == 'DELETE':
        cur = db.cursor()
        cur.execute("DELETE FROM tenant_contracts WHERE id=%s AND user_id=%s", (rid, uid()))
        cur.close()
        db.commit(); db.close()
        return jsonify({'ok': True})
    d = request.json or {}
    cur = db.cursor()
    cur.execute(
    "UPDATE tenant_contracts SET contract_type=%s, deposit=%s, monthly_rent=%s, start_date=%s, end_date=%s, memo=%s WHERE id=%s AND user_id=%s",
    (d.get('contract_type'), d.get('deposit', 0), d.get('monthly_rent', 0),
    d.get('start_date'), d.get('end_date'), d.get('memo'), rid, uid())
    )
    cur.close()
    db.commit(); db.close()
    return jsonify({'ok': True})


@app.route('/api/property-costs', methods=['GET', 'POST'])
@login_required
def api_property_costs():
    db = get_db()
    if request.method == 'GET':
        rid = request.args.get('real_estate_id')
        cur = db.cursor()
        cur.execute(
        "SELECT pc.* FROM property_costs pc JOIN real_estate r ON pc.real_estate_id = r.id WHERE pc.real_estate_id=%s AND r.user_id=%s ORDER BY pc.date DESC", (rid, uid())
        )
        rows = cur.fetchall()
        cur.close()
        db.close()
        return jsonify(rows_to_list(rows))
    d = request.json or {}
    cur = db.cursor()
    cur.execute(
    "INSERT INTO property_costs (real_estate_id, cost_type, name, amount, date, memo, user_id) VALUES (%s,%s,%s,%s,%s,%s,%s)",
    (d.get('real_estate_id'), d.get('cost_type'), d.get('name'),
    d.get('amount', 0), d.get('date'), d.get('memo'), uid())
    )
    cur.close()
    db.commit(); db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/property-costs/<int:rid>', methods=['PUT', 'DELETE'])
@login_required
def api_property_costs_detail(rid):
    db = get_db()
    if request.method == 'DELETE':
        cur = db.cursor()
        cur.execute("DELETE FROM property_costs WHERE id=%s AND user_id=%s", (rid, uid()))
        cur.close()
        db.commit(); db.close()
        return jsonify({'ok': True})
    d = request.json or {}
    cur = db.cursor()
    cur.execute(
    "UPDATE property_costs SET cost_type=%s, name=%s, amount=%s, date=%s, memo=%s WHERE id=%s AND user_id=%s",
    (d.get('cost_type'), d.get('name'), d.get('amount', 0),
    d.get('date'), d.get('memo'), rid, uid())
    )
    cur.close()
    db.commit(); db.close()
    return jsonify({'ok': True})


# ── API: 앱 설정 ──────────────────────────────────────────────
@app.route('/api/settings/<key>', methods=['GET', 'PUT'])
@login_required
def api_settings(key):
    db = get_db()
    cur = db.cursor()
    if request.method == 'GET':
        cur.execute("SELECT value FROM app_settings WHERE key=%s AND user_id=%s", (key, uid()))
        row = cur.fetchone()
        cur.close(); db.close()
        return jsonify({'key': key, 'value': row['value'] if row else None})
    value = (request.json or {}).get('value')
    cur.execute("DELETE FROM app_settings WHERE key=%s AND user_id=%s", (key, uid()))
    cur.execute(
        "INSERT INTO app_settings (key, value, user_id) VALUES (%s,%s,%s)",
        (key, value, uid())
    )
    cur.close()
    db.commit(); db.close()
    return jsonify({'ok': True})


# ── API: 매도 부동산 ──────────────────────────────────────────
@app.route('/api/real-estate/<int:rid>/sell', methods=['POST'])
@login_required
def api_real_estate_sell(rid):
    d = request.json or {}
    db = get_db()
    cur = db.cursor()

    cur.execute("SELECT * FROM real_estate WHERE id=%s AND user_id=%s", (rid, uid()))
    re = cur.fetchone()
    cur.close()
    if not re:
        db.close()
        return jsonify({'error': '부동산을 찾을 수 없습니다'}), 404

    # 취득비용 합계
    cur = db.cursor()
    cur.execute(
        "SELECT COALESCE(SUM(amount),0) as v FROM property_costs "
        "WHERE real_estate_id=%s AND cost_type='취득비용'", (rid,)
    )
    acq_cost = cur.fetchone()['v']
    cur.close()

    # 현재 보증금
    cur = db.cursor()
    cur.execute(
        "SELECT COALESCE(deposit,0) as v FROM tenant_contracts "
        "WHERE real_estate_id=%s ORDER BY end_date DESC LIMIT 1", (rid,)
    )
    row = cur.fetchone()
    cur.close()
    deposit = row['v'] if row else 0

    purchase_price = re['purchase_price']
    sell_price   = int(d.get('sell_price', 0))
    tax          = int(d.get('tax', 0))
    other_costs  = int(d.get('other_costs', 0))
    real_inv     = purchase_price - deposit + acq_cost
    profit       = sell_price - purchase_price - tax - other_costs
    roi          = round(profit / real_inv * 100, 1) if real_inv > 0 else 0.0

    from datetime import date
    cur = db.cursor()
    cur.execute(
        "INSERT INTO sold_real_estate "
        "(name, re_type, purchase_date, purchase_price, real_inv, sell_date, sell_price, tax, other_costs, profit, roi, memo, created_at, user_id) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (re['name'], re['re_type'], re['purchase_date'], purchase_price, real_inv,
         d.get('sell_date'), sell_price, tax, other_costs, profit, roi,
         d.get('memo'), str(date.today()), uid())
    )
    cur.close()

    # 원본 데이터 삭제 (관련 레코드 먼저; real_estate_payments는 CASCADE)
    cur = db.cursor()
    cur.execute("DELETE FROM tenant_contracts WHERE real_estate_id=%s AND user_id=%s", (rid, uid()))
    cur.execute("DELETE FROM property_costs WHERE real_estate_id=%s AND user_id=%s", (rid, uid()))
    cur.execute("DELETE FROM real_estate WHERE id=%s AND user_id=%s", (rid, uid()))
    cur.close()

    db.commit(); db.close()
    return jsonify({'ok': True, 'profit': profit, 'roi': roi}), 201


@app.route('/api/sold-real-estate', methods=['GET'])
@login_required
def api_sold_real_estate():
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM sold_real_estate WHERE user_id = %s ORDER BY sell_date DESC", (uid(),))
    rows = cur.fetchall()
    cur.close(); db.close()
    return jsonify(rows_to_list(rows))


@app.route('/api/sold-real-estate/<int:sid>', methods=['DELETE'])
@login_required
def api_sold_real_estate_detail(sid):
    db = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM sold_real_estate WHERE id=%s AND user_id=%s", (sid, uid()))
    cur.close()
    db.commit(); db.close()
    return jsonify({'ok': True})


# ── API: 부동산 거래 단계 (계약금/중도금/잔금) ────────────────────
@app.route('/api/real-estate-payments', methods=['GET', 'POST'])
@login_required
def api_re_payments():
    db = get_db()
    if request.method == 'GET':
        rid = request.args.get('real_estate_id')
        cur = db.cursor()
        if rid:
            cur.execute(
                "SELECT p.* FROM real_estate_payments p JOIN real_estate r ON p.real_estate_id=r.id WHERE p.real_estate_id=%s AND r.user_id=%s ORDER BY p.scheduled_date, p.id",
                (rid, uid())
            )
        else:
            cur.execute(
                "SELECT p.*, r.name AS re_name FROM real_estate_payments p "
                "LEFT JOIN real_estate r ON p.real_estate_id=r.id "
                "WHERE r.user_id=%s ORDER BY p.scheduled_date, p.id",
                (uid(),)
            )
        rows = cur.fetchall()
        cur.close(); db.close()
        return jsonify(rows_to_list(rows))

    d = request.json
    cur = db.cursor()
    cur.execute(
        "INSERT INTO real_estate_payments (real_estate_id, direction, payment_type, scheduled_date, actual_date, amount, memo, user_id) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (d.get('real_estate_id'), d.get('direction'), d.get('payment_type'),
         d.get('scheduled_date') or None, d.get('actual_date') or None,
         d.get('amount', 0), d.get('memo'), uid())
    )
    new_id = cur.fetchone()[0]
    cur.close()
    db.commit(); db.close()
    return jsonify({'id': new_id}), 201


@app.route('/api/real-estate-payments/<int:pid>', methods=['PUT', 'DELETE'])
@login_required
def api_re_payment_detail(pid):
    db = get_db()
    if request.method == 'DELETE':
        cur = db.cursor()
        cur.execute("DELETE FROM real_estate_payments WHERE id=%s AND user_id=%s", (pid, uid()))
        cur.close()
        db.commit(); db.close()
        return jsonify({'ok': True})

    d = request.json
    cur = db.cursor()
    cur.execute(
        "UPDATE real_estate_payments SET direction=%s, payment_type=%s, scheduled_date=%s, "
        "actual_date=%s, amount=%s, memo=%s WHERE id=%s AND user_id=%s",
        (d.get('direction'), d.get('payment_type'),
         d.get('scheduled_date') or None, d.get('actual_date') or None,
         d.get('amount', 0), d.get('memo'), pid, uid())
    )
    cur.close()
    db.commit(); db.close()
    return jsonify({'ok': True})


@app.route('/api/real-estate-payments/active')
@login_required
def api_re_payments_active():
    """진행 중인 거래 단계 요약 (대시보드용)"""
    db = get_db()
    cur = db.cursor()
    # 아직 완료되지 않은 거래 단계가 있는 부동산 목록
    cur.execute("""
        SELECT p.*, r.name AS re_name, r.current_price
        FROM real_estate_payments p
        LEFT JOIN real_estate r ON p.real_estate_id = r.id
        WHERE p.real_estate_id IS NOT NULL AND r.user_id = %s
        ORDER BY p.real_estate_id, p.scheduled_date, p.id
    """, (uid(),))
    rows = cur.fetchall()
    cur.close(); db.close()
    return jsonify(rows_to_list(rows))


# ── API: 대출 ────────────────────────────────────────────────
@app.route('/api/loans', methods=['GET', 'POST'])
@login_required
def api_loans():
    db = get_db()
    if request.method == 'GET':
        cur = db.cursor()
        cur.execute("SELECT * FROM loans WHERE user_id = %s ORDER BY name", (uid(),))
        rows = cur.fetchall()
        cur.close()
        db.close()
        return jsonify(rows_to_list(rows))

    data = request.json
    cur = db.cursor()
    cur.execute(
    "INSERT INTO loans (name, institution, principal, remaining, monthly_payment, interest_rate, loan_date, end_date, memo, user_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
    (data.get('name'), data.get('institution'), data.get('principal', 0),
    data.get('remaining', 0), data.get('monthly_payment', 0),
    data.get('interest_rate', 0), data.get('loan_date'), data.get('end_date'), data.get('memo'), uid())
    )
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/loans/<int:rid>', methods=['PUT', 'DELETE'])
@login_required
def api_loans_detail(rid):
    db = get_db()
    if request.method == 'PUT':
        data = request.json
        cur = db.cursor()
        cur.execute(
        "UPDATE loans SET name=%s, institution=%s, principal=%s, remaining=%s, monthly_payment=%s, interest_rate=%s, loan_date=%s, end_date=%s, memo=%s WHERE id=%s AND user_id=%s",
        (data.get('name'), data.get('institution'), data.get('principal', 0),
        data.get('remaining', 0), data.get('monthly_payment', 0),
        data.get('interest_rate', 0), data.get('loan_date'), data.get('end_date'), data.get('memo'), rid, uid())
        )
        cur.close()
        db.commit()
        db.close()
        return jsonify({'ok': True})
    cur = db.cursor()
    cur.execute("DELETE FROM loans WHERE id = %s AND user_id = %s", (rid, uid()))
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True})


# ── API: 연금 ────────────────────────────────────────────────
@app.route('/api/pension', methods=['GET', 'POST'])
@login_required
def api_pension():
    db = get_db()
    if request.method == 'GET':
        cur = db.cursor()
        cur.execute("SELECT * FROM pension WHERE user_id = %s ORDER BY pension_type, name", (uid(),))
        rows = cur.fetchall()
        cur.close()
        db.close()
        return jsonify(rows_to_list(rows))

    data = request.json
    cur = db.cursor()
    cur.execute(
    "INSERT INTO pension (pension_type, name, institution, monthly_payment, accumulated, return_rate, memo, user_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
    (data.get('pension_type'), data.get('name'), data.get('institution'),
    data.get('monthly_payment', 0), data.get('accumulated', 0),
    data.get('return_rate', 0), data.get('memo'), uid())
    )
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/pension/<int:rid>', methods=['PUT', 'DELETE'])
@login_required
def api_pension_detail(rid):
    db = get_db()
    if request.method == 'PUT':
        data = request.json
        cur = db.cursor()
        cur.execute(
        "UPDATE pension SET pension_type=%s, name=%s, institution=%s, monthly_payment=%s, accumulated=%s, return_rate=%s, memo=%s WHERE id=%s AND user_id=%s",
        (data.get('pension_type'), data.get('name'), data.get('institution'),
        data.get('monthly_payment', 0), data.get('accumulated', 0),
        data.get('return_rate', 0), data.get('memo'), rid, uid())
        )
        cur.close()
        db.commit()
        db.close()
        return jsonify({'ok': True})
    cur = db.cursor()
    cur.execute("DELETE FROM pension WHERE id = %s AND user_id = %s", (rid, uid()))
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True})


# ── API: 목표저축 ────────────────────────────────────────────
@app.route('/api/goals', methods=['GET', 'POST'])
@login_required
def api_goals():
    db = get_db()
    if request.method == 'GET':
        cur = db.cursor()
        cur.execute("SELECT * FROM goals WHERE name != '자본주의테크트리' AND user_id = %s ORDER BY target_date", (uid(),))
        rows = cur.fetchall()
        cur.close()
        db.close()
        return jsonify(rows_to_list(rows))

    data = request.json
    cur = db.cursor()
    cur.execute(
    "INSERT INTO goals (name, target_amount, current_amount, monthly_saving, target_date, memo, user_id) VALUES (%s,%s,%s,%s,%s,%s,%s)",
    (data.get('name'), data.get('target_amount', 0), data.get('current_amount', 0),
    data.get('monthly_saving', 0), data.get('target_date'), data.get('memo'), uid())
    )
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/goals/<int:rid>', methods=['PUT', 'DELETE'])
@login_required
def api_goals_detail(rid):
    db = get_db()
    if request.method == 'PUT':
        data = request.json
        cur = db.cursor()
        cur.execute(
        "UPDATE goals SET name=%s, target_amount=%s, current_amount=%s, monthly_saving=%s, target_date=%s, memo=%s WHERE id=%s AND user_id=%s",
        (data.get('name'), data.get('target_amount', 0), data.get('current_amount', 0),
        data.get('monthly_saving', 0), data.get('target_date'), data.get('memo'), rid, uid())
        )
        cur.close()
        db.commit()
        db.close()
        return jsonify({'ok': True})
    cur = db.cursor()
    cur.execute("DELETE FROM goals WHERE id = %s AND user_id = %s", (rid, uid()))
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True})


# ── API: 현금/예금 ───────────────────────────────────────────
@app.route('/api/cash-deposits', methods=['GET', 'POST'])
@login_required
def api_cash_deposits():
    db = get_db()
    if request.method == 'GET':
        cur = db.cursor()
        cur.execute("SELECT * FROM cash_deposits WHERE user_id = %s ORDER BY name", (uid(),))
        rows = cur.fetchall()
        cur.close()
        db.close()
        return jsonify(rows_to_list(rows))

    data = request.json
    today = date.today().isoformat()
    cur = db.cursor()
    cur.execute(
    "INSERT INTO cash_deposits (name, amount, memo, updated_date, user_id) VALUES (%s,%s,%s,%s,%s)",
    (data.get('name'), data.get('amount', 0), data.get('memo'), today, uid())
    )
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/cash-deposits/<int:rid>', methods=['PUT', 'DELETE'])
@login_required
def api_cash_deposits_detail(rid):
    db = get_db()
    if request.method == 'PUT':
        data = request.json
        today = date.today().isoformat()
        cur = db.cursor()
        cur.execute(
        "UPDATE cash_deposits SET name=%s, amount=%s, memo=%s, updated_date=%s WHERE id=%s AND user_id=%s",
        (data.get('name'), data.get('amount', 0), data.get('memo'), today, rid, uid())
        )
        cur.close()
        db.commit()
        db.close()
        return jsonify({'ok': True})
    cur = db.cursor()
    cur.execute("DELETE FROM cash_deposits WHERE id = %s AND user_id = %s", (rid, uid()))
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True})

# ── API: 구분별 실현손익 ─────────────────────────────────────
@app.route('/api/stock-category-pnl')
@login_required
def api_stock_category_pnl():
    """구분(category)별 실현손익 – period: monthly(최근12개월) | yearly | all"""
    category = request.args.get('category', '전체')
    period   = request.args.get('period', 'monthly')

    date_fmt = 'YYYY' if period == 'yearly' else 'YYYY-MM'

    if category and category != '전체':
        inner_where = "WHERE s.category = %s AND s.user_id = %s"
        outer_where = "AND s.category = %s AND s.user_id = %s"
        params = [date_fmt, category, uid(), category, uid()]
    else:
        inner_where = "WHERE s.user_id = %s"
        outer_where = "AND s.user_id = %s"
        params = [date_fmt, uid(), uid()]

    db  = get_db()
    cur = db.cursor()
    cur.execute(f"""
        WITH avg_costs AS (
            SELECT t.stock_id,
                SUM(CASE WHEN t.tx_type='buy' THEN t.price*t.quantity+t.fee ELSE 0 END) /
                NULLIF(SUM(CASE WHEN t.tx_type='buy' THEN t.quantity ELSE 0 END), 0) AS avg_cost
            FROM stock_tx t
            JOIN stocks s ON s.id = t.stock_id
            {inner_where}
            GROUP BY t.stock_id
        )
        SELECT
            to_char(t.tx_date::date, %s) AS period_key,
            COALESCE(SUM((t.price - ac.avg_cost) * t.quantity - t.fee), 0) AS realized_pnl,
            COALESCE(SUM(ac.avg_cost * t.quantity), 0) AS cost_basis
        FROM stock_tx t
        JOIN avg_costs ac ON ac.stock_id = t.stock_id
        JOIN stocks s ON s.id = t.stock_id
        WHERE t.tx_type = 'sell'
        {outer_where}
        GROUP BY period_key
        ORDER BY period_key
    """, params)
    rows = cur.fetchall()
    cur.close()
    db.close()

    data_map = {r['period_key']: {'pnl': float(r['realized_pnl']), 'cost': float(r['cost_basis'])} for r in rows}

    if period == 'monthly':
        today = date.today()
        keys = []
        for i in range(11, -1, -1):
            mo = today.month - i
            yr = today.year
            while mo <= 0:
                mo += 12; yr -= 1
            keys.append(f"{yr}-{mo:02d}")
        # cumulative includes all history before our 12-month window
        cumulative = sum(v['pnl'] for k, v in data_map.items() if k < keys[0])
    else:
        keys = sorted(data_map.keys())
        cumulative = 0

    result = []
    for k in keys:
        d = data_map.get(k, {'pnl': 0, 'cost': 0})
        cumulative += d['pnl']
        result.append({
            'label':          k,
            'realized_pnl':   round(d['pnl']),
            'cost_basis':     round(d['cost']),
            'return_rate':    round(d['pnl'] / d['cost'] * 100, 2) if d['cost'] else 0,
            'cumulative_pnl': round(cumulative),
        })

    return jsonify(result)


# ── API: 월별 실현손익 ───────────────────────────────────────
@app.route('/api/investment-monthly')
@login_required
def api_investment_monthly():
    """최근 12개월 월별 실현손익 및 누계 (주식+ETF+공모주 합산)"""
    db = get_db()
    ex_rate = get_current_exchange_rate()

    cur = db.cursor()
    cur.execute("""
        WITH avg_costs AS (
            SELECT stock_id,
                SUM(CASE WHEN tx_type='buy' THEN price*quantity ELSE 0 END) /
                NULLIF(SUM(CASE WHEN tx_type='buy' THEN quantity ELSE 0 END), 0) AS avg_cost
            FROM stock_tx GROUP BY stock_id
        )
        SELECT to_char(t.tx_date::date, 'YYYY-MM') AS ym,
            COALESCE(SUM(((t.price - ac.avg_cost) * t.quantity - t.fee) * (CASE WHEN s.ticker IS NOT NULL AND s.ticker != '' AND s.ticker !~ '^[0-9]{6}$' THEN %s ELSE 1 END)), 0) AS realized_pnl
        FROM stock_tx t
        JOIN avg_costs ac ON ac.stock_id = t.stock_id
        JOIN stocks s ON s.id = t.stock_id
        WHERE t.tx_type = 'sell' AND s.user_id = %s
        GROUP BY ym ORDER BY ym
    """, (ex_rate, uid()))
    stocks_by_month = {r['ym']: float(r['realized_pnl']) for r in cur.fetchall()}
    cur.close()

    cur = db.cursor()
    cur.execute("""
        WITH avg_costs AS (
            SELECT etf_id,
                SUM(CASE WHEN tx_type='buy' THEN price*quantity ELSE 0 END) /
                NULLIF(SUM(CASE WHEN tx_type='buy' THEN quantity ELSE 0 END), 0) AS avg_cost
            FROM etf_tx GROUP BY etf_id
        )
        SELECT to_char(t.tx_date::date, 'YYYY-MM') AS ym,
            COALESCE(SUM(((t.price - ac.avg_cost) * t.quantity - t.fee) * (CASE WHEN e.ticker IS NOT NULL AND e.ticker != '' AND e.ticker !~ '^[0-9]{6}$' THEN %s ELSE 1 END)), 0) AS realized_pnl
        FROM etf_tx t
        JOIN avg_costs ac ON ac.etf_id = t.etf_id
        JOIN etf e ON e.id = t.etf_id
        WHERE t.tx_type = 'sell' AND e.user_id = %s
        GROUP BY ym ORDER BY ym
    """, (ex_rate, uid()))
    etf_by_month = {r['ym']: float(r['realized_pnl']) for r in cur.fetchall()}
    cur.close()

    cur = db.cursor()
    cur.execute("""
        SELECT to_char(listing_date::date, 'YYYY-MM') AS ym,
            COALESCE(SUM(realized_pnl), 0) AS realized_pnl
        FROM ipo
        WHERE user_id = %s
        GROUP BY ym ORDER BY ym
    """, (uid(),))
    ipo_by_month = {r['ym']: float(r['realized_pnl']) for r in cur.fetchall()}
    cur.close()
    db.close()

    today = date.today()
    months = []
    cumulative = 0
    for i in range(11, -1, -1):
        mo = today.month - i
        yr = today.year
        while mo <= 0:
            mo += 12
            yr -= 1
        ym = f"{yr}-{mo:02d}"
        pnl = round(stocks_by_month.get(ym, 0) + etf_by_month.get(ym, 0) + ipo_by_month.get(ym, 0))
        cumulative += pnl
        months.append({'ym': ym, 'realized_pnl': pnl, 'cumulative_pnl': cumulative})

    return jsonify(months)


# ── API: 대시보드 집계 ───────────────────────────────────────
@app.route('/api/dashboard')
@login_required
def api_dashboard():
    try:
     return _api_dashboard_inner()
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 200

def _api_dashboard_inner():
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
    "WHERE to_char(date::date, 'YYYY-MM') = %s AND category IN ('급여', '사업소득') AND date <= CURRENT_DATE AND user_id = %s",
    (ym, uid())
    )
    labor_inc = cur.fetchone()[0]
    cur.close()

    # 자생소득: 그 외 모든 수입
    cur = db.cursor()
    cur.execute(
    "SELECT COALESCE(SUM(amount),0) FROM income "
    "WHERE to_char(date::date, 'YYYY-MM') = %s AND category NOT IN ('급여', '사업소득') AND date <= CURRENT_DATE AND user_id = %s",
    (ym, uid())
    )
    passive_inc = cur.fetchone()[0]
    cur.close()

    # 이번달 수입 합계
    cur = db.cursor()
    cur.execute(
    "SELECT COALESCE(SUM(amount),0) as total FROM income WHERE to_char(date::date, 'YYYY-MM') = %s AND date <= CURRENT_DATE AND user_id = %s", (ym, uid())
    )
    income_total = cur.fetchone()['total']
    cur.close()

    # 이번달 지출 합계
    cur = db.cursor()
    cur.execute(
    "SELECT COALESCE(SUM(amount),0) as total FROM budget WHERE to_char(date::date, 'YYYY-MM') = %s AND date <= CURRENT_DATE AND user_id = %s", (ym, uid())
    )
    expense_total = cur.fetchone()['total']
    cur.close()

    # 이번달 카드 지출
    cur = db.cursor()
    cur.execute(
    "SELECT COALESCE(SUM(amount),0) as total FROM card_tx WHERE to_char(date::date, 'YYYY-MM') = %s AND date <= CURRENT_DATE AND user_id = %s", (ym, uid())
    )
    card_total = cur.fetchone()['total']
    cur.close()

    ex_rate = get_current_exchange_rate()
    stocks_val, stocks_cost = get_stocks_total_and_cost(db, ex_rate, uid())
    etf_val, etf_cost = get_etf_total_and_cost(db, ex_rate, uid())

    # 코인 평가액
    cur = db.cursor()
    cur.execute(
    "SELECT COALESCE(SUM(current_price * quantity),0) as val FROM crypto WHERE user_id = %s", (uid(),)
    )
    crypto_val = float(cur.fetchone()['val'] or 0)
    cur.close()

    # 부동산 현재가 (시세 - 임대보증금 + 거주보증금)
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(current_price),0) FROM real_estate WHERE user_id = %s", (uid(),))
    re_total_price = float(cur.fetchone()[0] or 0)
    cur.close()
    cur = db.cursor()
    cur.execute("""
    SELECT COALESCE(SUM(deposit), 0) FROM tenant_contracts
    WHERE id IN (SELECT MAX(id) FROM tenant_contracts WHERE real_estate_id IS NOT NULL GROUP BY real_estate_id)
    AND user_id = %s
    """, (uid(),))
    re_total_deposit = float(cur.fetchone()[0] or 0)
    cur.close()
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(deposit), 0) FROM residence WHERE user_id = %s", (uid(),))
    residence_deposit = float(cur.fetchone()[0] or 0)
    cur.close()
    re_val = re_total_price - re_total_deposit + residence_deposit

    # 연금 누적액
    cur = db.cursor()
    cur.execute(
    "SELECT COALESCE(SUM(accumulated),0) as val FROM pension WHERE user_id = %s", (uid(),)
    )
    pension_val = float(cur.fetchone()['val'] or 0)
    cur.close()

    # 현금/예금
    cur = db.cursor()
    cur.execute(
    "SELECT COALESCE(SUM(amount),0) as val FROM cash_deposits WHERE user_id = %s", (uid(),)
    )
    cash_val = float(cur.fetchone()['val'] or 0)
    cur.close()

    # 부동산 거래 단계 조정
    sell_received = 0.0
    buy_paid = 0.0
    try:
        cur = db.cursor()
        cur.execute("""
            SELECT direction, COALESCE(SUM(amount),0) as total
            FROM real_estate_payments
            WHERE actual_date IS NOT NULL AND actual_date <= CURRENT_DATE AND user_id = %s
            GROUP BY direction
        """, (uid(),))
        for row in cur.fetchall():
            if row['direction'] == 'sell':
                sell_received = float(row['total'])
            elif row['direction'] == 'buy':
                buy_paid = float(row['total'])
        cur.close()
    except Exception:
        db.rollback()  # 테이블 없을 때 트랜잭션 중단 상태 초기화
    re_val += buy_paid - sell_received

    # 대출 잔액
    cur = db.cursor()
    cur.execute(
    "SELECT COALESCE(SUM(remaining),0) as total FROM loans WHERE user_id = %s", (uid(),)
    )
    loan_total = float(cur.fetchone()['total'] or 0)
    cur.close()

    total_assets = stocks_val + etf_val + crypto_val + re_val + pension_val + cash_val
    net_worth = total_assets - loan_total
    gross_assets = total_assets + re_total_deposit

    # 이번달 수입 카테고리별
    cur = db.cursor()
    cur.execute(
    "SELECT category, SUM(amount) as total FROM income WHERE to_char(date::date, 'YYYY-MM') = %s AND user_id = %s GROUP BY category",
    (ym, uid())
    )
    income_by_cat = cur.fetchall()
    cur.close()

    # 이번달 지출 카테고리별
    cur = db.cursor()
    cur.execute(
    "SELECT category, SUM(amount) as total FROM budget WHERE to_char(date::date, 'YYYY-MM') = %s AND user_id = %s GROUP BY category",
    (ym, uid())
    )
    expense_by_cat = cur.fetchall()
    cur.close()

    # 대출 목록
    cur = db.cursor()
    cur.execute(
    "SELECT name, remaining FROM loans WHERE user_id = %s ORDER BY remaining DESC", (uid(),)
    )
    loans_list = cur.fetchall()
    cur.close()

    # 목표저축 목록 (자본주의테크트리 항목 제외)
    cur = db.cursor()
    cur.execute(
    "SELECT name, target_amount, current_amount FROM goals WHERE name != '자본주의테크트리' AND user_id = %s ORDER BY target_date", (uid(),)
    )
    raw_goals = cur.fetchall()
    cur.close()

    goals_list = [{'name': g['name'], 'target_amount': g['target_amount'], 'current_amount': g['current_amount']} for g in raw_goals]

    # 자본주의테크트리 목표 자산 (app_settings에서 읽기)
    cur = db.cursor()
    cur.execute("SELECT value FROM app_settings WHERE key = 'techTreeTarget' AND user_id = %s", (uid(),))
    tt_goal = cur.fetchone()
    cur.close()
    if tt_goal and tt_goal['value']:
        goals_list.append({
            'name': '자본주의테크트리 (목표 자산)',
            'target_amount': int(tt_goal['value']),
            'current_amount': int(net_worth),
        })

    # 투자 수익률 (코인 비용만 별도 조회)
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(buy_price * quantity),0) as c FROM crypto WHERE user_id = %s", (uid(),))
    crypto_cost = cur.fetchone()['c']
    cur.close()

    db.close()

    return jsonify({
        'income_total':    income_total,
        'expense_total':   expense_total + card_total,
        'net_worth':       net_worth,
        'total_assets':    gross_assets,
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
        'goals':          goals_list,
        'investment_returns': {
            'stocks':  {'cost': stocks_cost, 'value': stocks_val},
            'etf':     {'cost': etf_cost,    'value': etf_val},
            'crypto':  {'cost': crypto_cost, 'value': crypto_val},
        },
        'payment_adjustments': {
            'sell_received': sell_received,
            'buy_paid': buy_paid,
            'has_active': sell_received > 0 or buy_paid > 0,
        },
    })


@app.route('/api/tech-tree-data')
@login_required
def api_tech_tree_data():
    try:
        return _api_tech_tree_data_inner()
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500

def _api_tech_tree_data_inner():
    db = get_db()
    ex_rate = get_current_exchange_rate()
    stocks_val = get_stocks_total_value(db, ex_rate, uid())
    etf_val = get_etf_total_value(db, ex_rate, uid())
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(current_price * quantity),0) FROM crypto WHERE user_id = %s", (uid(),))
    crypto_val = float(cur.fetchone()[0] or 0)
    cur.close()
    # 부동산 가치 계산 (현재 시세 총합 - 임대 보증금 총합)
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(current_price),0) FROM real_estate WHERE user_id = %s", (uid(),))
    re_total_price = float(cur.fetchone()[0] or 0)
    cur.close()
    # 각 부동산별 가장 최근 계약의 보증금 합계
    cur = db.cursor()
    cur.execute("""
    SELECT COALESCE(SUM(deposit), 0) FROM tenant_contracts
    WHERE id IN (SELECT MAX(id) FROM tenant_contracts WHERE real_estate_id IS NOT NULL GROUP BY real_estate_id)
    AND user_id = %s
    """, (uid(),))
    re_total_deposit = float(cur.fetchone()[0] or 0)
    cur.close()

    # 거주지 보증금 (본인이 돌려받을 돈이므로 자산에 포함)
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(deposit), 0) FROM residence WHERE user_id = %s", (uid(),))
    residence_deposit = float(cur.fetchone()[0] or 0)
    cur.close()

    re_val = re_total_price - re_total_deposit + residence_deposit

    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(amount),0) FROM cash_deposits WHERE user_id = %s", (uid(),))
    cash_val = float(cur.fetchone()[0] or 0)
    cur.close()

    # 연금 자산 추가
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(accumulated),0) FROM pension WHERE user_id = %s", (uid(),))
    pension_val = float(cur.fetchone()[0] or 0)
    cur.close()

    # 소득 현황 (이번달 기준, 오늘 이후 날짜의 반복 수입 등은 제외)
    today = date.today()
    ym = today.strftime('%Y-%m')
    # 근로소득: 급여, 사업소득(자영업) - 수입관리 데이터에서 직접 집계
    cur = db.cursor()
    cur.execute(
    "SELECT COALESCE(SUM(amount),0) FROM income "
    "WHERE to_char(date::date, 'YYYY-MM') = %s AND category IN ('급여', '사업소득') AND date <= CURRENT_DATE AND user_id = %s",
    (ym, uid())
    )
    labor_inc = float(cur.fetchone()[0] or 0)
    cur.close()

    # 자생소득: 그 외 모든 수입
    cur = db.cursor()
    cur.execute(
    "SELECT COALESCE(SUM(amount),0) FROM income "
    "WHERE to_char(date::date, 'YYYY-MM') = %s AND category NOT IN ('급여', '사업소득') AND date <= CURRENT_DATE AND user_id = %s",
    (ym, uid())
    )
    passive_inc = float(cur.fetchone()[0] or 0)
    cur.close()

    # 부동산 월세(임대료) 자동 합산
    cur = db.cursor()
    cur.execute("""
    SELECT COALESCE(SUM(monthly_rent), 0)
    FROM tenant_contracts
    WHERE contract_type = '월세'
    AND id IN (SELECT MAX(id) FROM tenant_contracts WHERE real_estate_id IS NOT NULL GROUP BY real_estate_id)
    AND user_id = %s
    """, (uid(),))
    rental_inc = float(cur.fetchone()[0] or 0)
    cur.close()

    # 전세 보증금 사적 레버리지 수익 계산 (보증금 * 4% / 12개월)
    cur = db.cursor()
    cur.execute("""
    SELECT COALESCE(SUM(deposit * 0.04 / 12), 0)
    FROM tenant_contracts
    WHERE contract_type = '전세'
    AND id IN (SELECT MAX(id) FROM tenant_contracts WHERE real_estate_id IS NOT NULL GROUP BY real_estate_id)
    AND user_id = %s
    """, (uid(),))
    leverage_inc = float(cur.fetchone()[0] or 0)
    cur.close()

    passive_inc += (rental_inc + leverage_inc)

    # 고정비(빨대) 합계 계산 (최근 3개월 내 2회 이상 발생한 동일 이름/금액 지출)
    cur = db.cursor()
    cur.execute("""
    SELECT name, amount, COUNT(*) as cnt, SUM(amount) as total
    FROM budget
    WHERE date >= CURRENT_DATE - INTERVAL '3 months'
    AND user_id = %s
    GROUP BY name, amount
    HAVING COUNT(*) >= 2
    ORDER BY total DESC
    """, (uid(),))
    straws = cur.fetchall()
    cur.close()
    straw_total = sum(r['total'] / r['cnt'] for r in straws) # 월평균 고정비

    # 이번달 지출 합계 (가계부 + 카드 + 대출 상환액)
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(amount),0) FROM budget WHERE to_char(date::date, 'YYYY-MM') = %s AND user_id = %s", (ym, uid()))
    expense_total = float(cur.fetchone()[0] or 0)
    cur.close()
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(amount),0) FROM card_tx WHERE to_char(date::date, 'YYYY-MM') = %s AND user_id = %s", (ym, uid()))
    card_total = float(cur.fetchone()[0] or 0)
    cur.close()
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(monthly_payment), 0) FROM loans WHERE user_id = %s", (uid(),))
    loan_repayment = float(cur.fetchone()[0] or 0)
    cur.close()
    total_exp = expense_total + card_total + loan_repayment

    # [신규] 월간 변동성 계산 (이번달 순유입액 기준)
    monthly_stats = {
        'cash': {'change': (labor_inc + passive_inc) - total_exp, 'percent': 0},
        'stocks': {'change': 0, 'percent': 0},
        'real_estate': {'change': 0, 'percent': 0},
        'crypto': {'change': 0, 'percent': 0}
    }
    # 주식/코인 이번달 매수액 집계
    cur = db.cursor()
    cur.execute("""SELECT COALESCE(SUM(price*quantity),0) FROM stock_tx
        WHERE to_char(tx_date::date, 'YYYY-MM') = %s AND tx_type='buy'
        AND stock_id IN (SELECT id FROM stocks WHERE user_id = %s)""", (ym, uid()))
    s_buy = float(cur.fetchone()[0] or 0)
    cur.close()
    cur = db.cursor()
    cur.execute("""SELECT COALESCE(SUM(price*quantity),0) FROM stock_tx
        WHERE to_char(tx_date::date, 'YYYY-MM') = %s AND tx_type='sell'
        AND stock_id IN (SELECT id FROM stocks WHERE user_id = %s)""", (ym, uid()))
    s_sell = float(cur.fetchone()[0] or 0)
    cur.close()
    monthly_stats['stocks']['change'] = s_buy - s_sell

    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(buy_price*quantity),0) FROM crypto WHERE to_char(buy_date::date, 'YYYY-MM') = %s AND user_id = %s", (ym, uid()))
    c_buy = float(cur.fetchone()[0] or 0)
    cur.close()
    monthly_stats['crypto']['change'] = c_buy

    # 변동률 계산 (현재값 대비)
    def calc_pct(val, change):
        val, change = float(val), float(change)
        prev = val - change
        return round((change / prev * 100), 1) if prev > 0 else 0
    
    monthly_stats['cash']['percent'] = calc_pct(cash_val, monthly_stats['cash']['change'])
    monthly_stats['stocks']['percent'] = calc_pct(stocks_val + etf_val, monthly_stats['stocks']['change'])
    monthly_stats['crypto']['percent'] = calc_pct(crypto_val, monthly_stats['crypto']['change'])

    # 목표 자산
    cur = db.cursor()
    cur.execute("SELECT value FROM app_settings WHERE key = 'techTreeTarget' AND user_id = %s", (uid(),))
    goal = cur.fetchone()
    cur.close()
    target_amount = int(goal['value']) if goal and goal['value'] else 1000000000  # 기본 10억

    # [신규] 월별 자산 스냅샷 자동 저장/업데이트 (DELETE+INSERT for multi-user)
    _snap_total = cash_val + stocks_val + etf_val + re_val + crypto_val + pension_val
    cur = db.cursor()
    cur.execute("DELETE FROM asset_snapshots WHERE month = %s AND user_id = %s", (ym, uid()))
    cur.execute("""
    INSERT INTO asset_snapshots (month, cash, stocks, real_estate, crypto, pension, total, updated_at, user_id)
    VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, %s)
    """, (ym, cash_val, stocks_val + etf_val, re_val, crypto_val, pension_val, _snap_total, uid()))
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
@login_required
def api_straws():
    """지출 중 매달 반복되는 '빨대'(고정비) 목록을 찾아 반환"""
    db = get_db()
    cur = db.cursor()
    cur.execute("""
    SELECT name, amount, category, COUNT(*) as cnt, MAX(date) as last_date
    FROM budget
    WHERE user_id = %s
    GROUP BY name, amount
    HAVING COUNT(*) >= 2
    ORDER BY amount DESC
    """, (uid(),))
    rows = cur.fetchall()
    cur.close()
    db.close()
    return jsonify(rows_to_list(rows))

@app.route('/api/tech-tree-goal', methods=['POST'])
@login_required
def api_tech_tree_goal():
    db = get_db()
    data = request.json
    target = str(data.get('target_amount', 1000000000))
    cur = db.cursor()
    cur.execute("DELETE FROM app_settings WHERE key = 'techTreeTarget' AND user_id = %s", (uid(),))
    cur.execute("INSERT INTO app_settings (key, value, user_id) VALUES ('techTreeTarget', %s, %s)", (target, uid()))
    cur.close()
    db.commit()
    db.close()
    return jsonify({'ok': True})


# ── API: 자산별 연도별 성장 통계 (Flow Rate & Milestone) ─────────
@app.route('/api/tech-tree-yearly-stats')
@login_required
def api_tech_tree_yearly_stats():
    try:
        return _api_tech_tree_yearly_stats_inner()
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500

def _api_tech_tree_yearly_stats_inner():
    db = get_db()
    today = date.today()

    # 1. 목표 자산 가져오기
    cur = db.cursor()
    cur.execute("SELECT value FROM app_settings WHERE key = 'techTreeTarget' AND user_id = %s", (uid(),))
    goal = cur.fetchone()
    cur.close()
    target_amount = int(goal['value']) if goal and goal['value'] else 1000000000

    # 2. 실시간 현재 자산 가져오기
    ex_rate = get_current_exchange_rate()
    stocks_val = get_stocks_total_value(db, ex_rate, user_id=uid())
    etf_val = get_etf_total_value(db, ex_rate, user_id=uid())

    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(current_price * quantity),0) FROM crypto WHERE user_id = %s", (uid(),))
    crypto_val = float(cur.fetchone()[0] or 0)
    cur.close()

    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(current_price),0) FROM real_estate WHERE user_id = %s", (uid(),))
    re_total_price = float(cur.fetchone()[0] or 0)
    cur.close()

    cur = db.cursor()
    cur.execute("""
    SELECT COALESCE(SUM(deposit), 0) FROM tenant_contracts
    WHERE id IN (SELECT MAX(id) FROM tenant_contracts WHERE real_estate_id IS NOT NULL GROUP BY real_estate_id)
    AND user_id = %s
    """, (uid(),))
    re_total_deposit = float(cur.fetchone()[0] or 0)
    cur.close()

    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(deposit), 0) FROM residence WHERE user_id = %s", (uid(),))
    residence_deposit = float(cur.fetchone()[0] or 0)
    cur.close()
    re_val = re_total_price - re_total_deposit + residence_deposit

    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(amount),0) FROM cash_deposits WHERE user_id = %s", (uid(),))
    cash_val = float(cur.fetchone()[0] or 0)
    cur.close()

    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(accumulated),0) FROM pension WHERE user_id = %s", (uid(),))
    pension_val = float(cur.fetchone()[0] or 0)
    cur.close()

    current_total = int(cash_val + stocks_val + etf_val + re_val + crypto_val + pension_val)
    current_percent = round((current_total / target_amount) * 100, 1) if target_amount > 0 else 0
    
    # 3. 스냅샷 데이터 조회하여 연도별 마지막 스냅샷 추출
    cur = db.cursor()
    cur.execute("SELECT month, cash, stocks, real_estate, crypto, pension, total FROM asset_snapshots WHERE user_id = %s ORDER BY month ASC", (uid(),))
    all_snapshots = cur.fetchall()
    cur.close()
    
    yearly_map = {}
    for s in all_snapshots:
        m = s['month']
        year = m[:4]
        yearly_map[year] = {
            'year': year,
            'month': m,
            'total': s['total'],
            'breakdown': {
                'cash': s['cash'],
                'stocks': s['stocks'],
                'real_estate': s['real_estate'],
                'crypto': s['crypto'],
                'pension': s['pension']
            }
        }
    
    # 올해 실시간 데이터 반영
    curr_year_str = str(today.year)
    curr_month_str = today.strftime('%Y-%m')
    
    yearly_map[curr_year_str] = {
        'year': curr_year_str,
        'month': curr_month_str,
        'total': current_total,
        'breakdown': {
            'cash': int(cash_val),
            'stocks': int(stocks_val + etf_val),
            'real_estate': int(re_val),
            'crypto': int(crypto_val),
            'pension': int(pension_val)
        }
    }
    
    # 맵 정렬 및 증감액 연산
    sorted_years = sorted(yearly_map.keys())
    yearly_history = []
    
    for idx, yr in enumerate(sorted_years):
        item = yearly_map[yr]
        total_assets = item['total']
        item['percent'] = round((total_assets / target_amount) * 100, 1) if target_amount > 0 else 0
        
        if idx == 0:
            item['change_amount'] = 0
            item['change_percent'] = 0.0
        else:
            prev_total = yearly_map[sorted_years[idx - 1]]['total']
            item['change_amount'] = total_assets - prev_total
            item['change_percent'] = round((total_assets - prev_total) / prev_total * 100, 1) if prev_total > 0 else 0.0
            
        yearly_history.append(item)
        
    # 4. 연간 유입 속도 (Flow Rate) 연산
    flow_rate_amount = 0
    changes = [h['change_amount'] for h in yearly_history if h['change_amount'] > 0]
    if len(changes) > 0:
        flow_rate_amount = sum(changes) / len(changes)
    else:
        # 과거 데이터가 없는 경우 이번달 소득/지출 기준 추정
        ym = today.strftime('%Y-%m')
        cur = db.cursor()
        cur.execute("SELECT COALESCE(SUM(amount),0) FROM income WHERE to_char(date::date, 'YYYY-MM') = %s AND category IN ('급여', '사업소득') AND date <= CURRENT_DATE AND user_id = %s", (ym, uid()))
        labor_inc = cur.fetchone()[0] or 0
        cur.close()

        cur = db.cursor()
        cur.execute("SELECT COALESCE(SUM(amount),0) FROM income WHERE to_char(date::date, 'YYYY-MM') = %s AND category NOT IN ('급여', '사업소득') AND date <= CURRENT_DATE AND user_id = %s", (ym, uid()))
        passive_inc = cur.fetchone()[0] or 0
        cur.close()

        cur = db.cursor()
        cur.execute("""
        SELECT COALESCE(SUM(monthly_rent), 0) FROM tenant_contracts
        WHERE contract_type = '월세' AND id IN (SELECT MAX(id) FROM tenant_contracts WHERE real_estate_id IS NOT NULL GROUP BY real_estate_id)
        AND user_id = %s
        """, (uid(),))
        rental_inc = cur.fetchone()[0] or 0
        cur.close()

        cur = db.cursor()
        cur.execute("""
        SELECT COALESCE(SUM(deposit * 0.04 / 12), 0) FROM tenant_contracts
        WHERE contract_type = '전세' AND id IN (SELECT MAX(id) FROM tenant_contracts WHERE real_estate_id IS NOT NULL GROUP BY real_estate_id)
        AND user_id = %s
        """, (uid(),))
        leverage_inc = cur.fetchone()[0] or 0
        cur.close()

        total_income = labor_inc + passive_inc + rental_inc + leverage_inc

        cur = db.cursor()
        cur.execute("SELECT COALESCE(SUM(amount),0) FROM budget WHERE to_char(date::date, 'YYYY-MM') = %s AND user_id = %s", (ym, uid()))
        expense_total = cur.fetchone()[0] or 0
        cur.close()

        cur = db.cursor()
        cur.execute("SELECT COALESCE(SUM(amount),0) FROM card_tx WHERE to_char(date::date, 'YYYY-MM') = %s AND user_id = %s", (ym, uid()))
        card_total = cur.fetchone()[0] or 0
        cur.close()

        cur = db.cursor()
        cur.execute("SELECT COALESCE(SUM(monthly_payment), 0) FROM loans WHERE user_id = %s", (uid(),))
        loan_repayment = cur.fetchone()[0] or 0
        cur.close()
        
        total_expense = expense_total + card_total + loan_repayment
        monthly_net_savings = total_income - total_expense
        flow_rate_amount = max(monthly_net_savings * 12, 0)
        
    if flow_rate_amount == 0:
        flow_rate_amount = 12000000 # 기본 연 1200만 원 (월 100만 원)
        
    flow_rate_percent = round((flow_rate_amount / target_amount) * 100, 1) if target_amount > 0 else 0
    
    # 5. 목표 완충 예상 기간 연산
    remaining_amount = max(target_amount - current_total, 0)
    remaining_years = 0
    remaining_months = 0
    expected_completion_ym = "완충 달성 완료!"
    
    if remaining_amount > 0:
        if flow_rate_amount > 0:
            total_months_needed = (remaining_amount / flow_rate_amount) * 12
            remaining_years = int(total_months_needed // 12)
            remaining_months = int(round(total_months_needed % 12))
            if remaining_months == 12:
                remaining_years += 1
                remaining_months = 0
                
            total_add_months = remaining_years * 12 + remaining_months
            expected_year = today.year
            expected_month = today.month + total_add_months
            while expected_month > 12:
                expected_year += 1
                expected_month -= 12
            expected_completion_ym = f"{expected_year}년 {expected_month}월"
        else:
            expected_completion_ym = "예측 불가 (자산 정체)"
            
    db.close()
    return jsonify({
        'target_amount': target_amount,
        'current_total': current_total,
        'current_percent': current_percent,
        'flow_rate_amount': int(flow_rate_amount),
        'flow_rate_percent': flow_rate_percent,
        'remaining_years': remaining_years,
        'remaining_months': remaining_months,
        'expected_completion_ym': expected_completion_ym,
        'yearly_history': yearly_history
    })


# ── API: 자산별 히스토리 (최근 12개월) ──────────────────────────
@app.route('/api/asset-history')
@login_required
def api_asset_history():
  try:
    db = get_db()
    today = date.today()
    history = []

    # 1. DB에 저장된 스냅샷 불러오기
    cur = db.cursor()
    cur.execute("SELECT * FROM asset_snapshots WHERE user_id = %s ORDER BY month DESC", (uid(),))
    snapshots = {r['month']: r for r in cur.fetchall()}
    cur.close()

    # 현재 실시간 자산 상태 (역산용 기준점)
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(amount),0) FROM cash_deposits WHERE user_id = %s", (uid(),))
    curr_cash = float(cur.fetchone()[0] or 0)
    cur.close()
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(accumulated),0) FROM pension WHERE user_id = %s", (uid(),))
    curr_pension = float(cur.fetchone()[0] or 0)
    cur.close()
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(monthly_payment),0) FROM pension WHERE user_id = %s", (uid(),))
    p_monthly = float(cur.fetchone()[0] or 0)
    cur.close()
    ex_rate = get_current_exchange_rate()
    curr_stocks = get_stocks_total_value(db, ex_rate, user_id=uid()) + get_etf_total_value(db, ex_rate, user_id=uid())
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(current_price * quantity),0) FROM crypto WHERE user_id = %s", (uid(),))
    curr_crypto = float(cur.fetchone()[0] or 0)
    cur.close()
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(current_price),0) FROM real_estate WHERE user_id = %s", (uid(),))
    re_price = float(cur.fetchone()[0] or 0)
    cur.close()
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(deposit), 0) FROM tenant_contracts WHERE id IN (SELECT MAX(id) FROM tenant_contracts WHERE real_estate_id IS NOT NULL GROUP BY real_estate_id) AND user_id = %s", (uid(),))
    re_dep = float(cur.fetchone()[0] or 0)
    cur.close()
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(deposit), 0) FROM residence WHERE user_id = %s", (uid(),))
    res_dep = float(cur.fetchone()[0] or 0)
    cur.close()
    curr_re = re_price - re_dep + res_dep

    # 12개월 범위의 연월 리스트 미리 구성
    months_list = []
    y, m = today.year, today.month
    for _ in range(12):
        months_list.append(f"{y}-{m:02d}")
        m -= 1
        if m == 0: m = 12; y -= 1

    # 최근 12개월간의 수입, 지출, 카드, 주식 거래, 코인 거래 일괄 집계 (루프 밖으로 쿼리 통합)
    cur = db.cursor()
    cur.execute("""
        SELECT to_char(date::date, 'YYYY-MM') as ym, COALESCE(SUM(amount), 0)
        FROM income
        WHERE to_char(date::date, 'YYYY-MM') IN %s AND user_id = %s
        GROUP BY ym
    """, (tuple(months_list), uid()))
    inc_map = {r[0]: r[1] for r in cur.fetchall()}
    cur.close()

    cur = db.cursor()
    cur.execute("""
        SELECT to_char(date::date, 'YYYY-MM') as ym, COALESCE(SUM(amount), 0)
        FROM budget
        WHERE to_char(date::date, 'YYYY-MM') IN %s AND user_id = %s
        GROUP BY ym
    """, (tuple(months_list), uid()))
    exp_map = {r[0]: r[1] for r in cur.fetchall()}
    cur.close()

    cur = db.cursor()
    cur.execute("""
        SELECT to_char(date::date, 'YYYY-MM') as ym, COALESCE(SUM(amount), 0)
        FROM card_tx
        WHERE to_char(date::date, 'YYYY-MM') IN %s AND user_id = %s
        GROUP BY ym
    """, (tuple(months_list), uid()))
    card_map = {r[0]: r[1] for r in cur.fetchall()}
    cur.close()

    cur = db.cursor()
    cur.execute("""
        SELECT to_char(tx_date::date, 'YYYY-MM') as ym,
               COALESCE(SUM(CASE WHEN tx_type='buy' THEN price*quantity ELSE 0 END), 0) as s_buy,
               COALESCE(SUM(CASE WHEN tx_type='sell' THEN price*quantity ELSE 0 END), 0) as s_sell
        FROM stock_tx
        WHERE to_char(tx_date::date, 'YYYY-MM') IN %s
        AND stock_id IN (SELECT id FROM stocks WHERE user_id = %s)
        GROUP BY ym
    """, (tuple(months_list), uid()))
    stock_tx_map = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    cur.close()

    cur = db.cursor()
    cur.execute("""
        SELECT to_char(buy_date::date, 'YYYY-MM') as ym, COALESCE(SUM(buy_price*quantity), 0)
        FROM crypto
        WHERE to_char(buy_date::date, 'YYYY-MM') IN %s AND user_id = %s
        GROUP BY ym
    """, (tuple(months_list), uid()))
    crypto_map = {r[0]: r[1] for r in cur.fetchall()}
    cur.close()

    cur = db.cursor()
    cur.execute("""
        SELECT to_char(buy_date::date, 'YYYY-MM') as ym, COALESCE(SUM(buy_price*quantity), 0)
        FROM crypto
        WHERE buy_date <= CURRENT_DATE AND user_id = %s
        GROUP BY ym
    """, (uid(),))
    crypto_monthly_buy = {r[0]: float(r[1]) for r in cur.fetchall()}
    cur.close()

    total_crypto_buy = sum(crypto_monthly_buy.values())
    crypto_ratio = (curr_crypto / total_crypto_buy) if total_crypto_buy > 0 else 1.0

    # 거꾸로 12개월치 데이터 생성 (메모리 맵 참조 방식으로 대기시간 격감)
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
                'pension': s['pension'],
                'is_snapshot': True
            })
            curr_cash, curr_stocks, curr_re, curr_crypto, curr_pension = s['cash'], s['stocks'], s['real_estate'], s['crypto'], s['pension']
        else:
            cum_crypto_buy = sum(v for k, v in crypto_monthly_buy.items() if k <= ym)
            est_crypto = float(cum_crypto_buy * crypto_ratio)
            history.append({
                'month': ym,
                'cash': curr_cash,
                'stocks': curr_stocks,
                'real_estate': curr_re,
                'crypto': est_crypto,
                'pension': curr_pension,
                'is_snapshot': False
            })
            curr_crypto = est_crypto
        
        # 미리 수집된 메모리 해시맵에서 값 읽기 (속도 혁명!)
        inc = inc_map.get(ym, 0)
        exp = exp_map.get(ym, 0)
        card = card_map.get(ym, 0)
        s_buy, s_sell = stock_tx_map.get(ym, (0, 0))
        c_buy = crypto_map.get(ym, 0)
        
        curr_cash -= (inc - (exp + card) - (s_buy + c_buy) + s_sell)
        curr_stocks -= (s_buy - s_sell)
        curr_pension -= p_monthly
        
        m -= 1
        if m == 0: m = 12; y -= 1

    db.close()
    return jsonify(history[::-1])
  except Exception as e:
    import traceback
    print("api_asset_history error:", traceback.format_exc())
    return jsonify({'error': str(e)}), 500

# ── API: 자산별 상세 내역 조회 ──────────────────────────
@app.route('/api/tech-tree-detail')
@login_required
def api_tech_tree_detail():
    db = get_db()
    ttype = request.args.get('type')
    ym = date.today().strftime('%Y-%m')

    res = []
    if ttype == 'labor':
        cur = db.cursor()
        cur.execute("SELECT date, name, amount, category FROM income WHERE to_char(date::date, 'YYYY-MM') = %s AND category IN ('급여', '사업소득') AND date <= CURRENT_DATE AND user_id = %s", (ym, uid()))
        rows = cur.fetchall()
        cur.close()
        res = [{'date': r[0], 'name': r[1], 'amount': r[2], 'memo': r[3]} for r in rows]
    elif ttype == 'passive':
        cur = db.cursor()
        cur.execute("SELECT date, name, amount, category FROM income WHERE to_char(date::date, 'YYYY-MM') = %s AND category NOT IN ('급여', '사업소득') AND date <= CURRENT_DATE AND user_id = %s", (ym, uid()))
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
        AND tc.id IN (SELECT MAX(id) FROM tenant_contracts WHERE real_estate_id IS NOT NULL GROUP BY real_estate_id)
        AND r.user_id = %s
        """, (uid(),))
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
        AND tc.id IN (SELECT MAX(id) FROM tenant_contracts WHERE real_estate_id IS NOT NULL GROUP BY real_estate_id)
        AND r.user_id = %s
        """, (uid(),))
        leverages = cur.fetchall()
        cur.close()
        for lev in leverages:
            if lev[1] > 0:
                res.append({'date': '레버리지', 'name': f"{lev[0]} (사적레버리지)", 'amount': int(lev[1]), 'memo': '전세금 기회비용(4%)'})
    elif ttype == 'expense':
        cur = db.cursor()
        cur.execute("SELECT date, name, amount, category FROM budget WHERE to_char(date::date, 'YYYY-MM') = %s AND user_id = %s", (ym, uid()))
        b = cur.fetchall()
        cur.close()
        cur = db.cursor()
        cur.execute("SELECT date, name, amount, category FROM card_tx WHERE to_char(date::date, 'YYYY-MM') = %s AND user_id = %s", (ym, uid()))
        c = cur.fetchall()
        cur.close()
        cur = db.cursor()
        cur.execute("SELECT '매월' as date, name, monthly_payment as amount, institution as category FROM loans WHERE user_id = %s", (uid(),))
        l = cur.fetchall()
        cur.close()
        res = [{'date': r[0], 'name': r[1], 'amount': r[2], 'memo': r[3]} for r in b + c + l]
    elif ttype == 'cash':
        cur = db.cursor()
        cur.execute("SELECT '현금' as date, name, amount, memo FROM cash_deposits WHERE user_id = %s", (uid(),))
        c = cur.fetchall()
        cur.close()
        cur = db.cursor()
        cur.execute("SELECT '목표' as date, name, current_amount as amount, memo FROM goals WHERE name != '자본주의테크트리' AND user_id = %s", (uid(),))
        g = cur.fetchall()
        cur.close()
        res = [{'date': r[0], 'name': r[1], 'amount': r[2], 'memo': r[3]} for r in c + g]
    elif ttype == 'stocks':
        ex_rate = get_current_exchange_rate()
        cur = db.cursor()
        cur.execute("""
        SELECT s.name, s.ticker, s.current_price,
        COALESCE(SUM(CASE WHEN t.tx_type='buy'  THEN t.quantity ELSE 0 END), 0) AS buy_qty,
        COALESCE(SUM(CASE WHEN t.tx_type='sell' THEN t.quantity ELSE 0 END), 0) AS sell_qty
        FROM stocks s
        LEFT JOIN stock_tx t ON t.stock_id = s.id
        WHERE s.user_id = %s
        GROUP BY s.id
        """, (uid(),))
        s_rows = cur.fetchall()
        cur.close()
        for r in s_rows:
            qty = r['buy_qty'] - r['sell_qty']
            if qty > 0:
                eval_amt = round(qty * r['current_price'])
                mul = ex_rate if is_foreign_ticker(r['ticker']) else 1
                res.append({'date': '주식', 'name': r['name'], 'amount': float(eval_amt * mul), 'memo': r['ticker']})

        cur = db.cursor()
        cur.execute("""
        SELECT e.name, e.ticker, e.current_price,
        COALESCE(SUM(CASE WHEN t.tx_type='buy'  THEN t.quantity ELSE 0 END), 0) AS buy_qty,
        COALESCE(SUM(CASE WHEN t.tx_type='sell' THEN t.quantity ELSE 0 END), 0) AS sell_qty
        FROM etf e
        LEFT JOIN etf_tx t ON t.etf_id = e.id
        WHERE e.user_id = %s
        GROUP BY e.id
        """, (uid(),))
        e_rows = cur.fetchall()
        cur.close()
        for r in e_rows:
            qty = r['buy_qty'] - r['sell_qty']
            if qty > 0:
                eval_amt = round(qty * r['current_price'])
                mul = ex_rate if is_foreign_ticker(r['ticker']) else 1
                res.append({'date': 'ETF', 'name': r['name'], 'amount': float(eval_amt * mul), 'memo': r['ticker']})
    elif ttype == 'real_estate':
        # 각 매물별 시세 - 최신 보증금(부채) 계산
        cur = db.cursor()
        cur.execute("""
        SELECT r.name, r.current_price,
        COALESCE((SELECT deposit FROM tenant_contracts WHERE real_estate_id = r.id ORDER BY id DESC LIMIT 1), 0) as tenant_dep,
        r.memo
        FROM real_estate r
        WHERE r.user_id = %s
        """, (uid(),))
        rows = cur.fetchall()
        cur.close()
        res = [{'date': '부동산', 'name': r[0], 'amount': r[1] - r[2], 'memo': f"시세:{r[1]:,} / 보증금:-{r[2]:,}"} for r in rows]
        # 거주 보증금 추가 (내가 낸 돈이므로 자산)
        cur = db.cursor()
        cur.execute("SELECT address, deposit FROM residence WHERE user_id = %s", (uid(),))
        res_dep = cur.fetchall()
        cur.close()
        for rd in res_dep:
            res.append({'date': '거주보증금', 'name': rd[0], 'amount': rd[1], 'memo': '내가 낸 보증금'})
    elif ttype == 'crypto':
        cur = db.cursor()
        cur.execute("SELECT '코인' as date, name, quantity * current_price as amount, symbol as memo FROM crypto WHERE user_id = %s", (uid(),))
        rows = cur.fetchall()
        cur.close()
        res = [{'date': r[0], 'name': r[1], 'amount': r[2], 'memo': r[3]} for r in rows]
    elif ttype == 'pension':
        cur = db.cursor()
        cur.execute("SELECT pension_type as date, name, accumulated as amount, institution as memo FROM pension WHERE user_id = %s", (uid(),))
        rows = cur.fetchall()
        cur.close()
        res = [{'date': r[0], 'name': r[1], 'amount': r[2], 'memo': r[3]} for r in rows]

    db.close()
    return jsonify(res)


# ── API: 월별 결산 ───────────────────────────────────────────
@app.route('/api/monthly-summary')
@login_required
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
        " WHERE to_char(date::date, 'YYYY-MM') = %s AND date <= CURRENT_DATE AND user_id = %s", (ym, uid())
        )
        inc = cur.fetchone()['t']
        cur.close()
        cur = db.cursor()
        cur.execute(
        "SELECT COALESCE(SUM(amount),0) as t FROM budget WHERE to_char(date::date, 'YYYY-MM') = %s AND user_id = %s", (ym, uid())
        )
        exp = cur.fetchone()['t']
        cur.close()
        cur = db.cursor()
        cur.execute(
        "SELECT COALESCE(SUM(amount),0) as t FROM card_tx WHERE to_char(date::date, 'YYYY-MM') = %s AND user_id = %s", (ym, uid())
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
@login_required
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
@login_required
def api_card_excel_mapping(card_id):
    db = get_db()
    if request.method == 'GET':
        cur = db.cursor()
        cur.execute("SELECT mapping FROM card_mappings WHERE card_id=%s AND user_id=%s", (card_id, uid()))
        row = cur.fetchone()
        cur.close()
        db.close()
        return jsonify(json.loads(row['mapping']) if row else {})
    cur = db.cursor()
    cur.execute("DELETE FROM card_mappings WHERE card_id=%s AND user_id=%s", (card_id, uid()))
    cur.execute("INSERT INTO card_mappings (card_id, mapping, user_id) VALUES (%s, %s, %s)",
    (card_id, json.dumps(request.json or {}), uid()))
    cur.close()
    db.commit(); db.close()
    return jsonify({'ok': True})


@app.route('/api/card-excel/import', methods=['POST'])
@login_required
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
        tmp_cur.execute("SELECT id FROM card_tx WHERE card_id=%s AND date=%s AND name=%s AND amount=%s AND user_id=%s",
        (card_id, date_str, name, amount, uid()))
        exists = tmp_cur.fetchone()
        tmp_cur.close()
        if exists:
            duplicate += 1; continue
        # 카테고리가 없으면 힌트 자동 적용
        if not category and name:
            category = _get_category_hint(db, name)
        cur = db.cursor()
        cur.execute("INSERT INTO card_tx (card_id,date,name,category,amount,installment,user_id) VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (card_id, date_str, name, category, amount, inst, uid()))
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
    "SELECT category FROM card_tx WHERE name=%s AND category IS NOT NULL AND category!='' AND user_id=%s "
    "ORDER BY date DESC LIMIT 1", (name, uid())
    )
    row = cur.fetchone()
    cur.close()
    if row:
        return row['category']
    # 2. 키워드 규칙 (긴 키워드 우선)
    cur = db.cursor()
    cur.execute(
    "SELECT keyword, category FROM card_category_rules WHERE user_id=%s ORDER BY LENGTH(keyword) DESC", (uid(),)
    )
    rules = cur.fetchall()
    cur.close()
    name_lower = name.lower()
    for rule in rules:
        if rule['keyword'].lower() in name_lower:
            return rule['category']
    return ''


@app.route('/api/card-category-hint')
@login_required
def api_card_category_hint():
    name = request.args.get('name', '').strip()
    if not name:
        return jsonify({'category': ''})
    db = get_db()
    category = _get_category_hint(db, name)
    db.close()
    return jsonify({'category': category})


@app.route('/api/card-category-rules', methods=['GET', 'POST'])
@login_required
def api_card_category_rules():
    db = get_db()
    if request.method == 'GET':
        cur = db.cursor()
        cur.execute("SELECT * FROM card_category_rules WHERE user_id=%s ORDER BY keyword", (uid(),))
        rows = cur.fetchall()
        cur.close()
        db.close()
        return jsonify(rows_to_list(rows))
    d = request.json or {}
    cur = db.cursor()
    cur.execute("INSERT INTO card_category_rules (keyword, category, user_id) VALUES (%s, %s, %s)",
    (d.get('keyword', ''), d.get('category', ''), uid()))
    cur.close()
    db.commit(); db.close()
    return jsonify({'ok': True})


@app.route('/api/categories', methods=['GET', 'POST'])
@login_required
def api_categories():
    db = get_db()
    if request.method == 'GET':
        cur = db.cursor()
        cur.execute("SELECT * FROM categories WHERE user_id=%s ORDER BY sort_order, name", (uid(),))
        rows = cur.fetchall()
        cur.close()
        db.close()
        return jsonify(rows_to_list(rows))
    d = request.json or {}
    cur = db.cursor()
    cur.execute("SELECT COALESCE(MAX(sort_order), -1) FROM categories WHERE user_id=%s", (uid(),))
    max_order = cur.fetchone()[0]
    cur.close()
    cur = db.cursor()
    cur.execute("INSERT INTO categories (name, sort_order, user_id) VALUES (%s, %s, %s)",
    (d.get('name', '').strip(), max_order + 1, uid()))
    cur.close()
    db.commit(); db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/categories/<int:rid>', methods=['PUT', 'DELETE'])
@login_required
def api_categories_detail(rid):
    db = get_db()
    if request.method == 'DELETE':
        cur = db.cursor()
        cur.execute("DELETE FROM categories WHERE id=%s AND user_id=%s", (rid, uid()))
        cur.close()
        db.commit(); db.close()
        return jsonify({'ok': True})
    d = request.json or {}
    cur = db.cursor()
    cur.execute("UPDATE categories SET name=%s WHERE id=%s AND user_id=%s", (d.get('name', '').strip(), rid, uid()))
    cur.close()
    db.commit(); db.close()
    return jsonify({'ok': True})


@app.route('/api/card-category-rules/<int:rid>', methods=['PUT', 'DELETE'])
@login_required
def api_card_category_rules_detail(rid):
    db = get_db()
    if request.method == 'DELETE':
        cur = db.cursor()
        cur.execute("DELETE FROM card_category_rules WHERE id=%s AND user_id=%s", (rid, uid()))
        cur.close()
        db.commit(); db.close()
        return jsonify({'ok': True})
    d = request.json or {}
    cur = db.cursor()
    cur.execute("UPDATE card_category_rules SET keyword=%s, category=%s WHERE id=%s AND user_id=%s",
    (d.get('keyword', ''), d.get('category', ''), rid, uid()))
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
    "SELECT fund_group_id FROM card_tx WHERE name=%s AND fund_group_id IS NOT NULL AND user_id=%s "
    "ORDER BY date DESC LIMIT 1", (name, uid())
    )
    row = cur.fetchone()
    cur.close()
    if row:
        return row['fund_group_id']
    # 2. 키워드 규칙 (긴 키워드 우선)
    cur = db.cursor()
    cur.execute(
    "SELECT keyword, fund_group_id FROM fund_group_rules WHERE user_id=%s ORDER BY LENGTH(keyword) DESC", (uid(),)
    )
    rules = cur.fetchall()
    cur.close()
    name_lower = name.lower()
    for rule in rules:
        if rule['keyword'].lower() in name_lower:
            return rule['fund_group_id']
    return None


@app.route('/fund-management')
@login_required
def fund_management():
    return render_template('fund_management.html')


@app.route('/api/fund-groups', methods=['GET', 'POST'])
@login_required
def api_fund_groups():
    db = get_db()
    if request.method == 'GET':
        cur = db.cursor()
        cur.execute("SELECT * FROM fund_groups WHERE user_id=%s ORDER BY sort_order, name", (uid(),))
        rows = cur.fetchall()
        cur.close()
        db.close()
        return jsonify(rows_to_list(rows))
    d = request.json or {}
    cur = db.cursor()
    cur.execute("SELECT COALESCE(MAX(sort_order), -1) FROM fund_groups WHERE user_id=%s", (uid(),))
    max_order = cur.fetchone()[0]
    cur.close()
    cur = db.cursor()
    cur.execute("INSERT INTO fund_groups (name, sort_order, user_id) VALUES (%s, %s, %s)",
    (d.get('name', '').strip(), max_order + 1, uid()))
    cur.close()
    db.commit(); db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/fund-groups/<int:rid>', methods=['PUT', 'DELETE'])
@login_required
def api_fund_groups_detail(rid):
    db = get_db()
    if request.method == 'DELETE':
        cur = db.cursor()
        cur.execute("DELETE FROM fund_groups WHERE id=%s AND user_id=%s", (rid, uid()))
        cur.close()
        db.commit(); db.close()
        return jsonify({'ok': True})
    d = request.json or {}
    cur = db.cursor()
    cur.execute("UPDATE fund_groups SET name=%s WHERE id=%s AND user_id=%s", (d.get('name', '').strip(), rid, uid()))
    cur.close()
    db.commit(); db.close()
    return jsonify({'ok': True})


@app.route('/api/fund-group-rules', methods=['GET', 'POST'])
@login_required
def api_fund_group_rules():
    db = get_db()
    if request.method == 'GET':
        cur = db.cursor()
        cur.execute(
        "SELECT r.*, g.name as fund_group_name FROM fund_group_rules r "
        "LEFT JOIN fund_groups g ON r.fund_group_id = g.id WHERE r.user_id=%s ORDER BY r.keyword", (uid(),)
        )
        rows = cur.fetchall()
        cur.close()
        db.close()
        return jsonify(rows_to_list(rows))
    d = request.json or {}
    cur = db.cursor()
    cur.execute("INSERT INTO fund_group_rules (keyword, fund_group_id, user_id) VALUES (%s, %s, %s)",
    (d.get('keyword', ''), d.get('fund_group_id'), uid()))
    cur.close()
    db.commit(); db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/fund-group-rules/<int:rid>', methods=['PUT', 'DELETE'])
@login_required
def api_fund_group_rules_detail(rid):
    db = get_db()
    if request.method == 'DELETE':
        cur = db.cursor()
        cur.execute("DELETE FROM fund_group_rules WHERE id=%s AND user_id=%s", (rid, uid()))
        cur.close()
        db.commit(); db.close()
        return jsonify({'ok': True})
    d = request.json or {}
    cur = db.cursor()
    cur.execute("UPDATE fund_group_rules SET keyword=%s, fund_group_id=%s WHERE id=%s AND user_id=%s",
    (d.get('keyword', ''), d.get('fund_group_id'), rid, uid()))
    cur.close()
    db.commit(); db.close()
    return jsonify({'ok': True})


@app.route('/api/monthly-fund-budgets', methods=['GET', 'POST'])
@login_required
def api_monthly_fund_budgets():
    db = get_db()
    if request.method == 'GET':
        year  = request.args.get('year')
        month = request.args.get('month')
        cur = db.cursor()
        cur.execute(
        "SELECT b.*, g.name as fund_group_name FROM monthly_fund_budgets b "
        "LEFT JOIN fund_groups g ON b.fund_group_id = g.id "
        "WHERE b.year=%s AND b.month=%s AND b.user_id=%s ORDER BY g.sort_order, g.name",
        (year, int(month), uid())
        )
        rows = cur.fetchall()
        cur.close()
        db.close()
        return jsonify(rows_to_list(rows))
    d = request.json or {}
    cur = db.cursor()
    cur.execute(
    "DELETE FROM monthly_fund_budgets WHERE fund_group_id=%s AND year=%s AND month=%s AND user_id=%s",
    (d.get('fund_group_id'), d.get('year'), d.get('month'), uid())
    )
    cur.execute(
    "INSERT INTO monthly_fund_budgets (fund_group_id, year, month, budget_amount, user_id) VALUES (%s,%s,%s,%s,%s)",
    (d.get('fund_group_id'), d.get('year'), d.get('month'), d.get('budget_amount', 0), uid())
    )
    cur.close()
    db.commit(); db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/fund-summary')
@login_required
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
    "  AND to_char(t.date::date, 'YYYY') = %s AND to_char(t.date::date, 'MM') = %s AND t.user_id = %s "
    "WHERE g.user_id = %s "
    "GROUP BY g.id ORDER BY g.sort_order, g.name",
    (year, month.zfill(2), uid(), uid())
    )
    actuals = cur.fetchall()
    cur.close()
    cur = db.cursor()
    cur.execute(
    "SELECT fund_group_id, budget_amount FROM monthly_fund_budgets WHERE year=%s AND month=%s AND user_id=%s",
    (year, int(month), uid())
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
@login_required
def api_card_tx_auto_fund_group():
    data    = request.json or {}
    card_id = data.get('card_id')
    year    = data.get('year')
    month   = data.get('month')

    db = get_db()
    query  = "SELECT id, name FROM card_tx WHERE fund_group_locked = 0 AND user_id = %s"
    params = [uid()]
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
            cur.execute("UPDATE card_tx SET fund_group_id=%s WHERE id=%s AND user_id=%s", (hint, row['id'], uid()))
            cur.close()
            updated += 1
    db.commit()
    db.close()
    return jsonify({'ok': True, 'updated': updated})


@app.route('/api/fund-group-hint')
@login_required
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
@login_required
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
@login_required
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
@login_required
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
@login_required
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
@login_required
def api_export_text():
    return jsonify({'error': 'PostgreSQL 환경에서는 텍스트 백업 기능을 지원하지 않습니다.'}), 501


@app.route('/api/import-text', methods=['POST'])
@login_required
def api_import_text():
    return jsonify({'error': 'PostgreSQL 환경에서는 텍스트 복구 기능을 지원하지 않습니다.'}), 501


# ── API: 전체 백업 / 복구 ────────────────────────────────────

# 외래키 의존성을 고려한 삭제 순서 (자식 → 부모)
_BACKUP_DELETE_ORDER = [
    'card_tx', 'card_mappings', 'card_category_rules',
    'stock_tx', 'etf_tx',
    'tenant_contracts', 'property_costs',
    'fund_group_rules', 'monthly_fund_budgets',
    'asset_snapshots', 'sold_real_estate',
    'income', 'budget', 'budget_recurring', 'crypto', 'loans', 'pension', 'goals',
    'cash_deposits', 'residence',
    'stocks', 'etf', 'real_estate', 'card_info',
    'fund_groups', 'categories', 'budget_categories', 'budget_category_rules',
    'stock_categories', 'app_settings',
]
# 삽입 순서 (부모 → 자식)
_BACKUP_INSERT_ORDER = [
    'categories', 'budget_categories', 'budget_category_rules',
    'stock_categories', 'card_info', 'fund_groups',
    'stocks', 'etf', 'real_estate',
    'budget_recurring',
    'income', 'budget', 'crypto', 'loans', 'pension', 'goals',
    'cash_deposits', 'residence', 'app_settings', 'asset_snapshots', 'sold_real_estate',
    'card_tx', 'card_mappings', 'card_category_rules',
    'stock_tx', 'etf_tx',
    'tenant_contracts', 'property_costs',
    'fund_group_rules', 'monthly_fund_budgets',
]


@app.route('/api/backup')
@login_required
def api_backup():
    """전체 테이블 데이터를 JSON 파일로 다운로드"""
    import decimal, traceback

    def _safe(v):
        """psycopg2 반환값을 JSON 직렬화 가능한 타입으로 변환"""
        if v is None:
            return None
        if isinstance(v, (datetime, date)):
            return v.isoformat()
        if isinstance(v, decimal.Decimal):
            return float(v)
        if isinstance(v, memoryview):
            return v.tobytes().decode('utf-8', errors='replace')
        return v

    db = get_db()
    backup = {'version': '1.0', 'exported_at': datetime.now().isoformat(), 'tables': {}}
    try:
        for table in _BACKUP_INSERT_ORDER:
            cur = db.cursor()
            try:
                cur.execute(f"SELECT * FROM {table}")
                rows = cur.fetchall()
                backup['tables'][table] = [
                    {k: _safe(v) for k, v in dict(row).items()}
                    for row in rows
                ]
            except Exception:
                backup['tables'][table] = []
            finally:
                cur.close()
    except Exception as e:
        db.close()
        return jsonify({'error': traceback.format_exc()}), 500
    finally:
        try:
            db.close()
        except Exception:
            pass

    filename = f"money_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    return Response(
        json.dumps(backup, ensure_ascii=False, indent=2),
        mimetype='application/json',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )


@app.route('/api/restore', methods=['POST'])
@login_required
def api_restore():
    """업로드된 JSON 백업 파일로 전체 데이터 복구"""
    import traceback
    if 'file' not in request.files:
        return jsonify({'error': '파일이 없습니다.'}), 400
    f = request.files['file']
    if not f.filename.endswith('.json'):
        return jsonify({'error': 'JSON 파일만 업로드할 수 있습니다.'}), 400

    try:
        backup = json.loads(f.read().decode('utf-8'))
    except Exception:
        return jsonify({'error': '파일 파싱 실패: 올바른 JSON 형식이 아닙니다.'}), 400

    if backup.get('version') != '1.0' or 'tables' not in backup:
        return jsonify({'error': '지원하지 않는 백업 형식입니다.'}), 400

    db = get_db()
    try:
        cur = db.cursor()
        # 자식 → 부모 순서로 삭제
        for table in _BACKUP_DELETE_ORDER:
            try:
                cur.execute(f"DELETE FROM {table}")
            except Exception:
                db.rollback()
        cur.close()

        tables = backup['tables']
        for table in _BACKUP_INSERT_ORDER:
            rows = tables.get(table, [])
            if not rows:
                continue
            cols = list(rows[0].keys())
            col_str = ', '.join(f'"{c}"' for c in cols)
            placeholders = ', '.join(['%s'] * len(cols))
            cur = db.cursor()
            for row in rows:
                vals = [row.get(c) for c in cols]
                cur.execute(
                    f"INSERT INTO {table} ({col_str}) VALUES ({placeholders}) ON CONFLICT DO NOTHING",
                    vals
                )
            cur.close()

            # 시퀀스 리셋 (id 컬럼이 있는 테이블)
            if rows and 'id' in rows[0]:
                cur = db.cursor()
                try:
                    cur.execute(
                        f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                        f"COALESCE((SELECT MAX(id) FROM {table}), 0) + 1, false)"
                    )
                except Exception:
                    pass
                cur.close()

        db.commit()
        total = sum(len(v) for v in tables.values())
        return jsonify({'ok': True, 'restored_rows': total})
    except Exception as e:
        db.rollback()
        return jsonify({'error': f'복구 실패: {traceback.format_exc()}'}), 500
    finally:
        db.close()


@app.route('/api/reset', methods=['POST'])
@login_required
def api_reset():
    """모든 테이블의 데이터를 삭제 (초기화)"""
    import traceback
    db = get_db()
    try:
        cur = db.cursor()
        for table in _BACKUP_DELETE_ORDER:
            try:
                cur.execute(f"DELETE FROM {table}")
            except Exception:
                db.rollback()
        db.commit()
        cur.close()
        return jsonify({'ok': True})
    except Exception as e:
        db.rollback()
        return jsonify({'error': f'초기화 실패: {traceback.format_exc()}'}), 500
    finally:
        db.close()


@app.route('/api/bond-rate')
@login_required
def api_bond_rate():
    """국민주택채권 할인율 자동 조회 (우리은행 경유)"""
    import re as _re
    from datetime import datetime as _dt
    now = _dt.now()
    year = str(now.year)
    month = f'{now.month:02d}'

    url = 'https://svc.wooribank.com/svc/Dream?withyou=HBNHB0087'
    hdrs = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Content-Type': 'application/x-www-form-urlencoded',
        'Referer': url,
    }
    try:
        resp = http_req.post(url, headers=hdrs,
                             data={'MODE': '1', 'BSDT_YM': year + month,
                                   'STD_YEAR': year, 'STD_MONTH': month},
                             timeout=15)
        resp.raise_for_status()
        text = resp.text

        rows = _re.findall(
            r'<tr[^>]*class="tableline"[^>]*>(.*?)</tr>', text, _re.DOTALL)
        records = []
        for row in rows:
            tds = _re.findall(r'<td[^>]*>(.*?)</td>', row, _re.DOTALL)
            tds = [_re.sub(r'<[^>]+>', '', td).strip() for td in tds]
            if len(tds) >= 4:
                try:
                    records.append({
                        'date':          tds[0],
                        'sell_price':    tds[1],
                        'yield_rate':    float(tds[2]),
                        'discount_rate': round(float(tds[3]), 2),
                    })
                except ValueError:
                    pass

        if not records:
            return jsonify({'error': '데이터를 찾을 수 없습니다.'}), 404

        latest = records[-1]
        return jsonify({'ok': True, 'records': records, 'latest': latest})
    except Exception as e:
        return jsonify({'error': str(e)}), 500





# ── API: 상세 자산 목록 (계산기용) ──────────────────────────────
@app.route('/api/assets-detailed')
@login_required
def api_assets_detailed():
    try:
        db = get_db()
        cur = db.cursor()
        ex_rate = get_current_exchange_rate()

        # 주식 (수량은 stock_tx 기반 계산)
        cur.execute("""
            SELECT s.name, s.ticker, s.current_price,
                COALESCE(SUM(CASE WHEN t.tx_type='buy'  THEN t.quantity ELSE 0 END), 0)
              - COALESCE(SUM(CASE WHEN t.tx_type='sell' THEN t.quantity ELSE 0 END), 0) AS qty
            FROM stocks s
            LEFT JOIN stock_tx t ON t.stock_id = s.id
            WHERE s.user_id = %s
            GROUP BY s.id, s.name, s.ticker, s.current_price
            HAVING (COALESCE(SUM(CASE WHEN t.tx_type='buy' THEN t.quantity ELSE 0 END), 0)
                  - COALESCE(SUM(CASE WHEN t.tx_type='sell' THEN t.quantity ELSE 0 END), 0)) > 0
        """, (uid(),))
        stocks = []
        for r in cur.fetchall():
            val = float(r['current_price'] or 0) * float(r['qty'] or 0)
            ticker = str(r['ticker'] or '')
            is_foreign = ticker and not re.match(r'^[0-9]{6}$', ticker)
            if is_foreign: val *= ex_rate
            stocks.append({'name': r['name'] or '이름없음', 'val': round(val)})

        # ETF (수량은 etf_tx 기반 계산)
        cur.execute("""
            SELECT e.name, e.ticker, e.current_price,
                COALESCE(SUM(CASE WHEN t.tx_type='buy'  THEN t.quantity ELSE 0 END), 0)
              - COALESCE(SUM(CASE WHEN t.tx_type='sell' THEN t.quantity ELSE 0 END), 0) AS qty
            FROM etf e
            LEFT JOIN etf_tx t ON t.etf_id = e.id
            WHERE e.user_id = %s
            GROUP BY e.id, e.name, e.ticker, e.current_price
            HAVING (COALESCE(SUM(CASE WHEN t.tx_type='buy' THEN t.quantity ELSE 0 END), 0)
                  - COALESCE(SUM(CASE WHEN t.tx_type='sell' THEN t.quantity ELSE 0 END), 0)) > 0
        """, (uid(),))
        etfs = []
        for r in cur.fetchall():
            val = float(r['current_price'] or 0) * float(r['qty'] or 0)
            ticker = str(r['ticker'] or '')
            is_foreign = ticker and not re.match(r'^[0-9]{6}$', ticker)
            if is_foreign: val *= ex_rate
            etfs.append({'name': r['name'] or '이름없음', 'val': round(val)})

        # 코인
        cur.execute("SELECT name, current_price * quantity as val FROM crypto WHERE quantity > 0 AND user_id = %s", (uid(),))
        crypto = [{'name': r['name'] or '이름없음', 'val': round(float(r['val'] or 0))} for r in cur.fetchall()]

        # 현금/예금 + 거주보증금
        cur.execute("SELECT name, amount as val FROM cash_deposits WHERE amount > 0 AND user_id = %s", (uid(),))
        cash = [{'name': r['name'] or '이름없음', 'val': round(float(r['val'] or 0))} for r in cur.fetchall()]

        cur.execute("SELECT address, deposit as val FROM residence WHERE deposit > 0 AND user_id = %s", (uid(),))
        residence = [{'name': "[거주] " + (r['address'] or '보증금'), 'val': round(float(r['val'] or 0))} for r in cur.fetchall()]

        # 부동산 (세입자 보증금 차감하여 순가치 계산)
        cur.execute("""
            SELECT re.id, re.name, re.current_price,
                COALESCE(SUM(tc.deposit), 0) AS total_deposit
            FROM real_estate re
            LEFT JOIN tenant_contracts tc ON tc.real_estate_id = re.id
            WHERE re.user_id = %s
            GROUP BY re.id, re.name, re.current_price
        """, (uid(),))
        re_list = []
        for r in cur.fetchall():
            price   = round(float(r['current_price'] or 0))
            deposit = round(float(r['total_deposit'] or 0))
            re_list.append({
                'name':          r['name'] or '이름없음',
                'val':           price,
                'deposit':       deposit,
                'net_val':       price - deposit,
            })

        # 연금
        cur.execute("SELECT name, accumulated as val FROM pension WHERE accumulated > 0 AND user_id = %s", (uid(),))
        pension = [{'name': r['name'] or '이름없음', 'val': round(float(r['val'] or 0))} for r in cur.fetchall()]

        # 세입자 보증금 (사적 레버리지 — 순자산 차감 항목)
        cur.execute("""
            SELECT re.name as re_name, tc.contract_type, tc.deposit
            FROM tenant_contracts tc
            JOIN real_estate re ON re.id = tc.real_estate_id
            WHERE tc.deposit > 0 AND re.user_id = %s
        """, (uid(),))
        tenant_deposits = [
            {'name': f"[{r['contract_type']}] {r['re_name']}", 'val': round(float(r['deposit'] or 0))}
            for r in cur.fetchall()
        ]

        cur.close()
        db.close()

        return jsonify({
            '주식': stocks,
            'ETF': etfs,
            '코인': crypto,
            '현금/예금': cash + residence,
            '부동산': re_list,
            '연금': pension,
            '_tenant_deposits': tenant_deposits,
        })
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)
