# 기능 계획서 #2-1 — 리밸런싱 "현재 포트폴리오 비중" 표 확장

> **목적**: `투자` 페이지 → 리밸런싱 탭 → "현재 포트폴리오 비중" 표에
> ① 현재 총자산 기준으로 각 자산군의 **목표 비중 금액(기준금액)** 을 함께 보여주고,
> ② 각 자산군 현재 금액 옆에 **매수평단가 대비 등락률(수익률)** 을 함께 보여준다.

대상 화면: `templates/investments.html` → `#tab-rebalance` → `#rb-compare-table`
(스크린샷 기준 "🎯 올웨더 목표 비중" 배지 아래, "📊 현재 포트폴리오 비중" 카드)

---

## 1. 요구사항 정리

| # | 요구사항 | 의미 |
|---|----------|------|
| 1 | 표 옆에 자산군별 **기준금액** 표기 (예: 미국장기채 40%의 금액, S&P 30%의 금액) | 현재 총자산 × 목표비중(%) = 자산군별 "목표 금액" |
| 2 | 표의 현재금액 옆에 **매수평단가 대비 등락률** 표기 | 자산군에 배정된 종목들의 (평가금액 − 매입원가) / 매입원가 × 100 |

---

## 2. 현재 구조 분석

### 2-1. 백엔드 — `app.py: api_rebalance_get()` (2246~2313행)

- 올웨더 카테고리 ETF/주식을 조회해 `qty × current_price` 로 `eval_amount`(평가금액)만 계산해서 반환.
- **매입원가(avg_price), 평단가, 손익률은 계산하지 않음** → 요구사항 2를 위해 추가 필요.
- `/api/stocks`, `/api/etf` 는 이미 `calc_position()`(FIFO)으로 `avg_price` / `unrealized_pnl` / `return_rate`를 계산해 응답하고 있음 (1596~1611행, 1830~1847행) → **동일 로직을 재사용**하면 된다.

```python
# app.py 1601~1607 (참고용, /api/stocks 기존 로직)
qty, avg, realized = calc_position(tx_by_stock[s['id']])
eval_amt = round(qty * current_price)
cost_amt = round(qty * avg)
unrealized_pnl = eval_amt - cost_amt
return_rate = round((eval_amt - cost_amt) / cost_amt * 100, 2) if cost_amt else 0
```

### 2-2. 프론트엔드 — `templates/investments.html`

- `loadRebalance()` (2384행): `/api/rebalance` 응답을 `rbItems`에 저장 (현재는 `eval_amount`만 사용).
- `getRbTotals()` (2487행): 자산군별 `eval_amount` 합계(`totals`)만 계산.
- `updateRbChart()` (2497~2541행): `totals`, `RB_TARGETS`(목표 %)로 표를 그림. 현재 컬럼 = `자산군 | 현재% | 목표% | 차이% | 진행바 | 금액(현재 평가금액)`.
- 재사용 가능한 포맷 헬퍼: `fmt()`(천단위 콤마), `rateHtml(pct)`(877~884행, 등락률 배지 — 상승 빨강/하락 파랑), `toKrw(amount, ticker)`(외화 환산).

---

## 3. 설계

### 3-1. 기준금액(목표 비중 금액) — 백엔드 변경 불필요

`updateRbChart()`는 이미 `grandTotal`(현재 총자산)과 `RB_TARGETS[cls]`(목표 %)를 갖고 있으므로 **프론트엔드 계산만으로 충분**하다.

```
기준금액[자산군] = grandTotal × RB_TARGETS[자산군] / 100
```

예) 총자산 1억 원일 때 → 미국장기채(40%) 기준금액 = 40,000,000원, S&P(30%) 기준금액 = 30,000,000원.

부가로 "현재 금액 − 기준금액" (과부족 금액)도 같은 계산에서 바로 나오므로, 리밸런싱에 얼마를 사고팔아야 하는지 금액으로 안내하는 컬럼도 함께 추가한다. (예: 부족 시 "+3,200,000원 매수 필요")

### 3-2. 매수평단가 대비 등락률 — 백엔드 변경 필요

자산군 단위 등락률은 해당 자산군에 배정된 종목들의 **매입원가 합계 대비 평가금액 합계**로 계산한다 (건별 등락률의 단순 평균이 아니라 금액가중 평균이어야 정확함).

```
자산군 매입원가 합계 = Σ(종목별 avg_price × qty)      # cost_amount
자산군 평가금액 합계 = Σ(종목별 current_price × qty)   # eval_amount (기존과 동일)
자산군 등락률 = (평가금액 합계 − 매입원가 합계) / 매입원가 합계 × 100
```

`calc_position()`이 이미 이 값을 만들어주므로, `/api/rebalance`가 종목별 `cost_amount`(또는 `avg_price`)를 함께 내려주기만 하면 프론트에서 자산군 단위로 합산 가능.

- **현금**은 매수평단가 개념이 없으므로 등락률 컬럼에 `-` 표시.
- 매입원가 합계가 0(전량 매도 등)이면 등락률은 `-` 처리 (0 나누기 방지).

---

## 4. 백엔드 변경 상세 (`app.py`)

`api_rebalance_get()` 수정: ETF/주식 조회 시 거래내역을 함께 가져와 `calc_position()`으로 평단가·매입원가를 계산해 각 item에 추가.

```python
@app.route('/api/rebalance', methods=['GET'])
def api_rebalance_get():
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM rebalance_assignments")
    assignments = {(r['source_type'], r['source_id']): dict(r) for r in cur.fetchall()}

    # 올웨더 ETF (기존 쿼리 그대로, qty 포함)
    cur.execute("""...(기존과 동일)...""")
    etfs = rows_to_list(cur.fetchall())

    # [NEW] 올웨더 ETF 거래내역 조회 (평단가 계산용)
    cur.execute("""
        SELECT t.etf_id, t.tx_type, t.price, t.quantity
        FROM etf_tx t
        JOIN etf e ON e.id = t.etf_id
        WHERE LOWER(e.category) LIKE '%올웨더%'
        ORDER BY t.etf_id, t.tx_date, t.id
    """)
    etf_tx_rows = cur.fetchall()

    # 올웨더 주식 (기존 쿼리 그대로)
    cur.execute("""...(기존과 동일)...""")
    stocks = rows_to_list(cur.fetchall())

    # [NEW] 올웨더 주식 거래내역 조회
    cur.execute("""
        SELECT t.stock_id, t.tx_type, t.price, t.quantity
        FROM stock_tx t
        JOIN stocks s ON s.id = t.stock_id
        WHERE LOWER(s.category) LIKE '%올웨더%'
        ORDER BY t.stock_id, t.tx_date, t.id
    """)
    stock_tx_rows = cur.fetchall()
    cur.close()
    db.close()

    from collections import defaultdict
    etf_tx_by_id = defaultdict(list)
    for r in etf_tx_rows: etf_tx_by_id[r['etf_id']].append(r)
    stock_tx_by_id = defaultdict(list)
    for r in stock_tx_rows: stock_tx_by_id[r['stock_id']].append(r)

    result_items = []
    for item in etfs:
        key = ('etf', item['id'])
        asgn = assignments.get(key, {})
        qty = float(item['qty'] or 0)
        _, avg, _ = calc_position(etf_tx_by_id[item['id']])
        avg = avg if (avg is not None and avg == avg) else 0.0
        eval_amt = round(qty * float(item['current_price'] or 0))
        cost_amt = round(qty * avg)
        result_items.append({
            'source_type': 'etf', 'source_id': item['id'],
            'name': item['name'], 'ticker': item['ticker'],
            'eval_amount': eval_amt,
            'cost_amount': cost_amt,          # [NEW]
            'avg_price': avg if qty > 0 else None,   # [NEW]
            'return_rate': round((eval_amt - cost_amt) / cost_amt * 100, 2) if cost_amt else None,  # [NEW]
            'asset_class': asgn.get('asset_class', ''),
        })
    for item in stocks:
        key = ('stock', item['id'])
        asgn = assignments.get(key, {})
        qty = float(item['qty'] or 0)
        _, avg, _ = calc_position(stock_tx_by_id[item['id']])
        avg = avg if (avg is not None and avg == avg) else 0.0
        eval_amt = round(qty * float(item['current_price'] or 0))
        cost_amt = round(qty * avg)
        result_items.append({
            'source_type': 'stock', 'source_id': item['id'],
            'name': item['name'], 'ticker': item['ticker'],
            'eval_amount': eval_amt,
            'cost_amount': cost_amt,          # [NEW]
            'avg_price': avg if qty > 0 else None,   # [NEW]
            'return_rate': round((eval_amt - cost_amt) / cost_amt * 100, 2) if cost_amt else None,  # [NEW]
            'asset_class': asgn.get('asset_class', ''),
        })

    cash_row = assignments.get(('cash', 0), {})
    cash_amount = int(cash_row.get('cash_amount', 0) or 0)
    return jsonify({'items': result_items, 'cash': cash_amount})
```

> 참고(환율): 외화 종목(`is_foreign_ticker`)의 `current_price`/`avg_price`는 원화 환산 없이 원종목 통화 그대로 계산된다 (`/api/stocks`, `/api/etf`와 동일한 기존 관례). 종목 단위 `return_rate`는 원가·평가액이 같은 통화라 문제없지만, 자산군 합산 `eval_amount`/`cost_amount`에 원화 종목과 외화 종목이 섞이면 금액 합계가 부정확해질 수 있다. 다만 이는 기존 `eval_amount` 합산 로직에도 이미 있던 한계이며, 실제 올웨더 배정 종목이 전부 국내 상장 ETF라면 영향 없음. 필요시 후속 작업으로 `toKrw()` 적용 검토.

---

## 5. 프론트엔드 변경 상세 (`templates/investments.html`)

### 5-1. `getRbTotals()` — 자산군별 매입원가 합계도 함께 집계 (2487~2495행)

```javascript
function getRbTotals() {
  const totals = { long_bond: 0, equity: 0, short_bond: 0, gold: 0, cash: 0 };
  const costTotals = { long_bond: 0, equity: 0, short_bond: 0, gold: 0, cash: 0 };  // [NEW]
  rbItems.forEach(it => {
    const cls = rbAssignments[rbKey(it)];
    if (cls && totals[cls] !== undefined) {
      totals[cls] += it.eval_amount || 0;
      costTotals[cls] += it.cost_amount || 0;   // [NEW]
    }
  });
  totals.cash = parseInt((document.getElementById('rb-cash-input')?.value || '').replace(/,/g,'')) || rbCash;
  return { totals, costTotals };   // [CHANGED] 반환 형태 변경 → 호출부(updateRbChart) 함께 수정
}
```

> `getRbTotals()`를 호출하는 다른 곳(`checkRbAlert()` 등)도 반환 형태 변경에 맞춰 `const { totals } = getRbTotals();` 로 수정 필요.

### 5-2. `updateRbChart()` — 표에 컬럼 2개 추가 (2497~2541행)

```javascript
function updateRbChart() {
  const { totals, costTotals } = getRbTotals();
  const grandTotal = Object.values(totals).reduce((s, v) => s + v, 0);
  document.getElementById('rb-total-amt').textContent = fmt(grandTotal) + '원';

  document.querySelectorAll('.rb-pct').forEach(el => {
    const cls = el.dataset.class;
    const pct = grandTotal > 0 ? (totals[cls] / grandTotal * 100).toFixed(1) : 0;
    el.textContent = pct + '%';
  });

  const rows = Object.keys(RB_TARGETS).map(cls => {
    const actual = grandTotal > 0 ? (totals[cls] / grandTotal * 100) : 0;
    const target = RB_TARGETS[cls];
    const diff = actual - target;
    const diffClass = Math.abs(diff) < 2 ? 'text-success' : (Math.abs(diff) < 5 ? 'text-warning' : 'text-danger');
    const bar = `<div class="progress" style="height:8px;background:#e5e7eb">
      <div class="progress-bar" style="width:${Math.min(actual,100)}%;background:${RB_COLORS[cls]}"></div>
    </div>`;

    // [NEW] 기준금액 (목표 비중 × 현재 총자산) + 과부족 금액
    const targetAmt = grandTotal > 0 ? Math.round(grandTotal * target / 100) : 0;
    const gapAmt = totals[cls] - targetAmt;
    const gapHtml = grandTotal > 0
      ? `<span class="small ${gapAmt >= 0 ? 'text-danger' : 'text-primary'}">${gapAmt >= 0 ? '+' : ''}${fmt(gapAmt)}</span>`
      : '-';

    // [NEW] 자산군 등락률 (현금은 '-')
    const rateHtmlStr = cls === 'cash'
      ? '<span class="text-muted">-</span>'
      : (costTotals[cls] > 0
          ? rateHtml((totals[cls] - costTotals[cls]) / costTotals[cls] * 100)
          : '<span class="text-muted">-</span>');

    return `<tr>
      <td><span class="badge rounded-pill" style="background:${RB_COLORS[cls]}">${RB_LABELS[cls]}</span></td>
      <td class="text-end fw-semibold">${actual.toFixed(1)}%</td>
      <td class="text-muted text-end">${target}%</td>
      <td class="text-end fw-semibold ${diffClass}">${diff >= 0 ? '+' : ''}${diff.toFixed(1)}%</td>
      <td style="width:120px">${bar}</td>
      <td class="text-end small">
        ${fmt(totals[cls])}원 ${rateHtmlStr}
      </td>
      <td class="text-end small text-muted">
        ${fmt(targetAmt)}원<br>${gapHtml}
      </td>
    </tr>`;
  }).join('');

  document.getElementById('rb-compare-table').innerHTML = `
    <table class="table table-sm mb-0">
      <thead><tr>
        <th>자산군</th><th class="text-end">현재</th><th class="text-end">목표</th><th class="text-end">차이</th><th></th>
        <th class="text-end">현재금액(등락률)</th>
        <th class="text-end">기준금액(과부족)</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;

  // 차트(rbChart) 부분은 기존과 동일
  ...
}
```

### 5-3. 표 최종 컬럼 (전/후 비교)

| 변경 전 | 변경 후 |
|---|---|
| 자산군 · 현재% · 목표% · 차이% · 진행바 · **금액** | 자산군 · 현재% · 목표% · 차이% · 진행바 · **현재금액(등락률)** · **기준금액(과부족금액)** |

화면 예시(총자산 1억, 미국장기채 배지 40%):

```
[미국장기채]  38.2%   40%   -1.8%  [====      ]   38,200,000원 (+6.4%)   40,000,000원 (-1,800,000원)
[S&P     ]  31.5%   30%   +1.5%  [=====     ]   31,500,000원 (+18.2%)  30,000,000원 (+1,500,000원)
[현금     ]   7.5%    7.5%   0.0%  [=         ]    7,500,000원 (-)        7,500,000원 (0원)
```

---

## 6. 엣지 케이스 처리

| 상황 | 처리 |
|---|---|
| 총자산(grandTotal) = 0 | 기준금액 = 0, 과부족 = 0, 등락률 = '-' |
| 자산군 매입원가 합계 = 0 (배정 종목 없음/전량매도) | 등락률 '-' 표시 |
| 현금(cash) | 등락률 개념 없음 → 항상 '-' |
| 외화(해외상장) 종목이 섞인 경우 | 기존 `eval_amount` 합산과 동일한 한계(환산 미적용) 유지, 등락률(종목 단위 %)은 통화 무관하게 정확 |
| `avg_price`가 NaN(거래 없음) | `calc_position` 결과 NaN 가드 후 `cost_amount=0` → 등락률 '-' |

---

## 7. 구현 순서

```
1단계: app.py - api_rebalance_get()에 calc_position() 기반 avg_price/cost_amount/return_rate 계산 추가
2단계: investments.html - getRbTotals()에서 costTotals 함께 반환하도록 수정 (+ 호출부 반영)
3단계: investments.html - updateRbChart()에서 targetAmt(기준금액)/gapAmt(과부족) 계산 및 컬럼 추가
4단계: investments.html - updateRbChart()에서 자산군별 등락률(rateHtml 재사용) 계산 및 컬럼 추가
5단계: rb-compare-table 헤더/셀 마크업 수정, 반응형(모바일) 레이아웃 확인
6단계: 수동 테스트 — 총자산 0원, 미배정 종목만 있는 경우, 현금만 있는 경우, 등락률 +/-/0 케이스 확인
```

## 8. 변경 파일 목록

- `app.py` — `api_rebalance_get()` 수정
- `templates/investments.html` — `getRbTotals()`, `updateRbChart()`, `rb-compare-table` 마크업 수정
