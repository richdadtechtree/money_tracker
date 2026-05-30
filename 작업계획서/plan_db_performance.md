# DB 조회 속도 개선 계획서

> **현황**: Flask + Supabase(PostgreSQL, 원격 서버) 구조에서 페이지 로딩이 느린 원인을 분석하고,  
> 코드 수정 없이 적용 가능한 것부터 핵심 리팩토링까지 단계별로 정리한다.

---

## 1. 현재 병목 원인 진단

### 원인 요약 (심각도 순)

| 순위 | 원인 | 영향 API | 심각도 |
|------|------|----------|--------|
| 1 | **콜드 스타트** (Render 무료 슬립) | 전체 | 🔴 치명 |
| 2 | **커넥션을 요청마다 새로 생성** | 전체 | 🔴 치명 |
| 3 | **루프 안에서 쿼리 반복** (N+1) | `asset-history`, `_re_enrich` | 🔴 치명 |
| 4 | **단일 값 쿼리 20+개 직렬 실행** | `tech-tree-data`, `dashboard` | 🟠 심각 |
| 5 | **`to_char()` 함수로 인덱스 무력화** | `income`, `budget`, `card_tx` 등 | 🟠 심각 |
| 6 | **상관 서브쿼리** (주식 평가액) | `stocks`, `tech-tree` | 🟡 중간 |
| 7 | **인덱스 없음** | 전체 테이블 | 🟡 중간 |
| 8 | **응답 캐시 없음** | 집계 API 전체 | 🟡 중간 |

---

### 상세 진단

#### ❶ Render 무료 플랜 콜드 스타트
비활성 15분 후 서버가 **슬립 상태**로 전환. 다음 요청 시 재시작에 **30~60초** 소요.  
사용자 입장에서는 DB가 느린 게 아니라 서버 자체가 안 켜진 상태.

#### ❷ 요청마다 DB 커넥션 신규 생성
```python
# 현재: api 함수마다 이 패턴이 반복됨
db = get_db()   # ← 매번 TCP 핸드셰이크 + PostgreSQL 인증 수행
...
db.close()
```
Supabase는 원격 서버이므로 커넥션 생성에만 **50~200ms**가 소요됨.  
페이지 1개 로드 시 여러 API를 호출하면 이 비용이 누적됨.

#### ❸ `api_asset_history()` — 루프 안 72개 쿼리
```python
for i in range(12):          # 12번 반복
    ym = f"{y}-{m:02d}"
    cur.execute("... income ...")    # ← 쿼리 1
    cur.execute("... budget ...")    # ← 쿼리 2
    cur.execute("... card_tx ...")   # ← 쿼리 3
    cur.execute("... stock_tx buy ...")  # ← 쿼리 4
    cur.execute("... stock_tx sell ...")  # ← 쿼리 5
    cur.execute("... crypto ...")    # ← 쿼리 6
    # = 12 × 6 = 72회 왕복
```

#### ❹ `_re_enrich()` — 부동산 N+1 쿼리
```python
for r in rows:   # 부동산 N개
    cur.execute("SELECT * FROM tenant_contracts ...")  # ← 쿼리 1/부동산
    cur.execute("SELECT SUM FROM property_costs ...")  # ← 쿼리 2/부동산
    cur.execute("SELECT SUM FROM property_costs ...")  # ← 쿼리 3/부동산
    # = N × 3 쿼리
```

#### ❺ `to_char()` 함수가 인덱스를 못 씀
```sql
-- 현재 (인덱스 사용 불가 → 풀스캔)
WHERE to_char(date::date, 'YYYY-MM') = '2025-05'

-- 개선 (인덱스 사용 가능)
WHERE date >= '2025-05-01' AND date < '2025-06-01'
```

#### ❻ 주식 평가액 상관 서브쿼리
```sql
-- 현재: stocks 행마다 서브쿼리 실행 (N개 주식 = N번 stock_tx 스캔)
SELECT SUM(s.current_price * (
    SELECT SUM(...) FROM stock_tx WHERE stock_id = s.id
))
FROM stocks s

-- 개선: JOIN으로 1회 처리
SELECT SUM(s.current_price * t.net_qty)
FROM stocks s
JOIN (SELECT stock_id, SUM(CASE WHEN tx_type='buy' THEN quantity ELSE -quantity END) AS net_qty
      FROM stock_tx GROUP BY stock_id) t ON t.stock_id = s.id
```

---

## 2. 개선 방안 (단계별)

---

### STEP 1 — 즉시 적용 (코드 변경 없음, 10분)

#### 1-A. Render 콜드 스타트 방지 — UptimeRobot 설정

Render 무료 플랜의 슬립을 막으려면 **14분마다 헬스체크 핑**을 보내면 됨.

1. [https://uptimerobot.com](https://uptimerobot.com) 무료 계정 생성
2. "Add New Monitor" → **HTTP(s)**
3. URL: `https://money-tracker-r8u6.onrender.com/` 
4. Monitoring Interval: **5분** (무료는 5분이 최소)
5. 저장 → 이후 서버가 슬립에 진입하지 않음

> 대안: Render 유료 플랜($7/월)으로 업그레이드 시 슬립 없이 항상 실행됨.

#### 1-B. DB 인덱스 추가 — Supabase SQL Editor에서 실행

아래 SQL을 **Supabase → SQL Editor**에서 한 번만 실행.  
인덱스는 한 번 만들면 이후 자동으로 쿼리에 적용됨.

```sql
-- ① income 테이블: 날짜·카테고리 복합 인덱스
CREATE INDEX IF NOT EXISTS idx_income_date
    ON income (date);
CREATE INDEX IF NOT EXISTS idx_income_date_cat
    ON income (date, category);

-- ② budget 테이블: 날짜 인덱스
CREATE INDEX IF NOT EXISTS idx_budget_date
    ON budget (date);

-- ③ card_tx 테이블: 날짜·카드 복합 인덱스
CREATE INDEX IF NOT EXISTS idx_card_tx_date
    ON card_tx (date);
CREATE INDEX IF NOT EXISTS idx_card_tx_card_date
    ON card_tx (card_id, date);
CREATE INDEX IF NOT EXISTS idx_card_tx_fund_group
    ON card_tx (fund_group_id);

-- ④ stock_tx 테이블: 종목·날짜·거래유형 인덱스
CREATE INDEX IF NOT EXISTS idx_stock_tx_stock_id
    ON stock_tx (stock_id);
CREATE INDEX IF NOT EXISTS idx_stock_tx_date
    ON stock_tx (tx_date);
CREATE INDEX IF NOT EXISTS idx_stock_tx_type
    ON stock_tx (stock_id, tx_type);

-- ⑤ tenant_contracts: 부동산 ID 인덱스
CREATE INDEX IF NOT EXISTS idx_tenant_contracts_re_id
    ON tenant_contracts (real_estate_id);

-- ⑥ property_costs: 부동산 ID + 비용유형
CREATE INDEX IF NOT EXISTS idx_property_costs_re_id
    ON property_costs (real_estate_id, cost_type);

-- ⑦ asset_snapshots: month 인덱스 (이미 UNIQUE지만 확인)
CREATE UNIQUE INDEX IF NOT EXISTS idx_asset_snapshots_month
    ON asset_snapshots (month);
```

> **효과**: 위 인덱스만으로 `to_char()` 사용 구간을 제외한 쿼리 속도가 **3~10배** 빨라짐.

---

### STEP 2 — 커넥션 풀링 적용 (`database.py` 수정)

#### 현재 문제
```python
# database.py (추정 구조)
def get_db():
    conn = psycopg2.connect(DATABASE_URL)  # ← 매 요청마다 새 TCP 연결
    return conn
```

#### 개선 코드

```python
# database.py 전체 교체
import psycopg2
import psycopg2.pool
import psycopg2.extras
import os

DATABASE_URL = os.environ.get('DATABASE_URL')

# ── 커넥션 풀 생성 (앱 시작 시 1회만 실행) ──────────────────
# minconn=2: 항상 2개 연결 유지
# maxconn=10: 최대 10개 동시 연결 허용
_pool = psycopg2.pool.ThreadedConnectionPool(
    minconn=2,
    maxconn=10,
    dsn=DATABASE_URL,
    cursor_factory=psycopg2.extras.RealDictCursor  # dict-like 커서 유지
)

def get_db():
    """
    풀에서 커넥션을 대여한다.
    기존 get_db()와 동일한 인터페이스를 유지하므로
    app.py의 다른 코드는 변경 불필요.
    """
    conn = _pool.getconn()
    # autocommit=False 유지 (기존 db.commit() 코드 그대로 동작)
    return conn

def release_db(conn):
    """커넥션을 풀에 반환."""
    _pool.putconn(conn)

def init_db():
    """테이블 초기화 (기존 함수 유지)."""
    conn = get_db()
    try:
        # 기존 init_db 로직 그대로
        pass
    finally:
        release_db(conn)
```

#### `app.py`에서 `db.close()` → `release_db(db)` 변경

현재 모든 함수 끝에 `db.close()`가 있는데, 이를 `release_db(db)`로 바꿔야 함.  
전체 일괄 치환 방법:

```bash
# 터미널에서 실행 (app.py가 있는 디렉토리에서)
sed -i 's/db\.close()/release_db(db)/g' app.py
```

그 후 `app.py` 상단 import에 추가:
```python
from database import get_db, init_db, release_db
```

> **효과**: 요청당 50~200ms이던 커넥션 생성 비용이 **1~5ms**로 감소.

---

### STEP 3 — 핵심 쿼리 병합 (app.py 수정)

#### 3-A. `api_tech_tree_data()` — 20개 쿼리 → 1개 CTE 쿼리

```python
@app.route('/api/tech-tree-data')
def api_tech_tree_data():
    db = get_db()
    today = date.today()
    ym_start = today.strftime('%Y-%m-01')                  # 이번달 1일
    ym_end   = (today.replace(day=1) + 
                __import__('dateutil.relativedelta', fromlist=['relativedelta'])
                .relativedelta(months=1)).strftime('%Y-%m-01')  # 다음달 1일

    cur = db.cursor()
    cur.execute("""
    WITH
    -- ① 주식 평가액 (JOIN으로 상관 서브쿼리 제거)
    stock_val AS (
        SELECT COALESCE(SUM(s.current_price * COALESCE(t.net_qty, 0)), 0) AS val
        FROM stocks s
        LEFT JOIN (
            SELECT stock_id,
                   SUM(CASE WHEN tx_type='buy' THEN quantity ELSE -quantity END) AS net_qty
            FROM stock_tx GROUP BY stock_id
        ) t ON t.stock_id = s.id
    ),
    -- ② ETF 평가액
    etf_val AS (
        SELECT COALESCE(SUM(current_price * quantity), 0) AS val FROM etf
    ),
    -- ③ 코인 평가액
    crypto_val AS (
        SELECT COALESCE(SUM(current_price * quantity), 0) AS val FROM crypto
    ),
    -- ④ 부동산 (시세 - 최신 임대 보증금 + 거주 보증금)
    re_price AS (
        SELECT COALESCE(SUM(current_price), 0) AS val FROM real_estate
    ),
    re_deposit AS (
        SELECT COALESCE(SUM(deposit), 0) AS val
        FROM tenant_contracts
        WHERE id IN (SELECT MAX(id) FROM tenant_contracts GROUP BY real_estate_id)
    ),
    res_deposit AS (
        SELECT COALESCE(SUM(deposit), 0) AS val FROM residence
    ),
    -- ⑤ 현금/예금
    cash_val AS (
        SELECT COALESCE(SUM(amount), 0) AS val FROM cash_deposits
    ),
    -- ⑥ 목표저축
    goal_val AS (
        SELECT COALESCE(SUM(current_amount), 0) AS val
        FROM goals WHERE name != '자본주의테크트리'
    ),
    -- ⑦ 목표 자산
    goal_target AS (
        SELECT COALESCE(MAX(target_amount), 1000000000) AS val
        FROM goals WHERE name = '자본주의테크트리'
    ),
    -- ⑧ 연금
    pension_val AS (
        SELECT COALESCE(SUM(accumulated), 0) AS val FROM pension
    ),
    -- ⑨ 이번달 근로소득 (날짜 범위로 인덱스 활용)
    labor_inc AS (
        SELECT COALESCE(SUM(amount), 0) AS val FROM income
        WHERE date >= %s AND date < %s
          AND category IN ('급여', '사업소득')
          AND date <= CURRENT_DATE
    ),
    -- ⑩ 이번달 자생소득
    passive_inc AS (
        SELECT COALESCE(SUM(amount), 0) AS val FROM income
        WHERE date >= %s AND date < %s
          AND category NOT IN ('급여', '사업소득')
          AND date <= CURRENT_DATE
    ),
    -- ⑪ 임대 수입 + 레버리지
    rental_inc AS (
        SELECT
            COALESCE(SUM(CASE WHEN contract_type='월세' THEN monthly_rent ELSE 0 END), 0) AS rent,
            COALESCE(SUM(CASE WHEN contract_type='전세' THEN deposit * 0.04 / 12 ELSE 0 END), 0) AS leverage
        FROM tenant_contracts
        WHERE id IN (SELECT MAX(id) FROM tenant_contracts GROUP BY real_estate_id)
    ),
    -- ⑫ 이번달 지출
    expense AS (
        SELECT COALESCE(SUM(amount), 0) AS val FROM budget
        WHERE date >= %s AND date < %s
    ),
    -- ⑬ 이번달 카드 지출
    card_exp AS (
        SELECT COALESCE(SUM(amount), 0) AS val FROM card_tx
        WHERE date >= %s AND date < %s
    ),
    -- ⑭ 대출 월상환액
    loan_pay AS (
        SELECT COALESCE(SUM(monthly_payment), 0) AS val FROM loans
    ),
    -- ⑮ 이번달 주식 매수/매도
    stock_trade AS (
        SELECT
            COALESCE(SUM(CASE WHEN tx_type='buy'  THEN price*quantity ELSE 0 END), 0) AS buy_amt,
            COALESCE(SUM(CASE WHEN tx_type='sell' THEN price*quantity ELSE 0 END), 0) AS sell_amt
        FROM stock_tx WHERE tx_date >= %s AND tx_date < %s
    ),
    -- ⑯ 이번달 코인 매수
    crypto_trade AS (
        SELECT COALESCE(SUM(buy_price*quantity), 0) AS buy_amt
        FROM crypto WHERE buy_date >= %s AND buy_date < %s
    )
    -- 최종 SELECT: 모든 집계값을 1행으로
    SELECT
        (SELECT val FROM stock_val)    AS stocks_val,
        (SELECT val FROM etf_val)      AS etf_val,
        (SELECT val FROM crypto_val)   AS crypto_val,
        (SELECT val FROM re_price)     AS re_price,
        (SELECT val FROM re_deposit)   AS re_deposit,
        (SELECT val FROM res_deposit)  AS res_deposit,
        (SELECT val FROM cash_val)     AS cash_val,
        (SELECT val FROM goal_val)     AS goal_val,
        (SELECT val FROM goal_target)  AS target_amount,
        (SELECT val FROM pension_val)  AS pension_val,
        (SELECT val FROM labor_inc)    AS labor_inc,
        (SELECT val FROM passive_inc)  AS passive_inc,
        (SELECT rent FROM rental_inc)  AS rental_inc,
        (SELECT leverage FROM rental_inc) AS leverage_inc,
        (SELECT val FROM expense)      AS expense_total,
        (SELECT val FROM card_exp)     AS card_total,
        (SELECT val FROM loan_pay)     AS loan_repayment,
        (SELECT buy_amt  FROM stock_trade) AS s_buy,
        (SELECT sell_amt FROM stock_trade) AS s_sell,
        (SELECT buy_amt  FROM crypto_trade) AS c_buy
    """,
    # 날짜 파라미터 (ym_start, ym_end)를 각 WITH절에 맞게 반복
    (ym_start, ym_end,   # labor_inc
     ym_start, ym_end,   # passive_inc
     ym_start, ym_end,   # expense
     ym_start, ym_end,   # card_exp
     ym_start, ym_end,   # stock_trade
     ym_start, ym_end,   # crypto_trade
    ))
    
    row = cur.fetchone()
    cur.close()
    
    # 계산은 파이썬에서 (기존 로직 그대로)
    re_val       = row['re_price'] - row['re_deposit'] + row['res_deposit']
    cash_val     = row['cash_val'] + row['goal_val']
    passive_inc  = row['passive_inc'] + row['rental_inc'] + row['leverage_inc']
    total_exp    = row['expense_total'] + row['card_total'] + row['loan_repayment']
    stocks_total = row['stocks_val'] + row['etf_val']
    
    # ... 이하 응답 구성 동일 ...
    
    release_db(db)
```

> **효과**: 20+ 왕복 → **1회 왕복**. 네트워크 레이턴시 기준 **1~2초 단축**.

---

#### 3-B. `api_asset_history()` — 72개 쿼리 → 6개 쿼리

```python
@app.route('/api/asset-history')
def api_asset_history():
    db = get_db()
    today = date.today()
    
    # 12개월 전 날짜 계산
    twelve_months_ago = (today.replace(day=1) - 
                         __import__('dateutil.relativedelta', fromlist=['relativedelta'])
                         .relativedelta(months=11)).strftime('%Y-%m-01')

    # ── 한 번에 12개월치 월별 집계 ──────────────────────────
    cur = db.cursor()
    
    # 수입 (월별 합계)
    cur.execute("""
        SELECT to_char(date::date, 'YYYY-MM') AS ym, COALESCE(SUM(amount), 0) AS val
        FROM income
        WHERE date >= %s AND date <= CURRENT_DATE
        GROUP BY ym ORDER BY ym
    """, (twelve_months_ago,))
    income_map = {r['ym']: r['val'] for r in cur.fetchall()}

    # 지출 (월별 합계)
    cur.execute("""
        SELECT to_char(date::date, 'YYYY-MM') AS ym, COALESCE(SUM(amount), 0) AS val
        FROM budget WHERE date >= %s GROUP BY ym ORDER BY ym
    """, (twelve_months_ago,))
    expense_map = {r['ym']: r['val'] for r in cur.fetchall()}

    # 카드 지출
    cur.execute("""
        SELECT to_char(date::date, 'YYYY-MM') AS ym, COALESCE(SUM(amount), 0) AS val
        FROM card_tx WHERE date >= %s GROUP BY ym ORDER BY ym
    """, (twelve_months_ago,))
    card_map = {r['ym']: r['val'] for r in cur.fetchall()}

    # 주식 매수/매도 (월별)
    cur.execute("""
        SELECT to_char(tx_date::date, 'YYYY-MM') AS ym,
               COALESCE(SUM(CASE WHEN tx_type='buy'  THEN price*quantity ELSE 0 END), 0) AS buy_amt,
               COALESCE(SUM(CASE WHEN tx_type='sell' THEN price*quantity ELSE 0 END), 0) AS sell_amt
        FROM stock_tx WHERE tx_date >= %s GROUP BY ym ORDER BY ym
    """, (twelve_months_ago,))
    stock_map = {r['ym']: (r['buy_amt'], r['sell_amt']) for r in cur.fetchall()}

    # 코인 매수 (월별)
    cur.execute("""
        SELECT to_char(buy_date::date, 'YYYY-MM') AS ym, COALESCE(SUM(buy_price*quantity), 0) AS val
        FROM crypto WHERE buy_date >= %s GROUP BY ym ORDER BY ym
    """, (twelve_months_ago,))
    crypto_map = {r['ym']: r['val'] for r in cur.fetchall()}

    # 스냅샷
    cur.execute("SELECT * FROM asset_snapshots ORDER BY month DESC")
    snapshots = {r['month']: r for r in cur.fetchall()}
    cur.close()

    # ── 파이썬에서 역산 (쿼리 없이) ──────────────────────────
    # (이하 기존 루프 로직 그대로, DB 호출만 제거됨)
    history = []
    y, m = today.year, today.month
    for i in range(12):
        ym = f"{y}-{m:02d}"
        inc    = income_map.get(ym, 0)
        exp    = expense_map.get(ym, 0)
        card   = card_map.get(ym, 0)
        s_buy, s_sell = stock_map.get(ym, (0, 0))
        c_buy  = crypto_map.get(ym, 0)
        # ... 역산 로직 동일 ...
        m -= 1
        if m == 0: m = 12; y -= 1

    release_db(db)
    return jsonify(history[::-1])
```

> **효과**: 72회 왕복 → **6회 왕복**. **최대 3~5초 단축**.

---

#### 3-C. `_re_enrich()` — N+1 → JOIN으로 1회 처리

```python
def _re_enrich(db, rows):
    """
    [개선] 루프 내 개별 쿼리 제거 → JOIN + GROUP BY로 한 번에 처리
    """
    if not rows:
        return []
    
    re_ids = [r['id'] for r in rows]
    placeholders = ','.join(['%s'] * len(re_ids))

    cur = db.cursor()
    # 최신 계약 정보 (각 부동산별 MAX id)
    cur.execute(f"""
        SELECT DISTINCT ON (real_estate_id)
               real_estate_id, contract_type, deposit, monthly_rent, end_date
        FROM tenant_contracts
        WHERE real_estate_id IN ({placeholders})
        ORDER BY real_estate_id, id DESC
    """, re_ids)
    contracts = {r['real_estate_id']: r for r in cur.fetchall()}

    # 취득비용 집계
    cur.execute(f"""
        SELECT real_estate_id,
               COALESCE(SUM(CASE WHEN cost_type='취득비용' THEN amount ELSE 0 END), 0) AS acq_cost,
               COALESCE(SUM(CASE WHEN cost_type='임대수익' THEN amount ELSE -amount END), 0) AS net_extra
        FROM property_costs
        WHERE real_estate_id IN ({placeholders})
        GROUP BY real_estate_id
    """, re_ids)
    costs = {r['real_estate_id']: r for r in cur.fetchall()}
    cur.close()

    result = []
    for r in rows:
        rid      = r['id']
        contract = contracts.get(rid)
        cost     = costs.get(rid, {'acq_cost': 0, 'net_extra': 0})

        deposit  = contract['deposit'] if contract else 0
        purchase = r['purchase_price']
        current  = r['current_price']
        real_inv = purchase - deposit + cost['acq_cost']
        net_gain = (current - purchase) + cost['net_extra']
        real_roi = round(net_gain / real_inv * 100, 1) if real_inv > 0 else None

        row = dict(r)
        row['contract_type'] = contract['contract_type'] if contract else None
        row['deposit']       = deposit
        row['monthly_rent']  = contract['monthly_rent'] if contract else 0
        row['contract_end']  = contract['end_date'] if contract else None
        row['real_inv']      = real_inv
        row['net_gain']      = net_gain
        row['real_roi']      = real_roi
        result.append(row)
    return result
```

> **효과**: 부동산 N개 → 3N 쿼리에서 **3 쿼리**로 고정. 부동산 5개 기준 **15 → 3회**.

---

#### 3-D. `to_char()` → 날짜 범위로 교체

전체 `app.py`에서 아래 패턴을 찾아 교체:

```python
# ── 변경 전 (인덱스 무력화) ──
"WHERE to_char(date::date, 'YYYY-MM') = %s"  # 파라미터: '2025-05'

# ── 변경 후 (인덱스 활용) ──
"WHERE date >= %s AND date < %s"  # 파라미터: ('2025-05-01', '2025-06-01')
```

파라미터 생성 헬퍼 함수 추가 (`app.py` 상단):

```python
def _month_range(year_str, month_str):
    """
    'YYYY', 'MM' → (월 시작일, 다음달 시작일) 반환
    예: '2025', '05' → ('2025-05-01', '2025-06-01')
    """
    from datetime import date
    import calendar
    y, m = int(year_str), int(month_str)
    start = date(y, m, 1).isoformat()
    # 다음달 1일 계산
    if m == 12:
        end = date(y + 1, 1, 1).isoformat()
    else:
        end = date(y, m + 1, 1).isoformat()
    return start, end

# 사용 예
# 기존: WHERE to_char(date::date, 'YYYY-MM') = %s  →  params: [ym]
# 변경: WHERE date >= %s AND date < %s              →  params: _month_range(year, month)
```

---

### STEP 4 — 응답 캐싱 적용

집계 API는 데이터가 자주 바뀌지 않으므로 **60~300초 캐싱**이 효과적.

#### 설치

```bash
pip install Flask-Caching
```

#### `app.py` 설정

```python
from flask_caching import Cache

# 인메모리 캐시 (SimpleCache: 단일 프로세스용)
cache = Cache(app, config={
    'CACHE_TYPE': 'SimpleCache',
    'CACHE_DEFAULT_TIMEOUT': 120  # 기본 2분
})
```

#### 캐시 적용

```python
# 대시보드 집계: 2분 캐시
@app.route('/api/dashboard')
@cache.cached(timeout=120, query_string=True)  # query_string=True: year/month 파라미터 포함
def api_dashboard():
    ...

# 테크트리: 3분 캐시
@app.route('/api/tech-tree-data')
@cache.cached(timeout=180)
def api_tech_tree_data():
    ...

# 자산 히스토리: 5분 캐시
@app.route('/api/asset-history')
@cache.cached(timeout=300)
def api_asset_history():
    ...

# 월별 결산: 5분 캐시
@app.route('/api/monthly-summary')
@cache.cached(timeout=300, query_string=True)
def api_monthly_summary():
    ...
```

#### 데이터 변경 시 캐시 무효화

```python
def _clear_summary_cache():
    """수입/지출/자산 데이터 변경 시 집계 캐시 삭제"""
    cache.delete('view//api/dashboard')
    cache.delete('view//api/tech-tree-data')
    cache.delete('view//api/asset-history')
    cache.delete('view//api/monthly-summary')

# POST/PUT/DELETE 핸들러에 추가
@app.route('/api/income', methods=['POST'])
def api_income():
    ...
    db.commit()
    _clear_summary_cache()  # ← 추가
    return jsonify({'ok': True}), 201
```

> **효과**: 두 번째 조회부터 DB 쿼리 없이 **1~5ms** 응답.

---

## 3. 개선 효과 예측

### 로딩 시간 비교 (테크트리 페이지 기준)

| 상황 | 개선 전 | 개선 후 |
|------|---------|---------|
| 콜드 스타트 시 | 30~60초 | 1~2초 (UptimeRobot 적용 시 콜드 스타트 없음) |
| 첫 요청 (캐시 미스) | 3~8초 | 0.3~0.8초 |
| 반복 요청 (캐시 히트) | 3~8초 | 0.01~0.05초 |
| asset-history API | 2~5초 | 0.1~0.3초 |
| 부동산 페이지 (5건) | 0.5~1초 | 0.05~0.1초 |

---

## 4. 구현 순서 및 난이도

```
STEP 1-A: UptimeRobot 설정       ⭐  10분   → 콜드 스타트 즉시 해결
STEP 1-B: 인덱스 추가 (SQL 실행) ⭐  10분   → 인덱스 기반 쿼리 가속
STEP 2:   커넥션 풀링             ⭐⭐  30분  → 연결 오버헤드 제거
STEP 3-C: _re_enrich N+1 제거   ⭐⭐  30분  → 부동산 조회 가속
STEP 3-D: to_char → 날짜 범위    ⭐⭐  1시간 → 인덱스 실제 활용
STEP 4:   Flask-Caching 적용     ⭐⭐  1시간 → 반복 조회 캐시
STEP 3-A: tech-tree 쿼리 병합    ⭐⭐⭐ 2시간 → 핵심 병목 제거
STEP 3-B: asset-history 병합     ⭐⭐⭐ 2시간 → 루프 쿼리 제거
```

> **빠른 효과 우선 순서**: 1-A → 1-B → 2 → 4 → 3-C → 3-D → 3-A → 3-B

---

## 5. requirements.txt 추가 항목

```
Flask-Caching>=2.1.0
psycopg2-binary>=2.9.0   # 이미 있을 가능성 높음
python-dateutil>=2.8.0   # relativedelta 사용 시
```
