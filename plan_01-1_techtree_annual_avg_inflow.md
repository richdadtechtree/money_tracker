# 기능 계획서 #1-1 — 테크트리 연평균 유입속도 산출 방식 개선

> **목적**: 현재 "이번달 수입 × 12"로 부정확하게 산출되는 연평균 유입속도를,
> 실제 데이터가 있는 월들의 평균으로 교체하여 신뢰도를 높인다.

---

## 1. 현재 방식의 문제

### 코드 위치: `app.py` → `api_tech_tree_data()` (약 1430~1450번째 줄)

```python
# 현재: 이번 달 수입만 집계
ym = today.strftime('%Y-%m')

cur.execute(
    "SELECT COALESCE(SUM(amount),0) FROM income "
    "WHERE to_char(date::date, 'YYYY-MM') = %s "
    "AND category IN ('급여', '사업소득') AND date <= CURRENT_DATE",
    (ym,)
)
labor_inc = cur.fetchone()[0]  # ← 이번 달 1개월치
```

프론트엔드 tech_tree.html에서는 이 값을 다음과 같이 사용:
```javascript
// 물탱크 유입속도 표시 (추정)
annualInflow = (labor_inc + passive_inc) * 12  // ← 이번 달 × 12 = 연간 추정
```

### 문제 시나리오

| 상황 | 현재 결과 | 실제 연평균 |
|------|-----------|-------------|
| 월초(급여 미입금) | 연평균 = 0원 | 실제와 완전 다름 |
| 보너스 월 | 연평균 과대 추정 | 부풀려짐 |
| 기록 3개월차 신규 사용자 | 3개월 데이터로 12 곱함 | 왜곡 없이 평균 사용해야 함 |

---

## 2. 개선 방식

### 핵심 원칙
> "데이터가 있는 월"만 분모로 사용한다. 미래 월은 제외, 기록 없는 과거 월도 제외.

### 산출 공식
```
월평균 근로소득 = SUM(해당 월 근로소득) / COUNT(DISTINCT 기록된 월, 단 해당월 합계 > 0)
연평균 근로소득 = 월평균 근로소득 × 12

월평균 자생소득 = SUM(해당 월 자생소득) / COUNT(DISTINCT 기록된 월, 단 해당월 합계 > 0)
연평균 자생소득 = 월평균 자생소득 × 12
```

---

## 3. 백엔드 변경 사항 (`app.py`)

### 3-1. 신규 헬퍼 함수 추가

```python
def _calc_annual_avg_income(db):
    """
    실제 기록이 있는 월의 평균을 기준으로 연환산 수입을 계산한다.
    
    반환값:
      labor_monthly_avg   : 월평균 근로소득 (급여+사업소득)
      passive_monthly_avg : 월평균 자생소득 (나머지 수입)
      labor_annual        : 연환산 근로소득 (× 12)
      passive_annual      : 연환산 자생소득 (× 12)
      months_counted      : 집계에 사용된 월 수 (신뢰도 지표)
    """
    # ── 근로소득: 월별 합계를 구하고, 합계 > 0인 월만 평균에 포함 ──
    cur = db.cursor()
    cur.execute("""
        SELECT 
            to_char(date::date, 'YYYY-MM') AS ym,
            SUM(amount) AS monthly_total
        FROM income
        WHERE category IN ('급여', '사업소득')
          AND date <= CURRENT_DATE           -- 미래 사전등록 수입 제외
        GROUP BY ym
        HAVING SUM(amount) > 0              -- 0인 달은 제외 (데이터 없는 달과 동일 취급)
        ORDER BY ym DESC
        LIMIT 12                            -- 최근 12개월 이내만 사용 (이직/폐업 등 과거 왜곡 방지)
    """)
    labor_rows = cur.fetchall()
    cur.close()

    if labor_rows:
        labor_monthly_avg = sum(r['monthly_total'] for r in labor_rows) / len(labor_rows)
    else:
        labor_monthly_avg = 0

    # ── 자생소득: 동일 방식 ──
    cur = db.cursor()
    cur.execute("""
        SELECT 
            to_char(date::date, 'YYYY-MM') AS ym,
            SUM(amount) AS monthly_total
        FROM income
        WHERE category NOT IN ('급여', '사업소득')
          AND date <= CURRENT_DATE
        GROUP BY ym
        HAVING SUM(amount) > 0
        ORDER BY ym DESC
        LIMIT 12
    """)
    passive_rows = cur.fetchall()
    cur.close()

    # 부동산 임대 수입은 매달 고정으로 발생하므로 그대로 합산
    cur = db.cursor()
    cur.execute("""
        SELECT COALESCE(SUM(monthly_rent), 0)
        FROM tenant_contracts
        WHERE contract_type = '월세'
          AND id IN (SELECT MAX(id) FROM tenant_contracts GROUP BY real_estate_id)
    """)
    rental_monthly = cur.fetchone()[0]
    cur.close()

    cur = db.cursor()
    cur.execute("""
        SELECT COALESCE(SUM(deposit * 0.04 / 12), 0)
        FROM tenant_contracts
        WHERE contract_type = '전세'
          AND id IN (SELECT MAX(id) FROM tenant_contracts GROUP BY real_estate_id)
    """)
    leverage_monthly = cur.fetchone()[0]
    cur.close()

    if passive_rows:
        passive_monthly_avg = sum(r['monthly_total'] for r in passive_rows) / len(passive_rows)
    else:
        passive_monthly_avg = 0

    passive_monthly_avg += (rental_monthly + leverage_monthly)

    return {
        'labor_monthly_avg':   round(labor_monthly_avg),
        'passive_monthly_avg': round(passive_monthly_avg),
        'labor_annual':        round(labor_monthly_avg * 12),
        'passive_annual':      round(passive_monthly_avg * 12),
        'labor_months':        len(labor_rows),    # 집계에 사용된 월 수 (신뢰도 지표)
        'passive_months':      len(passive_rows),
    }
```

### 3-2. `api_tech_tree_data()` 수정

```python
@app.route('/api/tech-tree-data')
def api_tech_tree_data():
    db = get_db()
    
    # ... (자산 계산 코드 그대로) ...

    # ── [변경] 연평균 유입속도 산출 ──────────────────────────
    # 기존: 이번달 수입만 사용
    # 변경: 기록된 월의 평균 × 12
    avg_income = _calc_annual_avg_income(db)
    
    # 이번달 실제 수입은 별도로 계산 (현황 표시용)
    today = date.today()
    ym = today.strftime('%Y-%m')
    cur = db.cursor()
    cur.execute(
        "SELECT COALESCE(SUM(amount),0) FROM income "
        "WHERE to_char(date::date, 'YYYY-MM') = %s AND category IN ('급여', '사업소득') AND date <= CURRENT_DATE",
        (ym,)
    )
    labor_inc_this_month = cur.fetchone()[0]; cur.close()

    cur = db.cursor()
    cur.execute(
        "SELECT COALESCE(SUM(amount),0) FROM income "
        "WHERE to_char(date::date, 'YYYY-MM') = %s AND category NOT IN ('급여', '사업소득') AND date <= CURRENT_DATE",
        (ym,)
    )
    passive_inc_this_month = cur.fetchone()[0]; cur.close()

    # ... (지출, 고정비 계산 이하 동일) ...

    return jsonify({
        'assets': { ... },
        
        # [변경] income 응답에 연평균 데이터 추가
        'income': {
            'labor':         int(labor_inc_this_month or 0),   # 이번달 실수입 (현황용)
            'passive':       int(passive_inc_this_month or 0), # 이번달 실수입 (현황용)
            'labor_annual_avg':   avg_income['labor_annual'],   # 연환산 평균 ← NEW
            'passive_annual_avg': avg_income['passive_annual'], # 연환산 평균 ← NEW
            'labor_months':       avg_income['labor_months'],   # 신뢰도 지표 ← NEW
            'passive_months':     avg_income['passive_months'], # 신뢰도 지표 ← NEW
        },
        
        'expense': int(total_exp or 0),
        'straw_total': int(straw_total or 0),
        'target_amount': int(target_amount or 0),
        'monthly_stats': { ... }
    })
```

---

## 4. 프론트엔드 변경 사항 (`tech_tree.html`)

### 4-1. 물탱크 유입속도 표시 변경

```javascript
// ── 기존 ──
const annualInflow = (data.income.labor + data.income.passive) * 12;
document.querySelector('.inflow-speed').textContent =
    `연평균 ${formatKRW(annualInflow)} 유입 중`;

// ── 변경 후 ──
const annualInflow = data.income.labor_annual_avg + data.income.passive_annual_avg;
const laborMonths  = data.income.labor_months;   // 집계 월 수
const reliabilityNote = laborMonths >= 6
    ? `(최근 ${laborMonths}개월 평균)`
    : `(${laborMonths}개월 기준, 데이터 축적 중)`;

document.querySelector('.inflow-speed').textContent =
    `연평균 ${formatKRW(annualInflow)} 유입 중`;

// 신뢰도 툴팁 또는 부제 표시
document.querySelector('.inflow-speed-sub').textContent = reliabilityNote;
```

### 4-2. 유입속도 카드에 월평균 breakdown 추가 (선택)

```html
<!-- 물탱크 위 또는 아래 정보 패널 -->
<div class="inflow-detail">
  <div>근로소득 월평균: <span id="labor-monthly-avg">-</span></div>
  <div>자생소득 월평균: <span id="passive-monthly-avg">-</span>
    <small class="text-muted">(임대료 포함)</small>
  </div>
  <hr>
  <div>연환산 합계: <span id="annual-total-avg" class="fw-bold text-primary">-</span></div>
  <div class="text-muted small" id="reliability-note"></div>
</div>
```

---

## 5. 신뢰도 기준 정의

| 기록된 월 수 | 신뢰도 표시 | 비고 |
|-------------|------------|------|
| 1~2개월 | ⚠️ 데이터 부족 (N개월 기준) | 주의 표시 |
| 3~5개월 | 🔵 N개월 평균 | 기본 표시 |
| 6~11개월 | 🟢 N개월 평균 | 신뢰 가능 |
| 12개월 이상 | 🟢 12개월 평균 (최근 1년) | 최고 신뢰도 |

---

## 6. 전후 비교

| 항목 | 변경 전 | 변경 후 |
|------|---------|---------|
| 산출 기준 | 이번 달 수입 × 12 | 기록된 월 평균 × 12 |
| 월초 급여 미입금 시 | 연평균 = 0원 | 과거 월 평균으로 안정적 |
| 보너스 월 | 연평균 과대 추정 | 분산되어 평활화됨 |
| 최대 반영 기간 | 1개월 | 최근 12개월 |
| 임대소득 처리 | 이번 달 임대료만 | 고정값으로 별도 합산 |
| 신규 사용자 | 왜곡 큼 | 기록된 만큼만 사용, 안내 제공 |

---

## 7. 구현 순서

```
1단계: _calc_annual_avg_income() 헬퍼 함수 작성 (app.py 상단)
2단계: api_tech_tree_data() 내 income 계산 블록 교체
3단계: JSON 응답에 labor_annual_avg, passive_annual_avg 필드 추가
4단계: tech_tree.html JS에서 새 필드 사용하도록 수정
5단계: 신뢰도 노트 UI 추가
```
