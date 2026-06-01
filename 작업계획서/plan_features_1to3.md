# 기능 개선 통합 계획서 — #1 ~ #3

> **대상**: Flask + Supabase(PostgreSQL) 기반 자산관리 웹앱  
> **작성 기준**: 기존 `app.py` 코드 구조 분석 후 최소 변경 원칙으로 설계

---

## #1. 대시보드 — 일별 순자산 변화 차트 (선그래프 + 변동률 막대)

### 1-1. 현재 문제 진단

| 항목 | 현재 상태 | 필요 상태 |
|------|-----------|-----------|
| 데이터 저장 | `asset_snapshots` — **월별(YYYY-MM)** 스냅샷만 존재 | **일별** 스냅샷 테이블 필요 |
| 저장 시점 | `/api/tech-tree-data` 호출 시에만 월별 upsert | 대시보드 조회 시에도 오늘 날짜 일별 저장 |
| 차트 | 없음 | Chart.js 이중 Y축 (선 + 막대) |
| 기간 선택 | 없음 | 일간 90일 / 주간 52주 / 월간 24개월 / 연간 5년 |

---

### 1-2. DB 변경 — `daily_snapshots` 테이블 신규 생성

**Supabase SQL Editor에서 실행:**

```sql
CREATE TABLE IF NOT EXISTS daily_snapshots (
    id          SERIAL PRIMARY KEY,
    day         DATE    NOT NULL,
    cash        BIGINT  DEFAULT 0,
    stocks      BIGINT  DEFAULT 0,
    real_estate BIGINT  DEFAULT 0,
    crypto      BIGINT  DEFAULT 0,
    pension     BIGINT  DEFAULT 0,
    total       BIGINT  DEFAULT 0,   -- 자산 합계 (대출 미차감)
    net_worth   BIGINT  DEFAULT 0,   -- 순자산 (자산 - 대출)
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT daily_snapshots_day_unique UNIQUE (day)
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_daily_snapshots_day ON daily_snapshots (day);
```

---

### 1-3. 백엔드 변경 (`app.py`)

#### ① 일별 스냅샷 저장 헬퍼 함수 추가

```python
def _save_daily_snapshot(db):
    """
    오늘 날짜의 순자산을 계산해 daily_snapshots에 upsert.
    api_dashboard() 끝에서 호출하여 매일 1회 자동 기록.
    """
    today_str = date.today().isoformat()

    # ── 자산 집계 (tech-tree-data와 동일 로직을 1 CTE로 처리) ──
    cur = db.cursor()
    cur.execute("""
        SELECT
            COALESCE((SELECT SUM(amount) FROM cash_deposits), 0)
            + COALESCE((SELECT SUM(current_amount) FROM goals WHERE name != '자본주의테크트리'), 0)
                AS cash,
            COALESCE((
                SELECT SUM(s.current_price *
                    COALESCE((SELECT SUM(CASE WHEN tx_type='buy' THEN quantity ELSE -quantity END)
                              FROM stock_tx WHERE stock_id=s.id), 0))
                FROM stocks s
            ), 0)
            + COALESCE((SELECT SUM(current_price * quantity) FROM etf), 0)
                AS stocks,
            COALESCE((SELECT SUM(current_price) FROM real_estate), 0)
            - COALESCE((SELECT SUM(deposit) FROM tenant_contracts
                        WHERE id IN (SELECT MAX(id) FROM tenant_contracts GROUP BY real_estate_id)), 0)
            + COALESCE((SELECT SUM(deposit) FROM residence), 0)
                AS real_estate,
            COALESCE((SELECT SUM(current_price * quantity) FROM crypto), 0)
                AS crypto,
            COALESCE((SELECT SUM(accumulated) FROM pension), 0)
                AS pension,
            COALESCE((SELECT SUM(remaining) FROM loans), 0)
                AS loans
    """)
    row = cur.fetchone()
    cur.close()

    total     = (row['cash'] + row['stocks'] + row['real_estate']
                 + row['crypto'] + row['pension'])
    net_worth = total - row['loans']

    cur = db.cursor()
    cur.execute("""
        INSERT INTO daily_snapshots
            (day, cash, stocks, real_estate, crypto, pension, total, net_worth, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (day) DO UPDATE SET
            cash=excluded.cash, stocks=excluded.stocks,
            real_estate=excluded.real_estate, crypto=excluded.crypto,
            pension=excluded.pension, total=excluded.total,
            net_worth=excluded.net_worth, updated_at=excluded.updated_at
    """, (today_str, row['cash'], row['stocks'], row['real_estate'],
          row['crypto'], row['pension'], total, net_worth))
    cur.close()
```

#### ② `api_dashboard()` 끝 부분에 호출 추가

```python
@app.route('/api/dashboard')
def api_dashboard():
    db = get_db()
    # ... 기존 코드 전체 유지 ...

    # ── [추가] 오늘 일별 스냅샷 저장 ──
    try:
        _save_daily_snapshot(db)
        db.commit()
    except Exception as e:
        pass  # 스냅샷 저장 실패가 메인 응답에 영향을 주지 않도록

    db.close()
    return jsonify({ ... })  # 기존 응답 그대로
```

#### ③ 신규 API: `/api/networth-history`

```python
@app.route('/api/networth-history')
def api_networth_history():
    """
    순자산 변화 이력 반환.

    period 파라미터:
      daily   → 최근 90일  (daily_snapshots)
      weekly  → 최근 52주, 주의 마지막 기록 (daily_snapshots)
      monthly → 최근 24개월 (asset_snapshots)
      yearly  → 최근 5년   (asset_snapshots, 연도별 마지막 월)
    """
    period = request.args.get('period', 'monthly')
    db     = get_db()
    cur    = db.cursor()

    if period == 'daily':
        cur.execute("""
            SELECT
                day::text                                          AS label,
                net_worth,
                net_worth - LAG(net_worth) OVER (ORDER BY day)    AS change_amt,
                ROUND(
                    (net_worth - LAG(net_worth) OVER (ORDER BY day))::numeric
                    / NULLIF(LAG(net_worth) OVER (ORDER BY day), 0) * 100, 2
                )                                                  AS change_pct
            FROM daily_snapshots
            WHERE day >= CURRENT_DATE - INTERVAL '90 days'
            ORDER BY day
        """)

    elif period == 'weekly':
        # ISO 주(week) 기준 마지막 기록 추출
        cur.execute("""
            WITH ranked AS (
                SELECT *,
                       DATE_TRUNC('week', day)::date AS week_start,
                       ROW_NUMBER() OVER (
                           PARTITION BY DATE_TRUNC('week', day) ORDER BY day DESC
                       ) AS rn
                FROM daily_snapshots
                WHERE day >= CURRENT_DATE - INTERVAL '52 weeks'
            )
            SELECT
                week_start::text                                         AS label,
                net_worth,
                net_worth - LAG(net_worth) OVER (ORDER BY week_start)   AS change_amt,
                ROUND(
                    (net_worth - LAG(net_worth) OVER (ORDER BY week_start))::numeric
                    / NULLIF(LAG(net_worth) OVER (ORDER BY week_start), 0) * 100, 2
                )                                                         AS change_pct
            FROM ranked
            WHERE rn = 1
            ORDER BY week_start
        """)

    elif period == 'monthly':
        cur.execute("""
            SELECT
                month                                                   AS label,
                (cash + stocks + real_estate + crypto + pension)        AS net_worth,
                (cash + stocks + real_estate + crypto + pension)
                    - LAG(cash+stocks+real_estate+crypto+pension)
                      OVER (ORDER BY month)                             AS change_amt,
                ROUND(
                    ((cash+stocks+real_estate+crypto+pension)
                      - LAG(cash+stocks+real_estate+crypto+pension)
                        OVER (ORDER BY month))::numeric
                    / NULLIF(
                        LAG(cash+stocks+real_estate+crypto+pension)
                          OVER (ORDER BY month), 0) * 100, 2
                )                                                       AS change_pct
            FROM asset_snapshots
            ORDER BY month
            LIMIT 24
        """)

    elif period == 'yearly':
        # 각 연도의 마지막 월 스냅샷
        cur.execute("""
            WITH yearly AS (
                SELECT *,
                       LEFT(month, 4) AS yr,
                       ROW_NUMBER() OVER (
                           PARTITION BY LEFT(month, 4) ORDER BY month DESC
                       ) AS rn
                FROM asset_snapshots
            )
            SELECT
                yr                                                      AS label,
                (cash + stocks + real_estate + crypto + pension)        AS net_worth,
                (cash + stocks + real_estate + crypto + pension)
                    - LAG(cash+stocks+real_estate+crypto+pension)
                      OVER (ORDER BY yr)                                AS change_amt,
                ROUND(
                    ((cash+stocks+real_estate+crypto+pension)
                      - LAG(cash+stocks+real_estate+crypto+pension)
                        OVER (ORDER BY yr))::numeric
                    / NULLIF(
                        LAG(cash+stocks+real_estate+crypto+pension)
                          OVER (ORDER BY yr), 0) * 100, 2
                )                                                       AS change_pct
            FROM yearly
            WHERE rn = 1
            ORDER BY yr
            LIMIT 5
        """)

    rows = cur.fetchall()
    cur.close()
    db.close()

    # 전체 기간 요약값 계산
    valid = [r for r in rows if r['net_worth'] is not None]
    first_nw = valid[0]['net_worth']  if valid else 0
    last_nw  = valid[-1]['net_worth'] if valid else 0
    total_change     = last_nw - first_nw
    total_change_pct = round(total_change / first_nw * 100, 2) if first_nw else 0

    return jsonify({
        'rows': rows_to_list(rows),
        'summary': {
            'current':     last_nw,
            'change_amt':  total_change,
            'change_pct':  total_change_pct,
        }
    })
```

---

### 1-4. 프론트엔드 변경 (`dashboard.html` + `dashboard.js`)

#### HTML — 대시보드 최하단에 섹션 추가

```html
<!-- 기존 카드들 아래 맨 마지막에 추가 -->
<div class="card mt-4" id="networth-chart-card">
  <div class="card-header d-flex justify-content-between align-items-center flex-wrap gap-2">
    <h5 class="mb-0">📈 순자산 변화 추이</h5>
    <div class="btn-group btn-group-sm" id="nw-period-tabs" role="group">
      <button class="btn btn-outline-primary" data-period="daily">일간</button>
      <button class="btn btn-outline-primary" data-period="weekly">주간</button>
      <button class="btn btn-outline-primary active" data-period="monthly">월간</button>
      <button class="btn btn-outline-primary" data-period="yearly">연간</button>
    </div>
  </div>
  <div class="card-body">
    <!-- 요약 수치 3종 -->
    <div class="row text-center mb-3" id="nw-summary-row">
      <div class="col-4">
        <div class="text-muted small">현재 순자산</div>
        <div class="fw-bold fs-6" id="nw-current">-</div>
      </div>
      <div class="col-4">
        <div class="text-muted small">기간 변동액</div>
        <div class="fw-bold fs-6" id="nw-change-amt">-</div>
      </div>
      <div class="col-4">
        <div class="text-muted small">기간 변동률</div>
        <div class="fw-bold fs-6" id="nw-change-pct">-</div>
      </div>
    </div>
    <!-- 이중 Y축 캔버스 -->
    <div style="position:relative; height:280px;">
      <canvas id="networth-chart"></canvas>
    </div>
    <p class="text-muted small text-center mt-2 mb-0" id="nw-data-notice"></p>
  </div>
</div>
```

#### JavaScript — `dashboard.js` 하단에 추가

```javascript
// ── 순자산 변화 차트 ──────────────────────────────────────────
let nwChart = null;

// 기간 탭 클릭
document.querySelectorAll('#nw-period-tabs button').forEach(btn => {
  btn.addEventListener('click', function () {
    document.querySelectorAll('#nw-period-tabs button')
      .forEach(b => b.classList.remove('active'));
    this.classList.add('active');
    loadNetworthChart(this.dataset.period);
  });
});

async function loadNetworthChart(period) {
  try {
    const res  = await fetch(`/api/networth-history?period=${period}`);
    const data = await res.json();
    const rows = data.rows;

    // ── 요약 수치 업데이트 ──
    const s = data.summary;
    document.getElementById('nw-current').textContent    = formatKRW(s.current);
    const changeEl = document.getElementById('nw-change-amt');
    changeEl.textContent  = (s.change_amt >= 0 ? '+' : '') + formatKRW(s.change_amt);
    changeEl.style.color  = s.change_amt >= 0 ? '#2ecc71' : '#e74c3c';
    const pctEl = document.getElementById('nw-change-pct');
    pctEl.textContent = (s.change_pct >= 0 ? '+' : '') + s.change_pct + '%';
    pctEl.style.color = s.change_pct >= 0 ? '#2ecc71' : '#e74c3c';

    // 일간 데이터 부족 시 안내
    const noticeEl = document.getElementById('nw-data-notice');
    if (period === 'daily' && rows.length < 3) {
      noticeEl.textContent = '⚠️ 일간 데이터는 대시보드를 매일 조회할수록 누적됩니다.';
    } else {
      noticeEl.textContent = '';
    }

    const labels   = rows.map(r => r.label);
    const netWorth = rows.map(r => r.net_worth  || 0);
    const changePct= rows.map(r => r.change_pct || 0);

    // ── Chart.js 이중 Y축 ──
    if (nwChart) nwChart.destroy();
    const ctx = document.getElementById('networth-chart').getContext('2d');
    nwChart = new Chart(ctx, {
      data: {
        labels,
        datasets: [
          {
            // 선그래프: 순자산 잔액
            type: 'line',
            label: '순자산',
            data: netWorth,
            borderColor: '#3498db',
            backgroundColor: 'rgba(52,152,219,0.07)',
            fill: true,
            tension: 0.3,
            yAxisID: 'y',
            pointRadius: period === 'daily' ? 2 : 4,
            pointHoverRadius: 6,
            order: 1,
          },
          {
            // 막대그래프: 변동률(%)
            type: 'bar',
            label: '변동률(%)',
            data: changePct,
            backgroundColor: changePct.map(v =>
              v >= 0 ? 'rgba(46,204,113,0.55)' : 'rgba(231,76,60,0.55)'
            ),
            borderColor: changePct.map(v =>
              v >= 0 ? '#2ecc71' : '#e74c3c'
            ),
            borderWidth: 1,
            yAxisID: 'y1',
            order: 2,
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { position: 'top' },
          tooltip: {
            callbacks: {
              label: ctx => {
                if (ctx.dataset.yAxisID === 'y')
                  return `순자산: ${formatKRW(ctx.raw)}`;
                const sign = ctx.raw >= 0 ? '+' : '';
                return `변동률: ${sign}${ctx.raw?.toFixed(2)}%`;
              }
            }
          }
        },
        scales: {
          x: {
            ticks: {
              maxRotation: 45,
              // 일간은 레이블 많으므로 n개마다 1개만 표시
              callback: (val, idx) => {
                if (period === 'daily' && idx % 7 !== 0) return '';
                return labels[idx];
              }
            }
          },
          y: {
            type: 'linear', position: 'left',
            ticks: { callback: v => formatKRW(v) },
            title: { display: true, text: '순자산 (원)' }
          },
          y1: {
            type: 'linear', position: 'right',
            grid: { drawOnChartArea: false },
            ticks: { callback: v => v.toFixed(1) + '%' },
            title: { display: true, text: '변동률 (%)' }
          }
        }
      }
    });
  } catch (e) {
    console.error('순자산 차트 로딩 실패:', e);
  }
}

// 페이지 로드 시 월간 기본 실행
loadNetworthChart('monthly');
```

---

### 1-5. 데이터 누적 전략

| 상황 | 처리 방법 |
|------|-----------|
| 앱 첫 사용 시 daily 데이터 없음 | "데이터 누적 중" 안내 메시지 표시 |
| Render 무료 플랜 슬립 중 미접속 날 | 해당 일 스냅샷 없음 → 차트에 빈 구간 생략 처리 |
| monthly 데이터는 asset_snapshots 활용 | 기존 데이터 그대로 사용 가능 |
| 과거 데이터 일괄 보정 | `/api/networth-history?period=daily` 최초 호출 시 오늘 데이터부터 시작 |

---
---

## #2. 가계부 — 고정지출 자동 반복 등록

### 2-1. 현재 문제 진단

- `budget` 테이블에 `type` 컬럼이 있으나 반복 처리 로직 없음
- 수입(`income`)은 `is_recurring + repeat_months` 방식으로 **미래 날짜까지 사전 INSERT**하는 구조
- 가계부는 이 구조가 없어 고정지출을 매달 수동으로 재입력해야 함
- **핵심 조건**: 해당 날짜가 되기 전에는 가계부 목록에 표기되지 않아야 함

---

### 2-2. 설계 방향: 템플릿 테이블 방식

> **왜 사전 INSERT 방식이 아닌 템플릿 방식인가?**  
> 수입의 사전 INSERT 방식은 이미 `date <= CURRENT_DATE` 필터로 미래분을 숨기고 있음.  
> 그러나 가계부는 현재 이 필터가 없으며, 추가 시 기존 즉시 지출과의 구분이 복잡해짐.  
> 템플릿 방식은 "그달이 되면 자동 생성"하므로 조회 로직 변경이 최소화됨.

---

### 2-3. DB 변경

#### 신규 테이블: `recurring_budget` (고정지출 템플릿)

```sql
CREATE TABLE IF NOT EXISTS recurring_budget (
    id             SERIAL PRIMARY KEY,
    name           VARCHAR(200) NOT NULL,        -- 지출명 (예: "월세", "넷플릭스")
    category       VARCHAR(100),                 -- 카테고리
    payment_method VARCHAR(50),                  -- 결제수단
    amount         BIGINT NOT NULL DEFAULT 0,    -- 금액
    card_id        INTEGER REFERENCES card_info(id) ON DELETE SET NULL,
    day_of_month   INTEGER NOT NULL CHECK (day_of_month BETWEEN 1 AND 31),
                                                 -- 매월 몇 일에 발생 (31→말일 처리)
    start_month    VARCHAR(7) NOT NULL,           -- 적용 시작 월 'YYYY-MM'
    end_month      VARCHAR(7),                   -- 적용 종료 월 (NULL=무기한)
    memo           VARCHAR(500),
    is_active      BOOLEAN DEFAULT TRUE,         -- 활성/비활성 토글
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### `budget` 테이블에 컬럼 추가

```sql
-- 어느 템플릿에서 자동 생성된 항목인지 추적 (중복 생성 방지용)
ALTER TABLE budget ADD COLUMN IF NOT EXISTS
    recurring_id INTEGER REFERENCES recurring_budget(id) ON DELETE SET NULL;

-- 자동 생성된 항목임을 표시 (수동 삭제해도 다음달엔 재생성됨)
ALTER TABLE budget ADD COLUMN IF NOT EXISTS
    is_auto_generated BOOLEAN DEFAULT FALSE;
```

---

### 2-4. 백엔드 변경 (`app.py`)

#### ① 고정지출 템플릿 CRUD API

```python
# ── 고정지출 템플릿 관리 ──────────────────────────────────────
@app.route('/api/recurring-budget', methods=['GET', 'POST'])
def api_recurring_budget():
    db = get_db()
    if request.method == 'GET':
        cur = db.cursor()
        cur.execute("""
            SELECT r.*, c.card_name
            FROM recurring_budget r
            LEFT JOIN card_info c ON r.card_id = c.id
            ORDER BY r.day_of_month, r.name
        """)
        rows = cur.fetchall()
        cur.close(); db.close()
        return jsonify(rows_to_list(rows))

    d = request.json or {}
    cur = db.cursor()
    cur.execute("""
        INSERT INTO recurring_budget
            (name, category, payment_method, amount, card_id,
             day_of_month, start_month, end_month, memo)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (d.get('name'), d.get('category'), d.get('payment_method'),
          d.get('amount', 0), d.get('card_id') or None,
          d.get('day_of_month', 1), d.get('start_month'),
          d.get('end_month') or None, d.get('memo')))
    cur.close(); db.commit(); db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/recurring-budget/<int:rid>', methods=['PUT', 'DELETE'])
def api_recurring_budget_detail(rid):
    db = get_db()
    if request.method == 'DELETE':
        cur = db.cursor()
        cur.execute("UPDATE recurring_budget SET is_active=FALSE WHERE id=%s", (rid,))
        cur.close(); db.commit(); db.close()
        return jsonify({'ok': True})
    d = request.json or {}
    cur = db.cursor()
    cur.execute("""
        UPDATE recurring_budget
        SET name=%s, category=%s, payment_method=%s, amount=%s, card_id=%s,
            day_of_month=%s, start_month=%s, end_month=%s, memo=%s, is_active=%s
        WHERE id=%s
    """, (d.get('name'), d.get('category'), d.get('payment_method'),
          d.get('amount', 0), d.get('card_id') or None,
          d.get('day_of_month', 1), d.get('start_month'),
          d.get('end_month') or None, d.get('memo'),
          d.get('is_active', True), rid))
    cur.close(); db.commit(); db.close()
    return jsonify({'ok': True})
```

#### ② 핵심 함수: 고정지출 자동 생성

```python
import calendar as _cal

def _generate_recurring_budget(db, year: int, month: int):
    """
    지정한 연월에 대해 활성 템플릿을 조회하고,
    아직 생성되지 않은 고정지출 항목을 budget 테이블에 INSERT.

    규칙:
      1. 해당 월이 start_month~end_month 범위 내여야 함
      2. budget에 같은 (recurring_id, 해당월) 조합이 없어야 함 (중복 방지)
      3. day_of_month가 해당 월의 말일을 초과하면 말일로 보정
      4. 생성된 날짜가 오늘 이전인 경우에만 INSERT
         (해당 날짜가 오지 않은 건 생성은 하되 GET 조회 시 필터링)
    """
    ym_str  = f"{year}-{month:02d}"        # 예: '2025-06'
    today   = date.today()

    cur = db.cursor()
    cur.execute("""
        SELECT * FROM recurring_budget
        WHERE is_active = TRUE
          AND start_month <= %s
          AND (end_month IS NULL OR end_month >= %s)
    """, (ym_str, ym_str))
    templates = cur.fetchall()
    cur.close()

    inserted = 0
    for t in templates:
        # 실제 날짜 계산 (말일 초과 보정)
        max_day   = _cal.monthrange(year, month)[1]
        actual_day = min(t['day_of_month'], max_day)
        tx_date   = date(year, month, actual_day)

        # ── 핵심 조건: 해당 날짜가 오늘 이후면 생성하지 않음 ──
        if tx_date > today:
            continue

        # 이미 이 템플릿으로 해당 월에 생성된 항목이 있는지 확인
        cur = db.cursor()
        cur.execute("""
            SELECT id FROM budget
            WHERE recurring_id = %s
              AND to_char(date::date, 'YYYY-MM') = %s
        """, (t['id'], ym_str))
        already_exists = cur.fetchone()
        cur.close()

        if already_exists:
            continue  # 이미 생성됨 → 스킵

        # 새 budget 행 INSERT
        cur = db.cursor()
        cur.execute("""
            INSERT INTO budget
                (date, category, name, type, payment_method,
                 amount, memo, card_id, recurring_id, is_auto_generated)
            VALUES (%s, %s, %s, '지출', %s, %s, %s, %s, %s, TRUE)
            RETURNING id
        """, (tx_date.isoformat(), t['category'], t['name'],
              t['payment_method'], t['amount'], t['memo'],
              t['card_id'], t['id']))
        budget_id = cur.fetchone()[0]
        cur.close()

        # 카드 연동 처리 (기존 _sync_card_tx 활용)
        if t['card_id']:
            _sync_card_tx(db, budget_id, {
                'card_id':  t['card_id'],
                'date':     tx_date.isoformat(),
                'name':     t['name'],
                'category': t['category'],
                'amount':   t['amount'],
                'memo':     t['memo'],
            })

        inserted += 1

    if inserted > 0:
        db.commit()
    return inserted
```

#### ③ `api_budget()` GET 호출 시 자동 생성 트리거

```python
@app.route('/api/budget', methods=['GET', 'POST'])
def api_budget():
    db = get_db()
    if request.method == 'GET':
        year  = request.args.get('year')
        month = request.args.get('month')

        # ── [추가] 해당 연월의 고정지출 자동 생성 ──
        if year and month:
            try:
                _generate_recurring_budget(db, int(year), int(month))
            except Exception as e:
                pass  # 자동 생성 실패가 조회를 막지 않도록

        # 기존 조회 로직 그대로
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
    # POST는 기존 코드 그대로 ...
```

---

### 2-5. 프론트엔드 변경 (`budget.html`)

#### 고정지출 등록 모달 추가

```html
<!-- 가계부 페이지 상단 버튼에 추가 -->
<button class="btn btn-outline-secondary btn-sm" 
        data-bs-toggle="modal" data-bs-target="#recurringModal">
  🔁 고정지출 관리
</button>

<!-- 고정지출 관리 모달 -->
<div class="modal fade" id="recurringModal" tabindex="-1">
  <div class="modal-dialog modal-lg">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title">🔁 고정지출 템플릿 관리</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
      </div>
      <div class="modal-body">

        <!-- 등록 폼 -->
        <div class="card mb-3">
          <div class="card-body">
            <div class="row g-2">
              <div class="col-md-3">
                <input type="text" class="form-control form-control-sm"
                       id="rc-name" placeholder="지출명 (예: 월세, 넷플릭스)">
              </div>
              <div class="col-md-2">
                <select class="form-select form-select-sm" id="rc-category">
                  <option value="">카테고리</option>
                  <!-- 기존 카테고리 목록 동적 삽입 -->
                </select>
              </div>
              <div class="col-md-2">
                <input type="number" class="form-control form-control-sm"
                       id="rc-amount" placeholder="금액">
              </div>
              <div class="col-md-1">
                <input type="number" class="form-control form-control-sm"
                       id="rc-day" placeholder="일" min="1" max="31" title="매월 몇 일">
              </div>
              <div class="col-md-2">
                <input type="month" class="form-control form-control-sm"
                       id="rc-start-month" title="적용 시작 월">
              </div>
              <div class="col-md-2">
                <input type="month" class="form-control form-control-sm"
                       id="rc-end-month" placeholder="종료 월 (빈칸=무기한)">
              </div>
            </div>
            <div class="row g-2 mt-1">
              <div class="col-md-3">
                <select class="form-select form-select-sm" id="rc-card">
                  <option value="">카드 연결 (선택)</option>
                </select>
              </div>
              <div class="col-md-4">
                <input type="text" class="form-control form-control-sm"
                       id="rc-memo" placeholder="메모">
              </div>
              <div class="col-md-2">
                <button class="btn btn-primary btn-sm w-100"
                        onclick="addRecurring()">등록</button>
              </div>
            </div>
          </div>
        </div>

        <!-- 등록된 고정지출 목록 -->
        <table class="table table-sm table-hover">
          <thead class="table-dark">
            <tr>
              <th>지출명</th><th>금액</th><th>매월</th>
              <th>시작</th><th>종료</th><th>상태</th><th>관리</th>
            </tr>
          </thead>
          <tbody id="recurring-list-tbody"></tbody>
        </table>
      </div>
    </div>
  </div>
</div>
```

#### JavaScript 주요 로직

```javascript
// ── 고정지출 관리 ────────────────────────────────────────────

async function loadRecurringList() {
  const res  = await fetch('/api/recurring-budget');
  const data = await res.json();
  const tbody = document.getElementById('recurring-list-tbody');
  tbody.innerHTML = '';
  data.forEach(r => {
    tbody.insertAdjacentHTML('beforeend', `
      <tr class="${r.is_active ? '' : 'text-muted'}">
        <td>${r.name} <small class="text-muted">${r.category || ''}</small></td>
        <td class="text-end">${formatKRW(r.amount)}</td>
        <td class="text-center">매월 ${r.day_of_month}일</td>
        <td>${r.start_month}</td>
        <td>${r.end_month || '무기한'}</td>
        <td>
          <span class="badge ${r.is_active ? 'bg-success' : 'bg-secondary'}">
            ${r.is_active ? '활성' : '비활성'}
          </span>
        </td>
        <td>
          <button class="btn btn-xs btn-outline-warning"
                  onclick="toggleRecurring(${r.id}, ${!r.is_active})">
            ${r.is_active ? '중단' : '재개'}
          </button>
          <button class="btn btn-xs btn-outline-danger"
                  onclick="deleteRecurring(${r.id})">삭제</button>
        </td>
      </tr>
    `);
  });
}

async function addRecurring() {
  const payload = {
    name:           document.getElementById('rc-name').value.trim(),
    category:       document.getElementById('rc-category').value,
    amount:         parseInt(document.getElementById('rc-amount').value || 0),
    day_of_month:   parseInt(document.getElementById('rc-day').value || 1),
    start_month:    document.getElementById('rc-start-month').value,
    end_month:      document.getElementById('rc-end-month').value || null,
    card_id:        document.getElementById('rc-card').value || null,
    memo:           document.getElementById('rc-memo').value.trim(),
    payment_method: document.getElementById('rc-card').value ? '카드' : '기타',
  };
  if (!payload.name || !payload.amount || !payload.start_month) {
    alert('지출명, 금액, 시작 월은 필수입니다.'); return;
  }
  await fetch('/api/recurring-budget', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload)
  });
  loadRecurringList();
}

// 가계부 목록 조회 시 (기존 loadBudget 함수에 통합)
// → api_budget GET 호출 시 서버가 자동으로 고정지출을 생성하므로
//   프론트는 기존 조회 로직 그대로 유지
```

---

### 2-6. 동작 흐름

```
사용자가 고정지출 등록 (예: "월세 80만원, 매월 5일, 2025-05~무기한")
           │
           ▼
recurring_budget 테이블에 템플릿 저장

매월 5일이 지난 후 가계부 페이지 진입 (예: 2025-06-06 접속)
           │
           ▼
api_budget GET → _generate_recurring_budget(2025, 6) 호출
           │
           ▼
"2025-06-05가 오늘(6일) 이전? YES"
           │
           ▼
budget 테이블에 2025-06-05 자 "월세" 80만원 자동 INSERT
  (is_auto_generated=TRUE, recurring_id=해당 id)
           │
           ▼
기존 조회 로직 실행 → 화면에 표시됨

5일이 지나지 않은 상태 (예: 2025-06-03 접속)
           │
           ▼
tx_date(2025-06-05) > today(2025-06-03) → INSERT 건너뜀
           │
           ▼
해당 월 고정지출 목록에 표시되지 않음 ✓
```

---
---

## #3. 투자관리 — 종목별 분할매수 계획 (상단 매수가 기준)

### 3-1. 현재 문제 진단

기존 이전 계획서(`#1 — 지수투자 분할매수 계획기`)에서 제안한 방식은  
**현재가(current_price)** 또는 **전고점** 기준으로 하락률을 계산.

**문제**: 주식이 전고점 대비 이미 크게 하락한 경우,  
전고점 기준으로 `-20%` 등을 계산하면 현재가와 괴리가 심해 실용성이 없음.

**해결**: 사용자가 직접 **"이 가격 이하에서 사겠다"는 상단 매수가** 를 지정하고,  
그 가격을 기준으로 `+X% ~ -Y%` 범위에서 N차 분할매수 계획을 수립.

---

### 3-2. 설계 개념

```
상단 매수가(target_price): 사용자가 판단한 "적정 진입 상한선"
  예) 삼성전자 현재가 53,000원 → 상단 매수가 60,000원 설정

분할매수 범위: +X% ~ -Y%  (상단 매수가 기준 위/아래)
  예) +0% ~ -20% → 60,000원 ~ 48,000원 구간에서 N차 매수

분할 횟수: N (기본 5차)

배분 전략:
  - 균등: 각 차수 동일 금액
  - 역피라미딩: 하락할수록 더 많이 (하락 방어 전략)
  - 정피라미딩: 하락할수록 적게 (추세 추종 전략)
```

---

### 3-3. DB 변경

#### 신규 테이블: `invest_plans` (종목별 분할매수 계획)

```sql
CREATE TABLE IF NOT EXISTS invest_plans (
    id              SERIAL PRIMARY KEY,
    -- 연결 대상 (주식 또는 ETF 중 하나)
    stock_id        INTEGER REFERENCES stocks(id)  ON DELETE CASCADE,
    etf_id          INTEGER REFERENCES etf(id)     ON DELETE CASCADE,

    plan_name       VARCHAR(100),               -- 계획명 (예: "삼성전자 1차 계획")
    target_price    BIGINT  NOT NULL,           -- 상단 매수가 (기준가)
    upper_pct       NUMERIC(5,2) DEFAULT 0,     -- 상단 여유 % (기본 0% = 상단 매수가 자체)
    lower_pct       NUMERIC(5,2) DEFAULT 20,    -- 하단 범위 % (예: 20 → -20%까지)
    split_count     INTEGER DEFAULT 5,          -- 분할 횟수
    total_budget    BIGINT  DEFAULT 0,          -- 총 투자 예산
    strategy        VARCHAR(20) DEFAULT 'inverse_pyramid',
                                                -- 'equal' | 'inverse_pyramid' | 'pyramid'
    status          VARCHAR(20) DEFAULT 'active',
                                                -- 'active' | 'completed' | 'cancelled'
    memo            VARCHAR(300),
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 각 차수별 실행 기록 (실제 매수 체결 여부 추적)
CREATE TABLE IF NOT EXISTS invest_plan_steps (
    id          SERIAL PRIMARY KEY,
    plan_id     INTEGER NOT NULL REFERENCES invest_plans(id) ON DELETE CASCADE,
    step_no     INTEGER NOT NULL,               -- 차수 (1, 2, 3 ...)
    trigger_price BIGINT NOT NULL,              -- 해당 차수 트리거 가격
    target_amount BIGINT NOT NULL,              -- 해당 차수 투자 예정금
    target_shares NUMERIC(12,4),               -- 해당 차수 예정 주수
    weight_pct  NUMERIC(5,2),                  -- 전체 예산 대비 비중(%)
    -- 실제 체결 정보 (매수 완료 시 기록)
    executed_at DATE,                           -- 실제 매수 날짜
    executed_price BIGINT,                      -- 실제 체결 가격
    executed_shares NUMERIC(12,4),             -- 실제 매수 주수
    executed_amount BIGINT,                     -- 실제 매수 금액
    is_executed BOOLEAN DEFAULT FALSE           -- 체결 완료 여부
);
```

---

### 3-4. 백엔드 변경 (`app.py`)

#### ① 분할매수 계획 계산 + 저장 API

```python
@app.route('/api/invest-plans', methods=['GET', 'POST'])
def api_invest_plans():
    db = get_db()
    if request.method == 'GET':
        cur = db.cursor()
        cur.execute("""
            SELECT p.*,
                   s.name AS stock_name, s.ticker AS stock_ticker,
                   e.name AS etf_name,   e.ticker AS etf_ticker,
                   s.current_price AS stock_current_price,
                   e.current_price AS etf_current_price
            FROM invest_plans p
            LEFT JOIN stocks s ON p.stock_id = s.id
            LEFT JOIN etf    e ON p.etf_id   = e.id
            ORDER BY p.created_at DESC
        """)
        rows = cur.fetchall(); cur.close()

        # 각 계획의 steps와 현재가 대비 진행상황 추가
        result = []
        for row in rows:
            r = dict(row)
            cur = db.cursor()
            cur.execute("""
                SELECT * FROM invest_plan_steps
                WHERE plan_id = %s ORDER BY step_no
            """, (row['id'],))
            r['steps'] = rows_to_list(cur.fetchall())
            cur.close()

            # 체결된 차수 수 / 총 차수
            r['executed_count']  = sum(1 for s in r['steps'] if s['is_executed'])
            r['total_steps']     = len(r['steps'])
            r['executed_amount'] = sum(s['executed_amount'] or 0
                                       for s in r['steps'] if s['is_executed'])
            # 현재가
            r['current_price'] = (row['stock_current_price']
                                  or row['etf_current_price'] or 0)
            result.append(r)

        db.close()
        return jsonify(result)

    # ── POST: 계획 생성 + steps 자동 계산 ──
    d = request.json or {}
    target_price = int(d.get('target_price', 0))
    upper_pct    = float(d.get('upper_pct',  0))
    lower_pct    = float(d.get('lower_pct',  20))
    split_count  = int(d.get('split_count',  5))
    total_budget = int(d.get('total_budget', 0))
    strategy     = d.get('strategy', 'inverse_pyramid')

    if not target_price or not total_budget:
        return jsonify({'error': '상단 매수가와 총 예산은 필수입니다.'}), 400

    # ── 차수별 트리거 가격 및 투자금 계산 ──
    steps_data = _calc_invest_plan_steps(
        target_price, upper_pct, lower_pct,
        split_count, total_budget, strategy
    )

    cur = db.cursor()
    cur.execute("""
        INSERT INTO invest_plans
            (stock_id, etf_id, plan_name, target_price, upper_pct, lower_pct,
             split_count, total_budget, strategy, memo)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
    """, (d.get('stock_id') or None, d.get('etf_id') or None,
          d.get('plan_name', ''), target_price, upper_pct, lower_pct,
          split_count, total_budget, strategy, d.get('memo', '')))
    plan_id = cur.fetchone()[0]
    cur.close()

    for step in steps_data:
        cur = db.cursor()
        cur.execute("""
            INSERT INTO invest_plan_steps
                (plan_id, step_no, trigger_price, target_amount, target_shares, weight_pct)
            VALUES (%s,%s,%s,%s,%s,%s)
        """, (plan_id, step['step_no'], step['trigger_price'],
              step['amount'], step['shares'], step['weight_pct']))
        cur.close()

    db.commit(); db.close()
    return jsonify({'ok': True, 'plan_id': plan_id, 'steps': steps_data}), 201


def _calc_invest_plan_steps(target_price, upper_pct, lower_pct,
                             split_count, total_budget, strategy):
    """
    상단 매수가 기준으로 분할매수 차수를 계산.

    예: target=60,000 / upper=0% / lower=20% / 5차
      1차: 60,000원 (0%)
      2차: 57,000원 (-5%)
      3차: 54,000원 (-10%)
      4차: 51,000원 (-15%)
      5차: 48,000원 (-20%)

    전략별 배분:
      equal:           [20%, 20%, 20%, 20%, 20%]
      inverse_pyramid: 하락할수록 비중↑ (역피라미딩)
      pyramid:         하락할수록 비중↓ (정피라미딩 / 추세추종)
    """
    # 각 차수의 하락률 균등 분배
    # upper_pct는 상단 여유 (보통 0), lower_pct는 최대 하락
    total_range = upper_pct + lower_pct   # 전체 범위 %
    step_pct    = total_range / (split_count - 1) if split_count > 1 else 0

    # 각 차수의 기준가 대비 하락률 (양수 = 상단매수가 위, 음수 = 아래)
    pct_points = [upper_pct - step_pct * i for i in range(split_count)]

    # 배분 가중치 결정
    if strategy == 'equal':
        weights = [1.0] * split_count

    elif strategy == 'inverse_pyramid':
        # 1.0, 1.5, 2.25, 3.375, 5.0625 ... (1.5배씩 증가)
        raw = [1.0 * (1.5 ** i) for i in range(split_count)]
        total_w = sum(raw)
        weights = [w / total_w for w in raw]

    elif strategy == 'pyramid':
        # 반대: 처음에 많이, 갈수록 적게
        raw = [1.0 * (1.5 ** i) for i in range(split_count - 1, -1, -1)]
        total_w = sum(raw)
        weights = [w / total_w for w in raw]

    else:
        weights = [1.0 / split_count] * split_count

    steps = []
    cumulative = 0
    for i, (pct, weight) in enumerate(zip(pct_points, weights)):
        # 트리거 가격: 상단 매수가 기준 pct% 위/아래
        trigger_price = round(target_price * (1 + pct / 100))
        amount        = round(total_budget * weight)
        shares        = round(amount / trigger_price, 4) if trigger_price > 0 else 0
        cumulative   += amount

        steps.append({
            'step_no':       i + 1,
            'pct_from_target': round(pct, 1),           # 상단 매수가 대비 %
            'trigger_price': trigger_price,
            'weight_pct':    round(weight * 100, 1),
            'amount':        amount,
            'shares':        shares,
            'cumulative':    cumulative,
            'label':         (f"+{pct:.1f}%" if pct > 0
                              else f"{pct:.1f}%" if pct < 0
                              else "상단 매수가"),
        })

    # 평균 단가 (전량 매수 가정)
    total_shares = sum(s['shares'] for s in steps)
    avg_price    = round(total_budget / total_shares) if total_shares > 0 else 0
    return steps
```

#### ② 차수별 체결 기록 API

```python
@app.route('/api/invest-plan-steps/<int:step_id>/execute', methods=['POST'])
def api_invest_plan_step_execute(step_id):
    """특정 차수 매수 체결 기록"""
    d = request.json or {}
    db = get_db()
    cur = db.cursor()
    cur.execute("""
        UPDATE invest_plan_steps
        SET is_executed=TRUE,
            executed_at=%s, executed_price=%s,
            executed_shares=%s, executed_amount=%s
        WHERE id=%s
    """, (d.get('executed_at', date.today().isoformat()),
          d.get('executed_price'), d.get('executed_shares'),
          d.get('executed_amount'), step_id))
    cur.close(); db.commit(); db.close()
    return jsonify({'ok': True})


@app.route('/api/invest-plan-steps/<int:step_id>/execute', methods=['DELETE'])
def api_invest_plan_step_unexecute(step_id):
    """체결 기록 취소"""
    db = get_db()
    cur = db.cursor()
    cur.execute("""
        UPDATE invest_plan_steps
        SET is_executed=FALSE, executed_at=NULL,
            executed_price=NULL, executed_shares=NULL, executed_amount=NULL
        WHERE id=%s
    """, (step_id,))
    cur.close(); db.commit(); db.close()
    return jsonify({'ok': True})
```

---

### 3-5. 프론트엔드 (`investments.html`)

#### 계획 생성 폼

```html
<!-- 투자관리 탭 내 "종목별 투자계획" 섹션 -->
<div class="card mt-4">
  <div class="card-header d-flex justify-content-between">
    <h6 class="mb-0">📋 종목별 분할매수 계획</h6>
    <button class="btn btn-primary btn-sm" onclick="showPlanForm()">+ 새 계획</button>
  </div>
  <div class="card-body" id="plan-form-area" style="display:none">
    <div class="row g-2">
      <div class="col-md-3">
        <label class="form-label">종목 선택</label>
        <select class="form-select form-select-sm" id="plan-stock-select">
          <option value="">-- 주식/ETF 선택 --</option>
        </select>
      </div>
      <div class="col-md-2">
        <label class="form-label">
          상단 매수가 (원)
          <span class="text-muted small" 
                data-bs-toggle="tooltip"
                title="'이 가격 이하에서 사겠다'는 기준 가격. 현재가보다 낮게 설정 가능.">
            ℹ️
          </span>
        </label>
        <input type="number" class="form-control form-control-sm"
               id="plan-target-price" placeholder="예: 60000">
        <div class="form-text" id="plan-current-price-hint"></div>
      </div>
      <div class="col-md-2">
        <label class="form-label">총 예산 (원)</label>
        <input type="number" class="form-control form-control-sm"
               id="plan-budget" placeholder="예: 5000000">
      </div>
      <div class="col-md-2">
        <label class="form-label">범위 하단 (%) ↓</label>
        <input type="number" class="form-control form-control-sm"
               id="plan-lower-pct" value="20" min="1" max="80"
               placeholder="상단가 기준 최대 하락 %">
        <div class="form-text">상단 매수가 기준 -X%까지</div>
      </div>
      <div class="col-md-1">
        <label class="form-label">분할 횟수</label>
        <input type="number" class="form-control form-control-sm"
               id="plan-split" value="5" min="2" max="10">
      </div>
      <div class="col-md-2">
        <label class="form-label">배분 전략</label>
        <select class="form-select form-select-sm" id="plan-strategy">
          <option value="inverse_pyramid">역피라미딩 (하락 시 더 많이)</option>
          <option value="equal">균등 배분</option>
          <option value="pyramid">정피라미딩 (초반에 많이)</option>
        </select>
      </div>
    </div>
    <div class="row g-2 mt-1">
      <div class="col-md-4">
        <input type="text" class="form-control form-control-sm"
               id="plan-name" placeholder="계획명 (예: 삼성전자 25년 1분기 분할매수)">
      </div>
      <div class="col-md-4">
        <input type="text" class="form-control form-control-sm"
               id="plan-memo" placeholder="메모">
      </div>
      <div class="col-md-2">
        <button class="btn btn-success btn-sm w-100"
                onclick="previewPlan()">미리보기</button>
      </div>
      <div class="col-md-2">
        <button class="btn btn-primary btn-sm w-100"
                onclick="savePlan()">저장</button>
      </div>
    </div>

    <!-- 미리보기 결과 -->
    <div id="plan-preview" class="mt-3" style="display:none">
      <div class="d-flex gap-2 mb-2 flex-wrap" id="plan-preview-summary"></div>
      <div class="table-responsive">
        <table class="table table-sm table-bordered table-hover">
          <thead class="table-dark">
            <tr>
              <th>차수</th>
              <th>상단가 대비</th>
              <th>트리거 가격</th>
              <th>현재가 대비</th>
              <th>비중</th>
              <th>투자금</th>
              <th>매수 주수</th>
              <th>누적 투자금</th>
            </tr>
          </thead>
          <tbody id="plan-preview-tbody"></tbody>
        </table>
      </div>
    </div>
  </div>
</div>
```

#### 계획 목록 + 차수별 체결 관리

```html
<!-- 저장된 계획 목록 -->
<div id="saved-plans-area" class="mt-3">
  <!-- JS로 동적 렌더링 -->
</div>
```

#### JavaScript

```javascript
// ── 종목별 분할매수 계획 ──────────────────────────────────────

let previewSteps = [];  // 미리보기 후 저장 시 재사용

// 종목 선택 시 현재가 힌트 표시
document.getElementById('plan-stock-select').addEventListener('change', function () {
  const selected = stockList.find(s => s.id == this.value)
                || etfList.find(e => e.id == this.value);
  if (selected) {
    document.getElementById('plan-current-price-hint').textContent =
      `현재가: ${formatKRW(selected.current_price)}`;
    // 상단 매수가 자동 채우기 (수정 가능)
    document.getElementById('plan-target-price').value = selected.current_price;
  }
});

async function previewPlan() {
  const targetPrice = parseInt(document.getElementById('plan-target-price').value || 0);
  const budget      = parseInt(document.getElementById('plan-budget').value || 0);
  const lowerPct    = parseFloat(document.getElementById('plan-lower-pct').value || 20);
  const splitCount  = parseInt(document.getElementById('plan-split').value || 5);
  const strategy    = document.getElementById('plan-strategy').value;

  if (!targetPrice || !budget) {
    alert('상단 매수가와 총 예산을 입력하세요.'); return;
  }

  // API 호출로 계산
  const res  = await fetch('/api/invest-plans', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      // 미리보기용 임시 계산 (저장 안 함)
      // 별도 /api/invest-plan-preview 엔드포인트를 만드는 것이 깔끔하지만
      // 간소화를 위해 동일 API 활용 가능
      target_price: targetPrice,
      upper_pct: 0,
      lower_pct: lowerPct,
      split_count: splitCount,
      total_budget: budget,
      strategy,
      _preview_only: true  // 이 플래그가 있으면 DB 저장 없이 steps만 반환
    })
  });
  const data = await res.json();
  previewSteps = data.steps;
  renderPlanPreview(previewSteps, targetPrice, budget);
}

function renderPlanPreview(steps, targetPrice, budget) {
  // 요약
  const totalShares = steps.reduce((acc, s) => acc + s.shares, 0);
  const avgPrice    = Math.round(budget / totalShares);
  document.getElementById('plan-preview-summary').innerHTML = `
    <span class="badge bg-primary fs-6">총 예산: ${formatKRW(budget)}</span>
    <span class="badge bg-secondary fs-6">상단 매수가: ${formatKRW(targetPrice)}</span>
    <span class="badge bg-success fs-6">전량 체결 시 평균단가: ${formatKRW(avgPrice)}</span>
    <span class="badge bg-info text-dark fs-6">총 예상 주수: ${totalShares.toFixed(2)}주</span>
  `;

  // 테이블
  const tbody = document.getElementById('plan-preview-tbody');
  tbody.innerHTML = '';
  // 현재가 (선택한 종목)
  const selectedEl = document.getElementById('plan-stock-select');
  const selected = stockList.find(s => s.id == selectedEl.value)
                || etfList.find(e => e.id == selectedEl.value);
  const currentPrice = selected?.current_price || 0;

  steps.forEach(s => {
    const vsCurrentPct = currentPrice
      ? ((s.trigger_price - currentPrice) / currentPrice * 100).toFixed(1)
      : '-';
    const vsCurrentClass = parseFloat(vsCurrentPct) > 0 ? 'text-danger'
                         : parseFloat(vsCurrentPct) < 0 ? 'text-success' : '';
    tbody.insertAdjacentHTML('beforeend', `
      <tr>
        <td class="text-center fw-bold">${s.step_no}차</td>
        <td class="text-center ${s.pct_from_target < 0 ? 'text-success' : ''}">
          ${s.label}
        </td>
        <td class="text-end fw-bold">${formatKRW(s.trigger_price)}</td>
        <td class="text-center ${vsCurrentClass}">
          ${vsCurrentPct !== '-' ? vsCurrentPct + '%' : '-'}
        </td>
        <td class="text-center">${s.weight_pct}%</td>
        <td class="text-end">${formatKRW(s.amount)}</td>
        <td class="text-end">${s.shares}주</td>
        <td class="text-end text-muted">${formatKRW(s.cumulative)}</td>
      </tr>
    `);
  });

  document.getElementById('plan-preview').style.display = 'block';
}

async function loadSavedPlans() {
  const res   = await fetch('/api/invest-plans');
  const plans = await res.json();
  const area  = document.getElementById('saved-plans-area');
  area.innerHTML = '';

  plans.forEach(plan => {
    const stockName = plan.stock_name || plan.etf_name || '-';
    const progress  = `${plan.executed_count} / ${plan.total_steps}차 완료`;
    const progressPct = plan.total_steps
      ? Math.round(plan.executed_count / plan.total_steps * 100) : 0;

    const stepsHtml = plan.steps.map(s => `
      <tr class="${s.is_executed ? 'table-success' : ''}">
        <td>${s.step_no}차</td>
        <td>${formatKRW(s.trigger_price)}</td>
        <td>${formatKRW(s.target_amount)}</td>
        <td>${s.target_shares}주</td>
        <td>${s.is_executed
              ? `✅ ${s.executed_at} / ${formatKRW(s.executed_price)} / ${s.executed_shares}주`
              : `<button class="btn btn-xs btn-outline-success"
                         onclick="executeStep(${s.id}, ${s.trigger_price}, ${s.target_shares})">
                   체결 기록
                 </button>`}
        </td>
      </tr>
    `).join('');

    area.insertAdjacentHTML('beforeend', `
      <div class="card mb-3">
        <div class="card-header d-flex justify-content-between align-items-center">
          <div>
            <strong>${plan.plan_name || stockName + ' 분할매수 계획'}</strong>
            <span class="badge bg-secondary ms-2">${stockName}</span>
            <span class="badge bg-info text-dark ms-1">
              상단가: ${formatKRW(plan.target_price)}
            </span>
            <span class="badge bg-warning text-dark ms-1">
              -${plan.lower_pct}% / ${plan.split_count}차
            </span>
          </div>
          <span class="text-muted small">${progress}</span>
        </div>
        <div class="card-body p-2">
          <!-- 진행률 바 -->
          <div class="progress mb-2" style="height:6px">
            <div class="progress-bar bg-success" style="width:${progressPct}%"></div>
          </div>
          <div class="table-responsive">
            <table class="table table-sm mb-0">
              <thead><tr>
                <th>차수</th><th>트리거 가격</th>
                <th>투자금</th><th>예정 주수</th><th>상태</th>
              </tr></thead>
              <tbody>${stepsHtml}</tbody>
            </table>
          </div>
        </div>
      </div>
    `);
  });
}
```

---

### 3-6. 미리보기 예시

```
종목: 삼성전자 | 현재가: 53,000원 | 상단 매수가: 60,000원 | 예산: 10,000,000원
범위: 0% ~ -20% | 분할: 5차 | 전략: 역피라미딩

[총 예산: 1,000만원] [상단 매수가: 60,000원] [평균단가: 56,380원] [총 178주]

┌────┬──────────────┬────────────┬─────────────┬──────┬──────────┬────────┬──────────────┐
│차수│ 상단가 대비  │ 트리거가격  │  현재가 대비 │ 비중 │  투자금  │예정주수│   누적 투자금  │
├────┼──────────────┼────────────┼─────────────┼──────┼──────────┼────────┼──────────────┤
│ 1차│  상단 매수가  │  60,000원  │   +13.2% ↑  │  9.5%│  950,000 │  15.8주│     950,000 │
│ 2차│    -5.0%     │  57,000원  │    +7.5% ↑  │ 14.2%│1,420,000 │  24.9주│   2,370,000 │
│ 3차│   -10.0%     │  54,000원  │    +1.9% ↑  │ 21.3%│2,130,000 │  39.4주│   4,500,000 │
│ 4차│   -15.0%     │  51,000원  │    -3.8% ↓  │ 31.9%│3,190,000 │  62.5주│   7,690,000 │
│ 5차│   -20.0%     │  48,000원  │    -9.4% ↓  │ 23.1%│2,310,000 │  48.1주│  10,000,000 │
└────┴──────────────┴────────────┴─────────────┴──────┴──────────┴────────┴──────────────┘

💡 3차(54,000원)부터 현재가(53,000원) 이하로 진입
   → 현재 즉시 실행 가능한 차수: 3, 4, 5차
```

---

## 전체 구현 순서 및 난이도

| 번호 | 작업 항목 | 수정 파일 | 난이도 | 예상 시간 |
|------|----------|----------|--------|-----------|
| #1-DB | `daily_snapshots` 테이블 생성 | Supabase SQL | ⭐ | 5분 |
| #1-BE | `_save_daily_snapshot()` + `/api/networth-history` | `app.py` | ⭐⭐ | 1시간 |
| #1-FE | Chart.js 이중 Y축 차트 + 기간 탭 | `dashboard.html/js` | ⭐⭐ | 1시간 |
| #2-DB | `recurring_budget` 테이블 생성, `budget` 컬럼 추가 | Supabase SQL | ⭐ | 5분 |
| #2-BE | `_generate_recurring_budget()` + 템플릿 CRUD API | `app.py` | ⭐⭐⭐ | 2시간 |
| #2-FE | 고정지출 관리 모달 + 리스트 | `budget.html` | ⭐⭐ | 1시간 |
| #3-DB | `invest_plans`, `invest_plan_steps` 테이블 생성 | Supabase SQL | ⭐ | 5분 |
| #3-BE | 계획 계산/저장 + 체결 기록 API | `app.py` | ⭐⭐⭐ | 2시간 |
| #3-FE | 계획 생성 폼 + 미리보기 + 저장 목록 + 체결 기록 | `investments.html` | ⭐⭐⭐ | 2.5시간 |

> **권장 순서**: #2-DB → #2-BE → #2-FE → #1-DB → #1-BE → #1-FE → #3-DB → #3-BE → #3-FE  
> (체감 개선이 가장 빠른 #2 가계부 자동반복부터 시작 권장)
