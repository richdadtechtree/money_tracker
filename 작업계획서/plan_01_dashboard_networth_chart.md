# 기능 계획서 #1 — 대시보드 순자산 변화 그래프

> **목적**: 대시보드 최하단에 순자산의 일간·주간·월간·연간 변화를 선그래프(잔액)와 막대그래프(변동률)로 시각화한다.

---

## 1. 현황 분석

### 현재 구조
- `asset_snapshots` 테이블: **월별(YYYY-MM)** 스냅샷이 `/api/tech-tree-data` 호출 시 자동 upsert됨
- `/api/asset-history`: 최근 12개월 월별 자산 내역 반환
- 일별 데이터는 **현재 저장하지 않음** → 일·주간 차트 구현을 위해 테이블 추가 필요

### 문제점
| 구분 | 현재 | 필요 |
|------|------|------|
| 일간 | 저장 없음 | `daily_snapshots` 테이블 |
| 주간 | 없음 | daily 집계 |
| 월간 | `asset_snapshots` 존재 | 그대로 활용 가능 |
| 연간 | monthly 집계 가능 | monthly에서 12개월 집계 |

---

## 2. DB 변경 사항

### 신규 테이블: `daily_snapshots`

```sql
CREATE TABLE IF NOT EXISTS daily_snapshots (
    id          SERIAL PRIMARY KEY,
    day         DATE    NOT NULL UNIQUE,  -- YYYY-MM-DD (UNIQUE → upsert 기준)
    cash        BIGINT  DEFAULT 0,
    stocks      BIGINT  DEFAULT 0,
    real_estate BIGINT  DEFAULT 0,
    crypto      BIGINT  DEFAULT 0,
    pension     BIGINT  DEFAULT 0,
    total       BIGINT  DEFAULT 0,        -- 총자산 (대출 제외)
    net_worth   BIGINT  DEFAULT 0,        -- 순자산 (총자산 - 대출)
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

> **주의**: `total`은 자산 합계, `net_worth`는 자산 - 대출잔액. 그래프에는 `net_worth`를 메인으로 사용한다.

---

## 3. 백엔드 변경 사항 (`app.py`)

### 3-1. 일별 스냅샷 저장 함수 추가

```python
def _save_daily_snapshot(db):
    """
    오늘 날짜의 순자산을 계산하여 daily_snapshots에 upsert.
    대시보드 또는 tech-tree 조회 시 자동 호출되어 매일 1회 기록됨.
    """
    today_str = date.today().isoformat()

    # --- 자산 계산 (api_tech_tree_data와 동일한 로직) ---
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(s.current_price * (...)), 0) FROM stocks s")
    stocks_val = cur.fetchone()[0]; cur.close()
    # ... (ETF, 코인, 부동산, 현금, 연금 동일하게 집계)

    # 대출 잔액
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(remaining), 0) FROM loans")
    loan_total = cur.fetchone()[0]; cur.close()

    total = cash_val + stocks_val + re_val + crypto_val + pension_val
    net_worth = total - loan_total

    cur = db.cursor()
    cur.execute("""
        INSERT INTO daily_snapshots (day, cash, stocks, real_estate, crypto, pension, total, net_worth, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (day) DO UPDATE SET
            cash=excluded.cash, stocks=excluded.stocks,
            real_estate=excluded.real_estate, crypto=excluded.crypto,
            pension=excluded.pension, total=excluded.total,
            net_worth=excluded.net_worth, updated_at=excluded.updated_at
    """, (today_str, cash_val, stocks_val, re_val, crypto_val, pension_val, total, net_worth))
    cur.close()
```

- `api_dashboard()` 함수 끝, `db.close()` 직전에 `_save_daily_snapshot(db)` 호출 추가.
- `api_tech_tree_data()`에서 이미 monthly upsert를 하고 있으므로, 같은 위치에 daily도 함께 저장.

---

### 3-2. 신규 API: `/api/networth-history`

```python
@app.route('/api/networth-history')
def api_networth_history():
    """
    파라미터: period = 'daily' | 'weekly' | 'monthly' | 'yearly'
    - daily   → 최근 90일 (daily_snapshots)
    - weekly  → 최근 52주, 각 주의 마지막 기록 (daily_snapshots)
    - monthly → 최근 24개월 (asset_snapshots)
    - yearly  → 최근 5년, 각 연도 12월 기준 (asset_snapshots)
    """
    period = request.args.get('period', 'monthly')
    db = get_db()

    if period == 'daily':
        cur = db.cursor()
        cur.execute("""
            SELECT day, net_worth, total,
                   net_worth - LAG(net_worth) OVER (ORDER BY day) AS change,
                   ROUND(
                     (net_worth - LAG(net_worth) OVER (ORDER BY day))::numeric
                     / NULLIF(LAG(net_worth) OVER (ORDER BY day), 0) * 100, 2
                   ) AS change_pct
            FROM daily_snapshots
            WHERE day >= CURRENT_DATE - INTERVAL '90 days'
            ORDER BY day
        """)
        rows = cur.fetchall(); cur.close()

    elif period == 'weekly':
        # 각 주의 가장 마지막 기록(ISO week 기준)
        cur = db.cursor()
        cur.execute("""
            WITH weekly AS (
                SELECT *,
                       DATE_TRUNC('week', day) AS week_start,
                       ROW_NUMBER() OVER (PARTITION BY DATE_TRUNC('week', day) ORDER BY day DESC) AS rn
                FROM daily_snapshots
                WHERE day >= CURRENT_DATE - INTERVAL '52 weeks'
            )
            SELECT week_start::date AS day, net_worth, total,
                   net_worth - LAG(net_worth) OVER (ORDER BY week_start) AS change,
                   ROUND(
                     (net_worth - LAG(net_worth) OVER (ORDER BY week_start))::numeric
                     / NULLIF(LAG(net_worth) OVER (ORDER BY week_start), 0) * 100, 2
                   ) AS change_pct
            FROM weekly WHERE rn = 1
            ORDER BY week_start
        """)
        rows = cur.fetchall(); cur.close()

    elif period == 'monthly':
        cur = db.cursor()
        cur.execute("""
            SELECT month AS day,
                   (cash + stocks + real_estate + crypto + pension) AS net_worth,
                   total,
                   (cash + stocks + real_estate + crypto + pension)
                     - LAG(cash + stocks + real_estate + crypto + pension) OVER (ORDER BY month) AS change,
                   ROUND(
                     ((cash+stocks+real_estate+crypto+pension)
                       - LAG(cash+stocks+real_estate+crypto+pension) OVER (ORDER BY month))::numeric
                     / NULLIF(LAG(cash+stocks+real_estate+crypto+pension) OVER (ORDER BY month), 0) * 100, 2
                   ) AS change_pct
            FROM asset_snapshots
            ORDER BY month
            LIMIT 24
        """)
        rows = cur.fetchall(); cur.close()

    elif period == 'yearly':
        # 각 연도의 마지막 월 스냅샷 사용
        cur = db.cursor()
        cur.execute("""
            WITH yearly AS (
                SELECT *,
                       LEFT(month, 4) AS year,
                       ROW_NUMBER() OVER (PARTITION BY LEFT(month, 4) ORDER BY month DESC) AS rn
                FROM asset_snapshots
            )
            SELECT year AS day,
                   (cash + stocks + real_estate + crypto + pension) AS net_worth,
                   total,
                   ... -- 동일한 LAG 패턴
            FROM yearly WHERE rn = 1
            ORDER BY year
        """)
        rows = cur.fetchall(); cur.close()

    db.close()
    return jsonify(rows_to_list(rows))
```

---

## 4. 프론트엔드 변경 사항 (`dashboard.html` / `dashboard.js`)

### 4-1. HTML 구조 (대시보드 최하단에 섹션 추가)

```html
<!-- 대시보드 최하단 -->
<section class="card mt-4" id="networth-chart-section">
  <div class="card-header d-flex justify-content-between align-items-center">
    <h5 class="mb-0">📈 순자산 변화 추이</h5>
    <!-- 기간 선택 탭 -->
    <div class="btn-group btn-group-sm" role="group" id="period-tabs">
      <button class="btn btn-outline-primary active" data-period="daily">일간</button>
      <button class="btn btn-outline-primary" data-period="weekly">주간</button>
      <button class="btn btn-outline-primary" data-period="monthly">월간</button>
      <button class="btn btn-outline-primary" data-period="yearly">연간</button>
    </div>
  </div>
  <div class="card-body">
    <!-- 요약 지표 -->
    <div class="row mb-3 text-center" id="networth-summary">
      <div class="col-4">
        <div class="text-muted small">현재 순자산</div>
        <div class="fw-bold fs-5" id="nw-current">-</div>
      </div>
      <div class="col-4">
        <div class="text-muted small">기간 변동액</div>
        <div class="fw-bold fs-5" id="nw-change">-</div>
      </div>
      <div class="col-4">
        <div class="text-muted small">기간 변동률</div>
        <div class="fw-bold fs-5" id="nw-pct">-</div>
      </div>
    </div>
    <!-- 차트 캔버스 (이중 Y축: 좌=순자산 선, 우=변동률 막대) -->
    <div style="position:relative; height:300px;">
      <canvas id="networth-chart"></canvas>
    </div>
  </div>
</section>
```

### 4-2. JavaScript 로직 (`dashboard.js` 하단 추가)

```javascript
// ── 순자산 변화 차트 ──────────────────────────────────────
let networthChart = null;
let currentPeriod = 'monthly';

// 기간 탭 클릭 이벤트
document.querySelectorAll('#period-tabs button').forEach(btn => {
  btn.addEventListener('click', function () {
    document.querySelectorAll('#period-tabs button').forEach(b => b.classList.remove('active'));
    this.classList.add('active');
    currentPeriod = this.dataset.period;
    loadNetworthChart(currentPeriod);
  });
});

async function loadNetworthChart(period) {
  const res = await fetch(`/api/networth-history?period=${period}`);
  const data = await res.json();

  const labels    = data.map(d => d.day);
  const netWorths = data.map(d => d.net_worth);
  const changes   = data.map(d => d.change_pct || 0);

  // 요약 지표 업데이트
  const last = data[data.length - 1];
  const first = data[0];
  document.getElementById('nw-current').textContent = formatKRW(last?.net_worth);
  const totalChange = (last?.net_worth || 0) - (first?.net_worth || 0);
  const totalPct = first?.net_worth
    ? ((totalChange / first.net_worth) * 100).toFixed(2) + '%'
    : '-';
  document.getElementById('nw-change').textContent = formatKRW(totalChange);
  document.getElementById('nw-change').style.color = totalChange >= 0 ? '#2ecc71' : '#e74c3c';
  document.getElementById('nw-pct').textContent = totalPct;

  // Chart.js 이중 Y축 설정
  if (networthChart) networthChart.destroy();
  const ctx = document.getElementById('networth-chart').getContext('2d');
  networthChart = new Chart(ctx, {
    data: {
      labels,
      datasets: [
        {
          // 선그래프: 순자산 잔액
          type: 'line',
          label: '순자산',
          data: netWorths,
          borderColor: '#3498db',
          backgroundColor: 'rgba(52,152,219,0.08)',
          fill: true,
          tension: 0.3,
          yAxisID: 'y',
          pointRadius: period === 'daily' ? 2 : 4,
        },
        {
          // 막대그래프: 변동률
          type: 'bar',
          label: '변동률(%)',
          data: changes,
          backgroundColor: changes.map(v =>
            v >= 0 ? 'rgba(46,204,113,0.5)' : 'rgba(231,76,60,0.5)'
          ),
          yAxisID: 'y1',
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        tooltip: {
          callbacks: {
            label: ctx => {
              if (ctx.dataset.yAxisID === 'y') return `순자산: ${formatKRW(ctx.raw)}`;
              return `변동률: ${ctx.raw?.toFixed(2)}%`;
            }
          }
        }
      },
      scales: {
        y: {  // 좌측 Y축: 순자산 금액
          type: 'linear', position: 'left',
          ticks: { callback: v => formatKRW(v) }
        },
        y1: { // 우측 Y축: 변동률(%)
          type: 'linear', position: 'right',
          grid: { drawOnChartArea: false },
          ticks: { callback: v => v.toFixed(1) + '%' }
        }
      }
    }
  });
}

// 페이지 로드 시 월간으로 초기 렌더링
loadNetworthChart('monthly');
```

---

## 5. 구현 순서 (권장)

```
1단계: DB 마이그레이션
  └─ daily_snapshots 테이블 생성 (Supabase SQL Editor)

2단계: 백엔드
  ├─ _save_daily_snapshot() 헬퍼 함수 작성
  ├─ api_dashboard() 끝에 _save_daily_snapshot() 호출 추가
  └─ /api/networth-history 라우트 신규 작성

3단계: 프론트엔드
  ├─ dashboard.html에 섹션 HTML 추가
  └─ dashboard.js에 Chart.js 이중 Y축 코드 추가

4단계: 검증
  ├─ 대시보드 1회 조회 → daily_snapshots에 오늘 행 생성 확인
  └─ 4가지 기간 탭 전환 시 차트 정상 렌더링 확인
```

---

## 6. 예외 처리 & 주의사항

| 상황 | 처리 방법 |
|------|-----------|
| daily 데이터가 아직 없을 때 (신규 설치) | monthly 스냅샷으로 fallback하거나 "데이터 수집 중" 안내 |
| change_pct가 NULL인 첫 번째 행 | 0으로 처리하거나 막대 숨김 |
| 대출 잔액 변동이 없을 때 net_worth 계산 | loans.remaining이 없으면 0으로 COALESCE 처리 |
| 서버가 항상 켜져 있지 않을 때 (Render 무료 플랜 슬립) | 접속 시마다 당일 스냅샷 upsert이므로 자동 보정됨 |

---

## 7. 완성 UI 예시

```
┌──────────────────────────────────────────────────────────┐
│ 📈 순자산 변화 추이        [일간] [주간] [월간] [연간]  │
├──────────────────────────────────────────────────────────┤
│  현재 순자산       기간 변동액      기간 변동률          │
│  3억 2,400만원     +840만원         +2.67%               │
├──────────────────────────────────────────────────────────┤
│  ↑ 3.5억                              ↑ +5%              │
│  │  ╭────────────────────────╮ ▓▓ ░   │                  │
│  │  │ 선그래프(순자산 잔액)  │  ▓░    │                  │
│  │  ╰────────────────────────╯   ░    │                  │
│  ↓ 3.0억  ┴───────────────────────── ↓ -3%              │
└──────────────────────────────────────────────────────────┘
```
