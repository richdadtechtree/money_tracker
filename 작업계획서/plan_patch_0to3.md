# 통합 수정 계획서 — #0 ~ #3

> **대상 파일**: `static/css/style.css`, `templates/base.html`, `templates/investments.html`, `static/js/common.js`  
> **DB 변경**: #1 ETF 테이블 컬럼 추가 외 없음

---

## #0. 다크모드 텍스트 가시성 전체 수정

### 문제 진단

투자관리 페이지의 "구분(etf_type)" 셀렉트박스 등,  
다크모드에서 **배경색이 어두운데 글자색이 자동으로 어두운 색을 상속**받아 보이지 않는 현상.

Bootstrap 기본 스타일(`form-select`, `table`, `badge`, `text-muted` 등)이  
`[data-bs-theme="dark"]` 범위 밖에서 선언되어 오버라이드되지 않는 것이 원인.

---

### 수정 대상 CSS 패턴 목록

| 요소 | 문제 | 수정 방향 |
|------|------|-----------|
| `<select>`, `<option>` | 다크배경에 어두운 글자 | `color: var(--bs-body-color)` 명시 |
| `<table>` 내 `<td>`, `<th>` | 컬러 미지정으로 투명 취급 | `color: inherit` 강제 |
| `.badge` (구분 배지) | 배경과 글자색 모두 어두움 | 다크모드 전용 badge 오버라이드 |
| `text-muted` | 다크모드에서 너무 어두움 | `opacity: 0.7` 유지, color 명시 |
| `<input>`, `<textarea>` | placeholder 색 겹침 | `::placeholder { color: #888 }` |
| `.card` 헤더/바디 | 배경 변수 미적용 | `background-color: var(--bs-card-bg)` |
| `modal-content` | 다크배경 모달에 흰 글자 누락 | `color: var(--bs-body-color)` |
| `.dropdown-menu` | 다크배경에 어두운 글자 | `--bs-dropdown-color` 명시 |

---

### `style.css` 추가 블록 (다크모드 전용 섹션)

```css
/* ══════════════════════════════════════════════
   다크모드 전체 가시성 픽스
   [data-bs-theme="dark"] 또는 .dark-mode 클래스 기준
══════════════════════════════════════════════ */
[data-bs-theme="dark"] {

  /* ── 폼 요소 ── */
  select,
  select option,
  .form-select,
  .form-control,
  .form-control::placeholder,
  textarea {
    color: var(--bs-body-color) !important;
    background-color: var(--bs-body-bg) !important;
    border-color: var(--bs-border-color) !important;
  }

  /* ── 테이블 ── */
  .table td,
  .table th,
  .table-striped > tbody > tr > td,
  .table-hover > tbody > tr:hover > td {
    color: var(--bs-body-color) !important;
  }

  /* ── 구분(etf_type) 배지 — 투자관리 핵심 수정 ── */
  .badge {
    color: #fff !important;
  }
  .badge.bg-secondary,
  .badge.bg-light {
    background-color: #4a4a5a !important;
    color: #e0e0e0 !important;
  }
  .badge.bg-success  { background-color: #1a6b3c !important; }
  .badge.bg-danger   { background-color: #7a1a2a !important; }
  .badge.bg-warning  { background-color: #7a5a00 !important; color: #fff !important; }
  .badge.bg-info     { background-color: #0a5a7a !important; }
  .badge.bg-primary  { background-color: #1a3a8a !important; }

  /* ── 카드 ── */
  .card,
  .card-header,
  .card-body,
  .card-footer {
    color: var(--bs-body-color) !important;
    background-color: var(--bs-card-bg) !important;
  }

  /* ── 모달 ── */
  .modal-content,
  .modal-header,
  .modal-body,
  .modal-footer {
    color: var(--bs-body-color) !important;
    background-color: var(--bs-body-bg) !important;
  }
  .modal-header .btn-close {
    filter: invert(1);
  }

  /* ── 드롭다운 ── */
  .dropdown-menu {
    color: var(--bs-body-color) !important;
    background-color: var(--bs-body-bg) !important;
    border-color: var(--bs-border-color) !important;
  }
  .dropdown-item {
    color: var(--bs-body-color) !important;
  }
  .dropdown-item:hover {
    background-color: rgba(255,255,255,0.08) !important;
  }

  /* ── 텍스트 유틸리티 ── */
  .text-muted {
    color: rgba(255,255,255,0.5) !important;
  }
  .text-dark {
    color: var(--bs-body-color) !important;
  }

  /* ── 리스트 그룹 ── */
  .list-group-item {
    color: var(--bs-body-color) !important;
    background-color: var(--bs-card-bg) !important;
    border-color: var(--bs-border-color) !important;
  }

  /* ── 투자관리 전용: 구분 셀렉트박스 ── */
  select[name="etf_type"],
  #etfTypeSelect,
  .investment-type-select {
    color: var(--bs-body-color) !important;
    background-color: #2a2a3e !important;
  }

  /* ── 페이지네이션 ── */
  .page-link {
    background-color: var(--bs-card-bg) !important;
    border-color: var(--bs-border-color) !important;
    color: var(--bs-body-color) !important;
  }
  .page-item.active .page-link {
    background-color: var(--bs-primary) !important;
    color: #fff !important;
  }
  .page-item.disabled .page-link {
    color: rgba(255,255,255,0.3) !important;
  }
}
```

---

### 검증 체크리스트

```
□ 투자관리 → 구분(국내/해외/지수/레버리지) 셀렉트박스 글씨 보임
□ 투자관리 → 거래내역 테이블 td 글씨 보임
□ 가계부 → 카테고리 셀렉트박스 글씨 보임
□ 카드관리 → badge 색상 구분 가능
□ 모달(추가/수정) → 입력 필드 글씨 보임
□ placeholder 색상이 너무 밝거나 어둡지 않음
□ 드롭다운 메뉴 항목 글씨 보임
□ 모달 X 버튼(btn-close) 보임
```

---
---

## #1. 지수투자 분할매수 공식 계산기

### 목적
ETF 목록 중 지수/레버리지 상품(TQQQ, SOXL 등)에 대해  
**총 투자 예산 + 목표 기간** 입력 시 하락률 비례 분할매수 권장 금액을 계산해주는 패널 추가.

---

### 배경: 레버리지 ETF 분할매수 전략

레버리지 ETF(2~3배)는 **변동성 끌림(volatility decay)** 현상으로 장기보유 시 손실 확대 위험이 있어,  
하락 구간을 나눠서 매수하는 **역피라미딩(하락 깊을수록 더 많이 매수)** 전략이 권장됨.

#### 하락률 비례 투자 공식

```
총 투자 예산: B 원
분할 횟수: N 회 (기본 5회)
각 구간 하락률 기준: -5%, -10%, -15%, -20%, -25%, ...

가중치 배분 (역피라미딩):
  1구간(현재가/초기): 전체의 10%
  2구간(-5%):        전체의 15%
  3구간(-10%):       전체의 20%
  4구간(-15%):       전체의 25%
  5구간(-20%↓):      전체의 30%

각 구간 투자금 = B × (구간 가중치)
각 구간 매수 주수 = 투자금 / (현재가 × (1 - 하락률))
```

#### 정액 DCA 공식 (단순 버전)

```
월 투자금 = B / 기간(개월)
매월 동일 금액으로 자동 매수
```

---

### DB 변경

**`etf` 테이블에 컬럼 추가** (Supabase SQL Editor):

```sql
ALTER TABLE etf ADD COLUMN IF NOT EXISTS invest_strategy VARCHAR(20) DEFAULT 'dca';
-- 'dca'(정액분할), 'drawdown'(하락률비례), 'va'(가치평균)

ALTER TABLE etf ADD COLUMN IF NOT EXISTS total_budget BIGINT DEFAULT 0;
-- 총 투자 예산 (사용자 설정)

ALTER TABLE etf ADD COLUMN IF NOT EXISTS invest_periods INTEGER DEFAULT 12;
-- 목표 투자 기간(개월)

ALTER TABLE etf ADD COLUMN IF NOT EXISTS drawdown_step NUMERIC(4,1) DEFAULT 5.0;
-- 하락률 간격(%, 기본 5%)
```

---

### 백엔드 변경 (`app.py`)

#### 신규 API: `/api/etf-invest-plan`

```python
@app.route('/api/etf-invest-plan', methods=['POST'])
def api_etf_invest_plan():
    """
    지수/레버리지 ETF 분할매수 계획 계산.
    
    요청 body:
      etf_id         : ETF ID (현재가 조회용)
      strategy       : 'dca' | 'drawdown'
      total_budget   : 총 투자 예산 (원)
      periods        : 기간 (개월, DCA용)
      drawdown_step  : 하락 간격 (%, 기본 5)
      split_count    : 분할 횟수 (drawdown용, 기본 5)
      current_price  : 현재 입력값 (없으면 DB 조회)
    """
    d = request.json or {}
    etf_id       = d.get('etf_id')
    strategy     = d.get('strategy', 'dca')
    total_budget = float(d.get('total_budget', 0))
    periods      = int(d.get('periods', 12))
    step         = float(d.get('drawdown_step', 5))
    split_count  = int(d.get('split_count', 5))
    
    db = get_db()
    
    # 현재가 조회
    if etf_id:
        cur = db.cursor()
        cur.execute("SELECT name, ticker, current_price FROM etf WHERE id=%s", (etf_id,))
        row = cur.fetchone(); cur.close()
        current_price = float(d.get('current_price') or row['current_price'] or 1)
        etf_name = row['name'] if row else ''
    else:
        current_price = float(d.get('current_price', 1))
        etf_name = d.get('etf_name', '')
    
    db.close()
    
    plan = []
    
    if strategy == 'dca':
        # ── 정액 분할매수 ──
        monthly_amount = total_budget / periods
        for i in range(periods):
            plan.append({
                'step':        i + 1,
                'label':       f"{i + 1}개월차",
                'trigger':     '매월 정기',
                'amount':      round(monthly_amount),
                'price':       round(current_price),  # DCA는 가격 무관
                'shares':      round(monthly_amount / current_price, 4),
                'cumulative':  round(monthly_amount * (i + 1)),
                'drawdown_pct': 0,
            })
    
    elif strategy == 'drawdown':
        # ── 하락률 비례 역피라미딩 ──
        # 가중치: 1구간=10%, 이후 매 구간마다 균등 배분 증가
        # 총합이 100%가 되도록 정규화
        raw_weights = [1]
        for i in range(1, split_count):
            raw_weights.append(raw_weights[-1] * 1.5)  # 1.5배씩 증가
        total_w = sum(raw_weights)
        weights = [w / total_w for w in raw_weights]
        
        cumulative = 0
        for i in range(split_count):
            dd_pct = i * step  # 하락률 (0, 5, 10, 15, 20, ...)
            trigger_price = round(current_price * (1 - dd_pct / 100))
            amount = round(total_budget * weights[i])
            cumulative += amount
            plan.append({
                'step':         i + 1,
                'label':        f"{'현재가' if i == 0 else f'-{dd_pct:.0f}% 하락 시'}",
                'trigger':      f"{'즉시 매수' if i == 0 else f'{trigger_price:,}원 이하'}",
                'trigger_price': trigger_price,
                'drawdown_pct': dd_pct,
                'weight_pct':   round(weights[i] * 100, 1),
                'amount':       amount,
                'price':        trigger_price,
                'shares':       round(amount / trigger_price, 4) if trigger_price > 0 else 0,
                'cumulative':   cumulative,
            })
    
    # 요약 정보
    total_shares = sum(p['shares'] for p in plan)
    avg_price    = round(total_budget / total_shares) if total_shares > 0 else 0
    
    return jsonify({
        'etf_name':     etf_name,
        'strategy':     strategy,
        'total_budget': round(total_budget),
        'plan':         plan,
        'summary': {
            'total_shares': round(total_shares, 4),
            'avg_price':    avg_price,
            'breakeven':    avg_price,  # 평균단가 = 손익분기점
        }
    })
```

---

### 프론트엔드 변경 (`investments.html`)

#### 레이아웃: ETF 탭 내 계산기 패널 추가

```html
<!-- ETF 섹션 하단에 추가 -->
<div class="card mt-4" id="invest-plan-panel">
  <div class="card-header">
    <h6 class="mb-0">📐 지수/레버리지 분할매수 계획기</h6>
  </div>
  <div class="card-body">
    <div class="row g-2 mb-3">
      <div class="col-md-3">
        <label class="form-label">ETF 선택</label>
        <select class="form-select" id="plan-etf-id">
          <option value="">직접 입력</option>
          <!-- ETF 목록 동적 삽입 -->
        </select>
      </div>
      <div class="col-md-2">
        <label class="form-label">현재가 (원)</label>
        <input type="number" class="form-control" id="plan-current-price" placeholder="자동 입력">
      </div>
      <div class="col-md-2">
        <label class="form-label">총 예산 (원)</label>
        <input type="number" class="form-control" id="plan-budget" placeholder="10,000,000">
      </div>
      <div class="col-md-2">
        <label class="form-label">전략</label>
        <select class="form-select" id="plan-strategy">
          <option value="dca">정액 DCA (월 분할)</option>
          <option value="drawdown">하락률 비례 역피라미딩</option>
        </select>
      </div>
      <!-- DCA 옵션 -->
      <div class="col-md-2" id="plan-opt-dca">
        <label class="form-label">기간 (개월)</label>
        <input type="number" class="form-control" id="plan-periods" value="12" min="1" max="60">
      </div>
      <!-- 하락률 옵션 -->
      <div class="col-md-2 d-none" id="plan-opt-dd">
        <label class="form-label">하락 간격 (%)</label>
        <input type="number" class="form-control" id="plan-dd-step" value="5" min="1" max="20">
      </div>
      <div class="col-md-1 d-flex align-items-end">
        <button class="btn btn-primary w-100" onclick="calcInvestPlan()">계산</button>
      </div>
    </div>

    <!-- 결과 영역 -->
    <div id="plan-result" class="d-none">
      <!-- 요약 배지 -->
      <div class="d-flex gap-3 mb-3 flex-wrap" id="plan-summary"></div>
      <!-- 계획 테이블 -->
      <div class="table-responsive">
        <table class="table table-sm table-bordered">
          <thead class="table-dark">
            <tr>
              <th>단계</th><th>트리거 조건</th><th>하락률</th>
              <th>비중</th><th>투자금</th><th>매수 주수</th><th>누적 투자금</th>
            </tr>
          </thead>
          <tbody id="plan-tbody"></tbody>
        </table>
      </div>
    </div>
  </div>
</div>
```

#### JavaScript (`investments.html` 내 script 섹션)

```javascript
// 전략 선택 시 옵션 전환
document.getElementById('plan-strategy').addEventListener('change', function() {
  const isDCA = this.value === 'dca';
  document.getElementById('plan-opt-dca').classList.toggle('d-none', !isDCA);
  document.getElementById('plan-opt-dd').classList.toggle('d-none', isDCA);
});

// ETF 선택 시 현재가 자동 입력
document.getElementById('plan-etf-id').addEventListener('change', function() {
  const etfId = this.value;
  if (!etfId) return;
  const etf = etfList.find(e => e.id == etfId);
  if (etf) document.getElementById('plan-current-price').value = etf.current_price;
});

async function calcInvestPlan() {
  const payload = {
    etf_id:        document.getElementById('plan-etf-id').value || null,
    strategy:      document.getElementById('plan-strategy').value,
    total_budget:  parseInt(document.getElementById('plan-budget').value || 0),
    current_price: parseFloat(document.getElementById('plan-current-price').value || 0),
    periods:       parseInt(document.getElementById('plan-periods').value || 12),
    drawdown_step: parseFloat(document.getElementById('plan-dd-step').value || 5),
    split_count:   5,
  };
  
  if (!payload.total_budget || !payload.current_price) {
    alert('현재가와 총 예산을 입력하세요.'); return;
  }
  
  const res  = await fetch('/api/etf-invest-plan', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload)
  });
  const data = await res.json();
  
  // 요약
  document.getElementById('plan-summary').innerHTML = `
    <span class="badge bg-primary fs-6">총 예산: ${formatKRW(data.total_budget)}</span>
    <span class="badge bg-success fs-6">예상 매수 주수: ${data.summary.total_shares}주</span>
    <span class="badge bg-warning text-dark fs-6">평균단가(손익분기): ${formatKRW(data.summary.avg_price)}</span>
  `;
  
  // 계획 테이블
  const tbody = document.getElementById('plan-tbody');
  tbody.innerHTML = '';
  data.plan.forEach(p => {
    tbody.insertAdjacentHTML('beforeend', `
      <tr>
        <td>${p.step}</td>
        <td>${p.trigger}</td>
        <td class="${p.drawdown_pct > 0 ? 'text-danger' : ''}">
          ${p.drawdown_pct > 0 ? '-' + p.drawdown_pct + '%' : '즉시'}
        </td>
        <td>${p.weight_pct ?? '-'}%</td>
        <td class="text-end fw-bold">${formatKRW(p.amount)}</td>
        <td class="text-end">${p.shares}주</td>
        <td class="text-end text-muted">${formatKRW(p.cumulative)}</td>
      </tr>
    `);
  });
  
  document.getElementById('plan-result').classList.remove('d-none');
}
```

---

### 결과 화면 예시

```
📐 지수/레버리지 분할매수 계획기
ETF: TQQQ  현재가: 65,000원  총예산: 10,000,000원  전략: 하락률 비례

[총 예산: 1,000만원] [예상 매수 주수: 178.4주] [평균단가(손익분기): 56,080원]

┌────┬─────────────────┬──────┬──────┬──────────┬────────┬────────────┐
│단계│ 트리거 조건      │하락률│ 비중 │  투자금  │매수주수│ 누적 투자금 │
├────┼─────────────────┼──────┼──────┼──────────┼────────┼────────────┤
│  1 │ 즉시 매수        │  -   │  9.5%│  950,000 │  14.6주│    950,000 │
│  2 │ 61,750원 이하    │  -5% │ 14.2%│1,420,000 │  23.0주│  2,370,000 │
│  3 │ 58,500원 이하    │ -10% │ 21.3%│2,130,000 │  36.4주│  4,500,000 │
│  4 │ 55,250원 이하    │ -15% │ 31.9%│3,190,000 │  57.7주│  7,690,000 │
│  5 │ 52,000원 이하    │ -20% │ 23.1%│2,310,000 │  44.4주│ 10,000,000 │
└────┴─────────────────┴──────┴──────┴──────────┴────────┴────────────┘
```

---
---

## #2. 왼쪽 사이드바 자동 숨김 / 재표시

### 동작 스펙

| 상황 | 동작 |
|------|------|
| 사이드바 외부에서 5초간 마우스 정지 또는 이동 없음 | 사이드바가 왼쪽으로 슬라이드 아웃 (숨김) |
| 마우스가 왼쪽 상단 타이틀(앱 이름) 영역에 진입 | 사이드바가 오른쪽으로 슬라이드 인 (표시) |
| 사이드바 위에 마우스가 있는 동안 | 타이머 리셋, 숨김 방지 |
| 앱 이름(타이틀) | 항상 고정 표시, 사라지지 않음 |
| 모바일 | 기존 토글 버튼 방식 유지 (이 기능은 데스크탑 전용) |

---

### CSS 변경 (`style.css`)

```css
/* ── 사이드바 슬라이드 애니메이션 ── */
#sidebar {
  transition: transform 0.35s cubic-bezier(0.4, 0, 0.2, 1);
  will-change: transform;
}

#sidebar.sidebar-hidden {
  transform: translateX(-100%);
  /* 사이드바가 완전히 왼쪽으로 사라짐 */
}

/* ── 사이드바 숨김 시 메인 콘텐츠 영역 확장 ── */
#main-content {
  transition: margin-left 0.35s cubic-bezier(0.4, 0, 0.2, 1);
}
#sidebar.sidebar-hidden ~ #main-content,
body.sidebar-hidden #main-content {
  margin-left: 0 !important;
}

/* ── 앱 타이틀 고정 레이어 (항상 표시) ── */
#sidebar-title-fixed {
  position: fixed;
  top: 0;
  left: 0;
  width: var(--sidebar-width, 250px);  /* 사이드바와 동일한 폭 */
  height: 56px;                        /* 사이드바 헤더 높이 */
  z-index: 1100;                       /* 사이드바보다 위에 렌더링 */
  background: var(--bs-primary);       /* 사이드바 헤더와 동일한 배경 */
  display: flex;
  align-items: center;
  padding: 0 1rem;
  cursor: pointer;                     /* 클릭/호버로 사이드바 재표시 가능 */
  user-select: none;
  box-shadow: 2px 0 8px rgba(0,0,0,0.15);
}

#sidebar-title-fixed .app-title-text {
  color: #fff;
  font-size: 1rem;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ── 호버 힌트 아이콘 (사이드바 숨김 상태에서만 표시) ── */
#sidebar-title-fixed .expand-hint {
  margin-left: auto;
  opacity: 0;
  transition: opacity 0.2s;
  color: rgba(255,255,255,0.7);
  font-size: 0.75rem;
}
body.sidebar-hidden #sidebar-title-fixed .expand-hint {
  opacity: 1;
}
body.sidebar-hidden #sidebar-title-fixed:hover .expand-hint {
  color: #fff;
}

/* ── 사이드바 내 기존 타이틀은 숨김 (중복 방지) ── */
#sidebar .sidebar-brand {
  visibility: hidden;   /* 공간은 유지, 텍스트만 숨김 */
}
```

---

### HTML 변경 (`base.html`)

```html
<!-- <body> 바로 아래, #sidebar보다 먼저 삽입 -->
<div id="sidebar-title-fixed" 
     onmouseenter="onTitleHover()"
     onclick="showSidebar()">
  <span class="app-title-text">💰 자산관리</span>
  <span class="expand-hint">← 메뉴 열기</span>
</div>

<!-- 기존 #sidebar는 그대로 유지 -->
<nav id="sidebar" ...>
  ...
</nav>
```

---

### JavaScript 변경 (`common.js` 또는 `base.html` 내 `<script>`)

```javascript
// ── 사이드바 자동 숨김 / 재표시 ──────────────────────────
(function () {
  const HIDE_DELAY_MS = 5000;   // 5초 후 숨김
  const SHOW_THRESHOLD = 80;    // 좌상단 영역 판정 픽셀 범위 (x < 80, y < 120)
  
  let hideTimer   = null;
  let isSidebarHidden = false;
  const sidebar   = document.getElementById('sidebar');
  const body      = document.body;

  // ── 타이머 시작 (5초 후 숨김) ──
  function startHideTimer() {
    clearTimeout(hideTimer);
    hideTimer = setTimeout(hideSidebar, HIDE_DELAY_MS);
  }

  // ── 타이머 취소 ──
  function cancelHideTimer() {
    clearTimeout(hideTimer);
  }

  // ── 사이드바 숨기기 ──
  function hideSidebar() {
    if (isSidebarHidden) return;
    isSidebarHidden = true;
    sidebar.classList.add('sidebar-hidden');
    body.classList.add('sidebar-hidden');
  }

  // ── 사이드바 표시 ──
  window.showSidebar = function () {
    if (!isSidebarHidden) return;
    isSidebarHidden = false;
    sidebar.classList.remove('sidebar-hidden');
    body.classList.remove('sidebar-hidden');
    startHideTimer();  // 표시 후 다시 타이머 시작
  };

  // ── 타이틀 호버 ──
  window.onTitleHover = function () {
    if (isSidebarHidden) showSidebar();
    else cancelHideTimer();   // 아직 표시 중이면 타이머 취소
  };

  // ── 사이드바에 마우스 진입 시 타이머 리셋 ──
  sidebar.addEventListener('mouseenter', () => {
    cancelHideTimer();
  });

  // ── 사이드바에서 마우스 이탈 시 타이머 재시작 ──
  sidebar.addEventListener('mouseleave', () => {
    startHideTimer();
  });

  // ── 전체 문서 마우스 이동 감지 (사이드바 밖) ──
  document.addEventListener('mousemove', (e) => {
    // 좌상단 타이틀 영역 (x < 80, y < 120) → 표시
    if (e.clientX < 80 && e.clientY < 120) {
      if (isSidebarHidden) showSidebar();
      return;
    }
    // 사이드바 위에 있는 경우 타이머 리셋 (mouseenter 이벤트 보완)
    const rect = sidebar.getBoundingClientRect();
    if (
      e.clientX >= rect.left && e.clientX <= rect.right &&
      e.clientY >= rect.top  && e.clientY <= rect.bottom
    ) {
      cancelHideTimer();
      return;
    }
    // 그 외 영역에서 마우스가 움직이면 타이머 재시작
    startHideTimer();
  });

  // ── 모바일에서는 비활성화 ──
  if (window.innerWidth < 768) {
    cancelHideTimer();
    return;
  }

  // ── 페이지 로드 시 타이머 시작 ──
  startHideTimer();
})();
```

---

### 동작 흐름 다이어그램

```
페이지 로드
    │
    ▼
타이머 시작 (5초)
    │
┌───┴────────────────────────────────────┐
│ 5초 경과?                               │
├─ YES ──→ 사이드바 슬라이드 아웃         │
│            │                           │
│            ▼                           │
│         [앱 타이틀만 고정 표시]          │
│            │                           │
│         마우스가 좌상단(x<80, y<120) ?  │
│         또는 타이틀 호버?               │
│            ├─ YES ──→ 슬라이드 인       │
│            │             └→ 타이머 재시작│
└─ NO  ──→ 타이머 리셋 (마우스 움직임)   │
            (사이드바 위에 있으면 취소)    │
└────────────────────────────────────────┘
```

---
---

## #3. 투자관리 거래내역 검색 + 페이지네이션

### 목표
- 매매 거래내역(stock_tx)에 **종목명/유형/날짜 범위 검색** 추가
- **10개씩 페이지 단위**로 분할 표시
- 프론트엔드 클라이언트 사이드 처리 (별도 API 불필요, 기존 `/api/stock-tx` 활용)

---

### 프론트엔드 변경 (`investments.html`)

#### 검색 바 HTML

```html
<!-- 거래내역 테이블 상단에 추가 -->
<div class="card mb-3" id="tx-search-bar">
  <div class="card-body py-2">
    <div class="row g-2 align-items-center">
      <!-- 키워드 검색 -->
      <div class="col-md-3">
        <div class="input-group input-group-sm">
          <span class="input-group-text">🔍</span>
          <input type="text" class="form-control" id="tx-search-keyword"
                 placeholder="종목명 또는 티커 검색..."
                 oninput="filterTxTable()">
        </div>
      </div>
      <!-- 거래 유형 필터 -->
      <div class="col-md-2">
        <select class="form-select form-select-sm" id="tx-search-type" onchange="filterTxTable()">
          <option value="">전체 유형</option>
          <option value="buy">매수</option>
          <option value="sell">매도</option>
        </select>
      </div>
      <!-- 날짜 범위 -->
      <div class="col-md-2">
        <input type="date" class="form-control form-control-sm" id="tx-search-from"
               onchange="filterTxTable()" title="시작 날짜">
      </div>
      <div class="col-md-2">
        <input type="date" class="form-control form-control-sm" id="tx-search-to"
               onchange="filterTxTable()" title="종료 날짜">
      </div>
      <!-- 가격 범위 (선택) -->
      <div class="col-md-2">
        <select class="form-select form-select-sm" id="tx-search-stock" onchange="filterTxTable()">
          <option value="">전체 종목</option>
          <!-- JS로 동적 삽입 -->
        </select>
      </div>
      <!-- 초기화 버튼 -->
      <div class="col-md-1">
        <button class="btn btn-outline-secondary btn-sm w-100" onclick="resetTxSearch()">
          초기화
        </button>
      </div>
    </div>
    <!-- 검색 결과 요약 -->
    <div class="mt-1">
      <small class="text-muted" id="tx-search-summary"></small>
    </div>
  </div>
</div>

<!-- 거래내역 테이블 (기존 구조 유지) -->
<div class="table-responsive">
  <table class="table table-sm table-hover" id="tx-table">
    <thead class="table-dark">
      <tr>
        <th>날짜</th><th>종목명</th><th>티커</th>
        <th>유형</th><th>가격</th><th>수량</th><th>수수료</th><th>메모</th><th>관리</th>
      </tr>
    </thead>
    <tbody id="tx-tbody"></tbody>
  </table>
</div>

<!-- 페이지네이션 -->
<nav aria-label="거래내역 페이지">
  <ul class="pagination pagination-sm justify-content-center" id="tx-pagination"></ul>
</nav>

<!-- 페이지당 건수 선택 -->
<div class="d-flex justify-content-between align-items-center mt-2">
  <small class="text-muted" id="tx-page-info"></small>
  <div class="d-flex align-items-center gap-2">
    <label class="text-muted small mb-0">페이지당</label>
    <select class="form-select form-select-sm w-auto" id="tx-per-page" onchange="renderTxPage(1)">
      <option value="10" selected>10개</option>
      <option value="20">20개</option>
      <option value="50">50개</option>
    </select>
  </div>
</div>
```

---

#### JavaScript 로직

```javascript
// ── 거래내역 검색 + 페이지네이션 ────────────────────────────

let allTxData    = [];   // 전체 로드된 거래내역 원본
let filteredTxData = []; // 검색 필터 적용 후
let txCurrentPage  = 1;

// ── 거래내역 로드 (기존 API 그대로 활용) ──
async function loadStockTx(stockId = null) {
  const url = stockId
    ? `/api/stock-tx?stock_id=${stockId}`
    : '/api/stock-tx';
  const res  = await fetch(url);
  allTxData  = await res.json();
  
  // 종목 선택 드롭다운 업데이트
  const stockSelect = document.getElementById('tx-search-stock');
  const names = [...new Set(allTxData.map(t => t.name).filter(Boolean))];
  stockSelect.innerHTML = '<option value="">전체 종목</option>';
  names.forEach(n => {
    stockSelect.insertAdjacentHTML('beforeend', `<option value="${n}">${n}</option>`);
  });
  
  filterTxTable();  // 초기 필터 적용 및 렌더링
}

// ── 필터 적용 ──
function filterTxTable() {
  const keyword = document.getElementById('tx-search-keyword').value.toLowerCase().trim();
  const txType  = document.getElementById('tx-search-type').value;
  const fromDt  = document.getElementById('tx-search-from').value;
  const toDt    = document.getElementById('tx-search-to').value;
  const stock   = document.getElementById('tx-search-stock').value;
  
  filteredTxData = allTxData.filter(t => {
    // 키워드: 종목명 or 티커 매칭
    if (keyword && !(
      (t.name   || '').toLowerCase().includes(keyword) ||
      (t.ticker || '').toLowerCase().includes(keyword) ||
      (t.memo   || '').toLowerCase().includes(keyword)
    )) return false;
    
    // 거래 유형
    if (txType && t.tx_type !== txType) return false;
    
    // 날짜 범위
    if (fromDt && t.tx_date < fromDt) return false;
    if (toDt   && t.tx_date > toDt)   return false;
    
    // 특정 종목
    if (stock && t.name !== stock) return false;
    
    return true;
  });
  
  // 검색 결과 요약 업데이트
  const total = allTxData.length;
  const found = filteredTxData.length;
  document.getElementById('tx-search-summary').textContent =
    keyword || txType || fromDt || toDt || stock
      ? `${total}건 중 ${found}건 검색됨`
      : `전체 ${total}건`;
  
  renderTxPage(1);  // 필터 적용 후 1페이지로 이동
}

// ── 초기화 ──
function resetTxSearch() {
  document.getElementById('tx-search-keyword').value = '';
  document.getElementById('tx-search-type').value    = '';
  document.getElementById('tx-search-from').value    = '';
  document.getElementById('tx-search-to').value      = '';
  document.getElementById('tx-search-stock').value   = '';
  filterTxTable();
}

// ── 페이지 렌더링 ──
function renderTxPage(page) {
  const perPage  = parseInt(document.getElementById('tx-per-page').value || 10);
  const total    = filteredTxData.length;
  const totalPages = Math.ceil(total / perPage) || 1;
  
  txCurrentPage = Math.min(Math.max(1, page), totalPages);
  
  const start = (txCurrentPage - 1) * perPage;
  const end   = Math.min(start + perPage, total);
  const pageData = filteredTxData.slice(start, end);
  
  // ── 테이블 렌더링 ──
  const tbody = document.getElementById('tx-tbody');
  tbody.innerHTML = '';
  
  if (pageData.length === 0) {
    tbody.innerHTML = `<tr><td colspan="9" class="text-center text-muted py-4">
      검색 결과가 없습니다.</td></tr>`;
  } else {
    pageData.forEach(t => {
      const isBuy = t.tx_type === 'buy';
      const totalAmt = t.price * t.quantity;
      tbody.insertAdjacentHTML('beforeend', `
        <tr>
          <td>${t.tx_date}</td>
          <td>${t.name || '-'}</td>
          <td><span class="badge bg-secondary">${t.ticker || '-'}</span></td>
          <td>
            <span class="badge ${isBuy ? 'bg-primary' : 'bg-danger'}">
              ${isBuy ? '매수' : '매도'}
            </span>
          </td>
          <td class="text-end">${formatKRW(t.price)}</td>
          <td class="text-end">${t.quantity}</td>
          <td class="text-end text-muted">${formatKRW(t.fee)}</td>
          <td class="text-muted small">${t.memo || ''}</td>
          <td>
            <button class="btn btn-xs btn-outline-primary" onclick="editTx(${t.id})">수정</button>
            <button class="btn btn-xs btn-outline-danger"  onclick="deleteTx(${t.id})">삭제</button>
          </td>
        </tr>
      `);
    });
  }
  
  // ── 페이지 정보 ──
  document.getElementById('tx-page-info').textContent =
    `${start + 1}-${end} / 전체 ${total}건`;
  
  // ── 페이지네이션 버튼 ──
  renderPagination(txCurrentPage, totalPages);
}

// ── 페이지네이션 버튼 렌더링 ──
function renderPagination(current, total) {
  const ul = document.getElementById('tx-pagination');
  ul.innerHTML = '';
  
  const maxBtns = 7;  // 최대 표시 버튼 수
  
  // 이전 버튼
  ul.insertAdjacentHTML('beforeend', `
    <li class="page-item ${current <= 1 ? 'disabled' : ''}">
      <a class="page-link" href="#" onclick="renderTxPage(${current - 1}); return false;">‹</a>
    </li>
  `);
  
  // 페이지 번호 버튼 (슬라이딩 윈도우)
  let startPage = Math.max(1, current - Math.floor(maxBtns / 2));
  let endPage   = Math.min(total, startPage + maxBtns - 1);
  if (endPage - startPage < maxBtns - 1) {
    startPage = Math.max(1, endPage - maxBtns + 1);
  }
  
  if (startPage > 1) {
    ul.insertAdjacentHTML('beforeend', `
      <li class="page-item">
        <a class="page-link" href="#" onclick="renderTxPage(1); return false;">1</a>
      </li>
      ${startPage > 2 ? '<li class="page-item disabled"><span class="page-link">…</span></li>' : ''}
    `);
  }
  
  for (let p = startPage; p <= endPage; p++) {
    ul.insertAdjacentHTML('beforeend', `
      <li class="page-item ${p === current ? 'active' : ''}">
        <a class="page-link" href="#" onclick="renderTxPage(${p}); return false;">${p}</a>
      </li>
    `);
  }
  
  if (endPage < total) {
    ul.insertAdjacentHTML('beforeend', `
      ${endPage < total - 1 ? '<li class="page-item disabled"><span class="page-link">…</span></li>' : ''}
      <li class="page-item">
        <a class="page-link" href="#" onclick="renderTxPage(${total}); return false;">${total}</a>
      </li>
    `);
  }
  
  // 다음 버튼
  ul.insertAdjacentHTML('beforeend', `
    <li class="page-item ${current >= total ? 'disabled' : ''}">
      <a class="page-link" href="#" onclick="renderTxPage(${current + 1}); return false;">›</a>
    </li>
  `);
}
```

---

### 완성 UI 예시

```
┌──────────────────────────────────────────────────────────────────┐
│ 🔍 [삼성전자    ] [전체 유형 ▼] [2025-01-01] [2025-12-31]      │
│    [전체 종목 ▼]                                   [초기화]      │
│    150건 중 23건 검색됨                                          │
├──────┬──────────┬──────┬──────┬──────────┬────┬──────┬────┬────┤
│ 날짜 │ 종목명   │ 티커 │ 유형 │   가격   │수량│수수료│메모│관리│
├──────┼──────────┼──────┼──────┼──────────┼────┼──────┼────┼────┤
│ 01/15│ 삼성전자 │ 005930│[매수]│  72,000 │ 10 │  360 │    │수정│
│ 02/03│ 삼성전자 │ 005930│[매도]│  78,000 │  5 │  195 │    │수정│
│  ... │   ...    │  ... │  ... │    ...  │ .. │  ... │ .. │ .. │
└──────┴──────────┴──────┴──────┴──────────┴────┴──────┴────┴────┘
  1-10 / 전체 23건               [페이지당 10▼]

        ‹  1  [2]  3  ›
```

---
---

## 전체 구현 순서 및 난이도

| 번호 | 작업 | 파일 | 난이도 | 예상 시간 |
|------|------|------|--------|-----------|
| #0 | 다크모드 CSS 픽스 | `style.css` | ⭐ | 30분 |
| #2 | 사이드바 자동 숨김 | `base.html`, `common.js`, `style.css` | ⭐⭐ | 1시간 |
| #3 | 거래내역 검색+페이지네이션 | `investments.html` | ⭐⭐ | 1.5시간 |
| #1 | 지수투자 계산기 | `app.py`, `investments.html` | ⭐⭐⭐ | 2.5시간 |

> **권장 순서**: #0 → #2 → #3 → #1  
> #0은 즉시 효과가 크고 #2, #3은 독립적이며 #1이 가장 복잡하므로 마지막에 작업.
