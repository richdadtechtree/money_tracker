# 기능 계획서 #2 — 생애주기별 자산 투영 시뮬레이터

> **목적**: 내 나이와 가족 구성원을 입력하고, 현재 자산에서 출발해
> 연평균 유입속도·자산 매수/매도 이벤트를 반영하여 연도별 자산 추이를 시뮬레이션한다.

---

## 1. 기능 개요

```
[현재 자산] ──→ [연도별 시뮬레이션 테이블/차트]
      ↑                 ↑
  tech-tree API    유입속도 + 매수/매도 이벤트
```

### 핵심 컨셉
1. **나이 기준 타임라인**: 사용자 나이를 중심으로 연도가 흐르면서 가족 모두의 나이가 함께 증가
2. **기준 유입속도**: 기능 #1-1에서 개선된 연환산 평균 수입을 기본값으로 사용
3. **이벤트 레이어**: 특정 연도에 부동산 매도, 주식 매도, 자산 매수 등을 추가하면 그 효과가 시뮬레이션에 반영
4. **복리 성장 옵션**: 투자 자산에 연간 수익률을 적용해 복리 효과 시뮬레이션

---

## 2. DB 변경 사항

### 2-1. 신규 테이블: `lifecycle_profile` (가족 구성)

```sql
CREATE TABLE IF NOT EXISTS lifecycle_profile (
    id         SERIAL PRIMARY KEY,
    role       VARCHAR(20) NOT NULL,  -- 'me', 'spouse', 'child1', 'child2' 등
    name       VARCHAR(50),           -- 표시명 (예: "나", "배우자", "첫째")
    birth_year INTEGER NOT NULL,      -- 출생 연도 (나이 계산 기준)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 2-2. 신규 테이블: `lifecycle_events` (연도별 이벤트)

```sql
CREATE TABLE IF NOT EXISTS lifecycle_events (
    id          SERIAL PRIMARY KEY,
    event_year  INTEGER NOT NULL,     -- 이벤트 발생 연도 (예: 2028)
    event_type  VARCHAR(30) NOT NULL, -- 'sell_realestate', 'sell_stock', 'buy_asset',
                                      --  'extra_income', 'extra_expense', 'retire'
    asset_name  VARCHAR(100),         -- 대상 자산명 (예: "강남 아파트", "삼성전자")
    amount      BIGINT DEFAULT 0,     -- 금액 (매도 수익금 또는 비용)
    memo        VARCHAR(200),         -- 메모
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 2-3. 신규 테이블: `lifecycle_settings` (시뮬레이션 파라미터)

```sql
CREATE TABLE IF NOT EXISTS lifecycle_settings (
    id                   SERIAL PRIMARY KEY,
    sim_years            INTEGER DEFAULT 30,     -- 시뮬레이션 기간(년)
    annual_return_stocks NUMERIC(5,2) DEFAULT 7, -- 주식 연간 수익률(%)
    annual_return_re     NUMERIC(5,2) DEFAULT 3, -- 부동산 연간 상승률(%)
    annual_return_cash   NUMERIC(5,2) DEFAULT 2, -- 현금/예금 이자율(%)
    annual_expense_growth NUMERIC(5,2) DEFAULT 2,-- 연간 지출 증가율(인플레이션, %)
    override_annual_inflow BIGINT DEFAULT NULL,  -- 수동 유입속도 오버라이드 (NULL이면 자동)
    updated_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 기본값 1행 삽입
INSERT INTO lifecycle_settings DEFAULT VALUES;
```

---

## 3. 백엔드 변경 사항 (`app.py`)

### 3-1. 프로필 API

```python
# ── 가족 구성 ──────────────────────────────────────────────
@app.route('/api/lifecycle-profile', methods=['GET', 'POST'])
def api_lifecycle_profile():
    db = get_db()
    if request.method == 'GET':
        cur = db.cursor()
        cur.execute("SELECT * FROM lifecycle_profile ORDER BY id")
        rows = cur.fetchall(); cur.close(); db.close()
        return jsonify(rows_to_list(rows))
    d = request.json or {}
    cur = db.cursor()
    cur.execute(
        "INSERT INTO lifecycle_profile (role, name, birth_year) VALUES (%s,%s,%s)",
        (d.get('role'), d.get('name'), d.get('birth_year'))
    )
    cur.close(); db.commit(); db.close()
    return jsonify({'ok': True}), 201

@app.route('/api/lifecycle-profile/<int:rid>', methods=['PUT', 'DELETE'])
def api_lifecycle_profile_detail(rid):
    db = get_db()
    if request.method == 'DELETE':
        cur = db.cursor()
        cur.execute("DELETE FROM lifecycle_profile WHERE id=%s", (rid,))
        cur.close(); db.commit(); db.close()
        return jsonify({'ok': True})
    d = request.json or {}
    cur = db.cursor()
    cur.execute(
        "UPDATE lifecycle_profile SET role=%s, name=%s, birth_year=%s WHERE id=%s",
        (d.get('role'), d.get('name'), d.get('birth_year'), rid)
    )
    cur.close(); db.commit(); db.close()
    return jsonify({'ok': True})
```

### 3-2. 이벤트 API

```python
@app.route('/api/lifecycle-events', methods=['GET', 'POST'])
def api_lifecycle_events():
    db = get_db()
    if request.method == 'GET':
        cur = db.cursor()
        cur.execute("SELECT * FROM lifecycle_events ORDER BY event_year, id")
        rows = cur.fetchall(); cur.close(); db.close()
        return jsonify(rows_to_list(rows))
    d = request.json or {}
    cur = db.cursor()
    cur.execute(
        "INSERT INTO lifecycle_events (event_year, event_type, asset_name, amount, memo) "
        "VALUES (%s,%s,%s,%s,%s)",
        (d.get('event_year'), d.get('event_type'),
         d.get('asset_name'), d.get('amount', 0), d.get('memo'))
    )
    cur.close(); db.commit(); db.close()
    return jsonify({'ok': True}), 201

@app.route('/api/lifecycle-events/<int:rid>', methods=['PUT', 'DELETE'])
def api_lifecycle_events_detail(rid):
    # PUT/DELETE 표준 패턴 동일
    ...
```

### 3-3. 시뮬레이션 설정 API

```python
@app.route('/api/lifecycle-settings', methods=['GET', 'POST'])
def api_lifecycle_settings():
    db = get_db()
    if request.method == 'GET':
        cur = db.cursor()
        cur.execute("SELECT * FROM lifecycle_settings LIMIT 1")
        row = cur.fetchone(); cur.close(); db.close()
        return jsonify(dict(row) if row else {})
    d = request.json or {}
    cur = db.cursor()
    cur.execute("""
        UPDATE lifecycle_settings SET
            sim_years=%s, annual_return_stocks=%s, annual_return_re=%s,
            annual_return_cash=%s, annual_expense_growth=%s,
            override_annual_inflow=%s, updated_at=CURRENT_TIMESTAMP
        WHERE id=1
    """, (
        d.get('sim_years', 30), d.get('annual_return_stocks', 7),
        d.get('annual_return_re', 3), d.get('annual_return_cash', 2),
        d.get('annual_expense_growth', 2), d.get('override_annual_inflow')
    ))
    cur.close(); db.commit(); db.close()
    return jsonify({'ok': True})
```

### 3-4. 핵심: 시뮬레이션 계산 API

```python
@app.route('/api/lifecycle-simulate')
def api_lifecycle_simulate():
    """
    연도별 자산 투영 시뮬레이션.
    
    알고리즘:
      base_year = 현재 연도
      base_assets = 현재 자산 스냅샷
      annual_inflow = 연평균 유입속도 (수입 - 지출)
      
      for each year in [base_year .. base_year + sim_years]:
          1. 기본 자산 성장: 각 자산 × (1 + 수익률)
          2. 현금 유입: + annual_inflow
          3. 이벤트 반영: 매도 → 현금 증가, 매수 → 현금 감소
          4. 나이 계산: 모든 가족 구성원 나이 업데이트
          5. 스냅샷 저장
    """
    db = get_db()
    today = date.today()
    current_year = today.year

    # ── 1. 시뮬레이션 설정 로드 ──
    cur = db.cursor()
    cur.execute("SELECT * FROM lifecycle_settings LIMIT 1")
    settings = dict(cur.fetchone() or {}); cur.close()
    
    sim_years    = settings.get('sim_years', 30)
    r_stocks     = float(settings.get('annual_return_stocks', 7)) / 100
    r_re         = float(settings.get('annual_return_re', 3)) / 100
    r_cash       = float(settings.get('annual_return_cash', 2)) / 100
    exp_growth   = float(settings.get('annual_expense_growth', 2)) / 100
    override_inflow = settings.get('override_annual_inflow')

    # ── 2. 현재 자산 기준점 ──
    # tech-tree API와 동일한 계산 로직 사용
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(amount),0) FROM cash_deposits")
    base_cash = float(cur.fetchone()[0]); cur.close()
    
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(current_price * quantity),0) FROM etf")
    cur.execute("""SELECT COALESCE(SUM(s.current_price * (
        SELECT COALESCE(SUM(CASE WHEN tx_type='buy' THEN quantity ELSE -quantity END),0)
        FROM stock_tx WHERE stock_id=s.id)),0) FROM stocks s""")
    base_stocks = float(cur.fetchone()[0]); cur.close()
    
    # ... (ETF, 부동산, 코인, 연금 동일하게)

    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(remaining),0) FROM loans")
    base_loans = float(cur.fetchone()[0]); cur.close()

    # ── 3. 연평균 유입속도 (순유입: 수입 - 지출) ──
    if override_inflow:
        annual_net_inflow = float(override_inflow)
    else:
        avg = _calc_annual_avg_income(db)
        # 연간 지출 추정 (최근 12개월 월평균 × 12)
        cur = db.cursor()
        cur.execute("""
            SELECT COALESCE(AVG(monthly_exp),0) FROM (
                SELECT to_char(date::date,'YYYY-MM') as ym, SUM(amount) as monthly_exp
                FROM budget
                WHERE date >= CURRENT_DATE - INTERVAL '12 months'
                GROUP BY ym
            ) sub
        """)
        monthly_exp_avg = float(cur.fetchone()[0]); cur.close()
        
        cur = db.cursor()
        cur.execute("""
            SELECT COALESCE(AVG(monthly_card),0) FROM (
                SELECT to_char(date::date,'YYYY-MM') as ym, SUM(amount) as monthly_card
                FROM card_tx
                WHERE date >= CURRENT_DATE - INTERVAL '12 months'
                GROUP BY ym
            ) sub
        """)
        monthly_card_avg = float(cur.fetchone()[0]); cur.close()
        
        annual_expense_est = (monthly_exp_avg + monthly_card_avg) * 12
        annual_net_inflow = (avg['labor_annual'] + avg['passive_annual']) - annual_expense_est

    # ── 4. 이벤트 로드 ──
    cur = db.cursor()
    cur.execute("SELECT * FROM lifecycle_events ORDER BY event_year")
    events = cur.fetchall(); cur.close()
    event_map = {}  # {year: [events]}
    for e in events:
        yr = e['event_year']
        if yr not in event_map:
            event_map[yr] = []
        event_map[yr].append(dict(e))

    # ── 5. 가족 구성 ──
    cur = db.cursor()
    cur.execute("SELECT * FROM lifecycle_profile ORDER BY id")
    family = cur.fetchall(); cur.close()

    # ── 6. 연도별 시뮬레이션 루프 ──
    result = []
    
    cash    = base_cash
    stocks  = base_stocks
    re      = base_re
    crypto  = base_crypto
    pension = base_pension
    loans   = base_loans

    for i in range(sim_years + 1):  # 0 = 현재 연도
        year = current_year + i

        # 가족 나이 계산
        family_ages = [
            {
                'name': m['name'],
                'role': m['role'],
                'age':  year - m['birth_year']
            }
            for m in family
        ]

        # 이번 연도 이벤트 처리
        year_events = event_map.get(year, [])
        event_cash_delta = 0
        for evt in year_events:
            etype  = evt['event_type']
            amount = evt['amount']
            if etype == 'sell_realestate':
                re   -= amount       # 부동산 자산 감소
                cash += amount       # 현금 증가 (매도 수익)
                event_cash_delta += amount
            elif etype == 'sell_stock':
                stocks -= amount
                cash   += amount
                event_cash_delta += amount
            elif etype == 'buy_asset':
                cash   -= amount     # 현금 감소 (매수 비용)
                stocks += amount     # 주식/ETF 증가 (또는 re 등 type에 따라 분기)
            elif etype == 'extra_income':
                cash += amount
            elif etype == 'extra_expense':
                cash -= amount
            elif etype == 'retire':
                # 은퇴 시 근로소득 = 0으로 처리
                # annual_net_inflow를 passive_annual만으로 재계산하는 로직 추가 가능
                pass

        total = cash + stocks + re + crypto + pension
        net   = total - loans

        result.append({
            'year':         year,
            'family_ages':  family_ages,
            'cash':         round(cash),
            'stocks':       round(stocks),
            'real_estate':  round(re),
            'crypto':       round(crypto),
            'pension':      round(pension),
            'loans':        round(loans),
            'total_assets': round(total),
            'net_worth':    round(net),
            'events':       year_events,
            'event_cash_delta': round(event_cash_delta),
        })

        # ── 다음 연도로 복리 성장 적용 ──
        if i < sim_years:
            cash    = cash    * (1 + r_cash)    + annual_net_inflow  # 유입 + 이자
            stocks  = stocks  * (1 + r_stocks)  # 주식 복리
            re      = re      * (1 + r_re)       # 부동산 가격 상승
            crypto  = crypto  * (1 + r_stocks)  # 코인은 주식과 동일 수익률 적용
            pension = pension + base_pension_monthly * 12  # 연간 납입액 단순 합산
            annual_net_inflow *= (1 - exp_growth)          # 지출 증가로 인한 순유입 감소

    db.close()
    return jsonify({
        'simulation':      result,
        'annual_net_inflow': round(annual_net_inflow),
        'settings':        settings,
    })
```

---

## 4. 프론트엔드 변경 사항

### 4-1. 신규 페이지: `/lifecycle` (라우트 추가)

```python
# app.py에 추가
@app.route('/lifecycle')
def lifecycle():
    return render_template('lifecycle.html')
```

### 4-2. 네비게이션 메뉴에 "생애주기" 링크 추가 (`base.html`)

```html
<li class="nav-item">
  <a class="nav-link" href="/lifecycle">👨‍👩‍👧 생애주기</a>
</li>
```

### 4-3. `lifecycle.html` 레이아웃 구조

```
┌─────────────────────────────────────────────────────────────┐
│  👨‍👩‍👧 생애주기별 자산 투영 시뮬레이터                          │
├───────────────┬─────────────────────────────────────────────┤
│  [설정 패널]  │  [차트 영역]                                 │
│               │                                             │
│  가족 구성    │  ① 누적 자산 영역 차트 (Area Chart)           │
│  ┌──────────┐ │     현금 / 주식 / 부동산 / 연금 스택         │
│  │나  birth │ │                                             │
│  │배우자    │ │  ② 순자산 선그래프 (네트워스 라인)            │
│  │자녀1     │ │                                             │
│  └──────────┘ │  ③ 나이 타임라인 바 (하단 x축 보조)          │
│  [+ 가족추가] │     나  30세 → 31세 → ... 60세              │
│               │     배우자 28세 → ...                       │
│  시뮬레이션   │                                             │
│  파라미터     ├─────────────────────────────────────────────┤
│  주식수익률   │  [이벤트 추가 패널]                          │
│  부동산상승률 │  연도 | 유형 | 자산명 | 금액 | 메모          │
│  현금이자율   │  2028 | 부동산매도 | 강남아파트 | 5억         │
│  지출증가율   │  2031 | 주식매도   | 삼성전자   | 1억         │
│  유입속도     │  2035 | 은퇴       | -          | -          │
│  (자동/수동)  │  [+ 이벤트 추가]                             │
└───────────────┴─────────────────────────────────────────────┘
```

### 4-4. 핵심 JavaScript 로직

```javascript
// ── lifecycle.js ──────────────────────────────────────────

let simChart = null;

async function runSimulation() {
  // 1. 설정 저장 후 시뮬레이션 API 호출
  const settings = collectSettings();
  await fetch('/api/lifecycle-settings', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(settings)
  });

  const res  = await fetch('/api/lifecycle-simulate');
  const data = await res.json();
  const sim  = data.simulation;

  // 2. X축 레이블: 연도 + "나 N세" 형태
  const meProfile = await fetchMe();  // role='me'인 가족 구성원
  const labels = sim.map(d => {
    const myAge = d.family_ages.find(f => f.role === 'me')?.age || '';
    return `${d.year}\n(${myAge}세)`;
  });

  // 3. 차트 데이터
  const cashData    = sim.map(d => d.cash);
  const stocksData  = sim.map(d => d.stocks);
  const reData      = sim.map(d => d.real_estate);
  const pensionData = sim.map(d => d.pension);
  const netData     = sim.map(d => d.net_worth);

  // 4. 이벤트 어노테이션
  const eventAnnotations = {};
  sim.forEach((d, i) => {
    if (d.events.length > 0) {
      d.events.forEach(e => {
        eventAnnotations[`event_${i}`] = {
          type: 'line',
          xMin: i, xMax: i,
          borderColor: 'rgba(255,165,0,0.7)',
          borderWidth: 2,
          borderDash: [6, 3],
          label: {
            enabled: true,
            content: e.asset_name || e.event_type,
            position: 'start',
            font: { size: 10 }
          }
        };
      });
    }
  });

  // 5. Chart.js 스택 영역 차트 + 순자산 선 오버레이
  if (simChart) simChart.destroy();
  const ctx = document.getElementById('sim-chart').getContext('2d');
  simChart = new Chart(ctx, {
    data: {
      labels,
      datasets: [
        // 스택 영역 (자산 구성)
        { type: 'bar', label: '현금/예금', data: cashData,    backgroundColor: 'rgba(52,152,219,0.6)',  stack: 'assets' },
        { type: 'bar', label: '주식/ETF',  data: stocksData,  backgroundColor: 'rgba(46,204,113,0.6)',  stack: 'assets' },
        { type: 'bar', label: '부동산',    data: reData,      backgroundColor: 'rgba(155,89,182,0.6)',  stack: 'assets' },
        { type: 'bar', label: '연금',      data: pensionData, backgroundColor: 'rgba(230,126,34,0.6)', stack: 'assets' },
        // 순자산 선 (대출 차감)
        {
          type: 'line', label: '순자산',
          data: netData,
          borderColor: '#e74c3c',
          borderWidth: 3,
          fill: false,
          tension: 0.3,
          pointRadius: 4,
          yAxisID: 'y',
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        annotation: { annotations: eventAnnotations },  // chartjs-plugin-annotation 필요
        tooltip: {
          callbacks: {
            afterBody: (items) => {
              const yearIdx = items[0].dataIndex;
              const d = sim[yearIdx];
              // 가족 나이 툴팁
              const ageStr = d.family_ages.map(f => `${f.name}: ${f.age}세`).join(', ');
              const lines = [`👨‍👩‍👧 ${ageStr}`];
              if (d.events.length > 0) {
                lines.push(`📌 이벤트: ${d.events.map(e => e.asset_name).join(', ')}`);
              }
              return lines;
            }
          }
        }
      },
      scales: {
        x: { stacked: true },
        y: {
          stacked: true,
          ticks: { callback: v => formatKRW(v) }
        }
      }
    }
  });

  // 6. 연도별 테이블 업데이트
  renderSimTable(sim);
}

// ── 연도별 테이블 렌더링 ──
function renderSimTable(sim) {
  const tbody = document.querySelector('#sim-table tbody');
  tbody.innerHTML = '';
  sim.forEach(d => {
    const myAge = d.family_ages.find(f => f.role === 'me')?.age;
    const eventBadge = d.events.length > 0
      ? d.events.map(e => `<span class="badge bg-warning text-dark">${e.asset_name}</span>`).join(' ')
      : '';
    tbody.insertAdjacentHTML('beforeend', `
      <tr class="${d.events.length > 0 ? 'table-warning' : ''}">
        <td>${d.year}<br><small class="text-muted">${myAge}세</small></td>
        <td>${formatKRW(d.net_worth)}</td>
        <td>${formatKRW(d.cash)}</td>
        <td>${formatKRW(d.stocks)}</td>
        <td>${formatKRW(d.real_estate)}</td>
        <td>${formatKRW(d.pension)}</td>
        <td>${formatKRW(d.loans)}</td>
        <td>${eventBadge}</td>
      </tr>
    `);
  });
}
```

---

## 5. 이벤트 유형 정의

| event_type | 한국어 표시 | 동작 설명 |
|-----------|------------|-----------|
| `sell_realestate` | 부동산 매도 | `re -= amount`, `cash += amount` |
| `sell_stock` | 주식/ETF 매도 | `stocks -= amount`, `cash += amount` |
| `buy_asset` | 자산 매수 | `cash -= amount`, 대상 자산 += amount |
| `extra_income` | 일시 수입 | `cash += amount` (상속, 보너스 등) |
| `extra_expense` | 일시 지출 | `cash -= amount` (결혼, 자녀교육 등) |
| `retire` | 은퇴 선언 | 근로소득 연평균을 0으로 전환, 자생소득만 유입 |
| `loan_payoff` | 대출 완납 | `cash -= amount`, `loans -= amount` |

---

## 6. 구현 순서

```
1단계: DB 마이그레이션 (Supabase SQL Editor)
  ├─ lifecycle_profile 테이블 생성
  ├─ lifecycle_events 테이블 생성
  └─ lifecycle_settings 테이블 생성 + 기본값 INSERT

2단계: 백엔드 API
  ├─ /api/lifecycle-profile (CRUD)
  ├─ /api/lifecycle-events (CRUD)
  ├─ /api/lifecycle-settings (GET/POST)
  ├─ /api/lifecycle-simulate (핵심 계산)
  └─ /lifecycle 페이지 라우트

3단계: 프론트엔드
  ├─ lifecycle.html 레이아웃 구현
  ├─ 가족 구성 입력 UI
  ├─ 시뮬레이션 파라미터 설정 UI
  ├─ 이벤트 추가/삭제 UI
  ├─ Chart.js 스택 영역 차트 + 선그래프 이중 표현
  └─ 연도별 요약 테이블

4단계: 연동
  ├─ tech-tree의 연평균 유입속도(#1-1 개선값)를 자동으로 기본값으로 사용
  └─ 수동 오버라이드 옵션 제공
```

---

## 7. 의존성 추가

```
chartjs-plugin-annotation   # 이벤트 수직선 어노테이션용
  → CDN: https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation
```

---

## 8. 완성 화면 예시

```
👨‍👩‍👧 생애주기별 자산 투영

연간 순유입: 약 3,200만원 (자동 계산, 근로소득 기반)
시뮬레이션 기간: 30년 | 주식수익률: 7% | 부동산상승률: 3%

    순자산
  ┌───────────────────────────────────────────────────────┐
  │15억                    ⋯⋯⋯⋯⋯⋯⋯⋯⋯⋯⋯⋯⋯⋯⋯───────────│순자산선
  │10억             ⋯⋯⋯⋯  ┊ (2031 삼성전자매도)         │
  │ 5억   ████████████     ┊                              │
  │       ████ 현금 ████   │ ████ 주식 ████ 부동산 ████  │
  └─────────────────────────────────────────────────────┘
      2025   2030   2035   2040   2045   2050   2055
    나 31세  36세  41세    46세   51세   56세   61세
  배우자29세 34세  39세   44세   49세   54세   59세

📅 이벤트 목록
  2028 | 부동산매도 | 강남아파트 | +5억원
  2031 | 주식매도   | 삼성전자   | +1억원
  2040 | 은퇴       | -          | 근로소득 → 0

┌──────┬──────────┬──────────┬──────────┬──────────┬──────┐
│ 연도 │  순자산  │  현금    │  주식    │  부동산  │ 이벤트│
├──────┼──────────┼──────────┼──────────┼──────────┼──────┤
│ 2025 │  3.2억   │  0.5억   │  1.8억   │  0.9억   │      │
│ 2026 │  3.5억   │  0.7억   │  2.0억   │  0.8억   │      │
│ 2028 │  8.1억   │  5.5억   │  2.1억   │  0.5억   │ 아파트│
│ ...  │  ...     │  ...     │  ...     │  ...     │      │
└──────┴──────────┴──────────┴──────────┴──────────┴──────┘
```

---

## 9. 주의사항 & 한계

| 항목 | 내용 |
|------|------|
| 시뮬레이션 특성 | 실제 미래는 다를 수 있음. 안내 문구 필수 |
| 대출 처리 | 현재는 대출 잔액 고정. 상환 시뮬레이션은 `loan_payoff` 이벤트로 수동 처리 |
| 연금 처리 | 납입액 단순 합산 (수익률 미적용). 추후 개선 가능 |
| 세금 처리 | 양도세, 금융투자세 등 미반영. 이벤트 `extra_expense`로 수동 입력 가능 |
| 복잡도 | 은퇴 이후 소득 구조 변경은 `retire` 이벤트 이후 로직에서 수동 설정 필요 |
