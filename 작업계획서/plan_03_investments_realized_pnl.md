# 기능 계획서 #3 — 투자 관리 매매거래 내역 내 실현 손익 추가

> **목적**: 주식 및 ETF 매매거래 내역(거래 정보)에 '실현 손익' 열을 추가하여 매도 거래 시 발생한 실현 손익을 개별적으로 기록/수정할 수 있도록 하고, 포지션 현황의 총 실현 손익 집계에 반영되도록 한다.

---

## 1. 현황 분석

### 현재 구조
* **매매 거래내역 테이블 (`stock_tx`, `etf_tx`)**:
  * 현재 컬럼: `id`, `stock_id` / `etf_id`, `tx_date`, `tx_type`, `price`, `quantity`, `fee`, `memo`, `exchange_rate`.
  * `realized_pnl`(실현 손익)에 대한 컬럼이 존재하지 않음.
* **실현 손익 계산 패턴 (`app.py` - `calc_position()`)**:
  * 개별 주식/ETF의 총 실현 손익(`realized_pnl`)은 매수 거래의 평균 단가를 추적(선입선출/이동평균)한 뒤, 매도 거래가 발생할 때마다 `(매도가 - 평균단가) * 수량` 공식을 사용하여 실시간 계산해 합산함.
* **문제점**:
  * 실제 증권사 수수료, 세금 및 기타 오차로 인해 시스템이 계산한 실현 손익과 실제 실현 손익 사이에 미세한 차이가 발생할 수 있음.
  * 사용자가 매도 거래 시 실제 발생한 실현 손익을 직접 입력하거나 수정할 수 있는 방법이 없음.

---

## 2. DB 변경 사항

### 2-1. 신규 컬럼 추가
`stock_tx` 및 `etf_tx` 테이블에 각각 실현 손익을 저장하기 위한 `realized_pnl` 컬럼을 추가합니다.
(외국 주식/ETF 거래 시 소수점이 발생할 수 있고, 원화 환산 전 원래 통화 단위로 저장될 수 있도록 `REAL` 타입으로 설정합니다.)

```sql
-- stock_tx 테이블
ALTER TABLE stock_tx ADD COLUMN IF NOT EXISTS realized_pnl REAL DEFAULT 0.0;

-- etf_tx 테이블
ALTER TABLE etf_tx ADD COLUMN IF NOT EXISTS realized_pnl REAL DEFAULT 0.0;
```

### 2-2. 기존 데이터 마이그레이션 (선택적 보정)
데이터베이스 초기화(`init_db`) 시점에 기존 `sell` 거래 내역들의 `realized_pnl`이 `0.0`으로 비어 있을 것이므로, 이동평균선 기반으로 계산한 최초 값을 일괄적으로 채워넣는 SQL/Python 마이그레이션 코드를 실행합니다.

---

## 3. 백엔드 변경 사항 (`app.py`, `database.py`)

### 3-1. `database.py` - 마이그레이션 추가
`init_db()` 내의 `migrations` 목록에 아래 구문을 추가합니다.
```python
"ALTER TABLE stock_tx ADD COLUMN IF NOT EXISTS realized_pnl REAL DEFAULT 0.0",
"ALTER TABLE etf_tx ADD COLUMN IF NOT EXISTS realized_pnl REAL DEFAULT 0.0",
```

또한, 기존 데이터에 대하여 최초 1회 실현 손익을 계산하여 업데이트하는 로직을 마이그레이션에 포함시킵니다. (또는 `app.py` 구동 시 수행)

### 3-2. `app.py` - 포지션 계산 및 API 수정

#### ① `calc_position(transactions)` 수정
매도 거래(`sell`) 누적 시 기존의 수식 계산 대신 DB에 기록된 `realized_pnl` 값을 우선적으로 사용하도록 변경하되, 만약 해당 값 또는 컬럼이 없는 레거시 데이터일 경우 계산된 값을 쓰도록 대체 패턴을 구성합니다.
```python
def calc_position(transactions):
    qty = 0.0
    avg_cost = 0.0
    realized = 0.0
    for tx in transactions:
        tq = float(tx['quantity'] or 0)
        tp = float(tx['price'] or 0)
        if tq <= 0:
            continue
        if tx['tx_type'] in ('buy', '매수'):
            new_qty = qty + tq
            avg_cost = (qty * avg_cost + tq * tp) / new_qty if new_qty > 0 else 0.0
            qty = new_qty
        else:  # sell
            # DB에 기록된 실현 손익을 사용 (원화 환산 전 통화 기준)
            tx_realized = tx.get('realized_pnl')
            if tx_realized is not None:
                realized += float(tx_realized)
            else:
                realized += (tp - avg_cost) * tq
            qty = max(0.0, qty - tq)
    return qty, avg_cost, realized
```

#### ② 주식/ETF 조회 API 수정 (`/api/stocks`, `/api/etf` GET)
`stock_tx` 및 `etf_tx`에서 데이터를 가져올 때 `realized_pnl` 컬럼도 함께 불러오도록 쿼리를 보완합니다.
```python
# /api/stocks
cur.execute("SELECT stock_id, tx_type, price, quantity, COALESCE(fee,0) as fee, COALESCE(realized_pnl,0) as realized_pnl FROM stock_tx ORDER BY stock_id, tx_date, id")

# /api/etf
cur.execute("SELECT etf_id, tx_type, price, quantity, COALESCE(fee,0) as fee, COALESCE(realized_pnl,0) as realized_pnl FROM etf_tx ORDER BY etf_id, tx_date, id")
```

#### ③ 주식/ETF 거래 API 수정 (`/api/stock-tx`, `/api/etf-tx` GET/POST/PUT)
* **GET**: 거래내역 목록 조회 쿼리에 `t.realized_pnl` 추가
* **POST/PUT**: 사용자가 입력한 `realized_pnl` 값을 받아서 DB에 저장/업데이트
  * 만약 사용자가 직접 값을 입력하지 않고 비워뒀거나 NULL인 경우, 직전까지의 평균 단가를 구하여 자동으로 `(매도가 - 평균단가) * 수량` 값을 계산하여 삽입하는 예외 보정 로직을 백엔드 단에도 추가합니다.

---

## 4. 프론트엔드 변경 사항 (`templates/investments.html`)

### 4-1. HTML 테이블 컬럼 추가
`stockTxTable` 및 `etfTxTable` 매매 거래내역 테이블의 `<thead>` 영역에 `실현손익` 열을 하나 추가합니다.
```html
<!-- stockTxTable 예시 -->
<thead class="table-light">
  <tr>
    <th>날짜</th><th>종목</th><th>구분</th>
    <th class="text-end">단가</th>
    <th class="text-end">수량</th>
    <th class="text-end">거래금액</th>
    <th class="text-end">수수료</th>
    <th class="text-end">실현손익</th> <!-- 추가 -->
    <th>메모</th>
    <th class="text-center">삭제</th>
  </tr>
</thead>
```

### 4-2. GridTable 컬럼 설정 및 이벤트 제어 (`investments.html` 스크립트)

#### ① `stockTxGrid` / `etfTxGrid` 컬럼 매핑 추가
* `realized_pnl` 컬럼을 입력 가능한 `number` 타입으로 추가합니다.
* 매수(`buy`) 거래일 때는 실현 손익이 없으므로 회색 표시(`-`) 또는 `0`으로 보여주고, 매도(`sell`) 거래일 때만 수익/손실 색상(`pnlHtml`)으로 렌더링합니다.
* 외화 거래의 경우 환율을 감안하여 화면에는 원화 환산 금액을 표시하지만, 편집 입력 창에는 원래 화폐 단위(예: 달러)로 입력하도록 유도합니다.

```javascript
{ 
  key: 'realized_pnl', 
  type: 'number', 
  align: 'end',
  render: (v, r) => {
    if (r.tx_type === 'buy' || r.tx_type === '매수') return '-';
    return pnlHtml(toKrw(v || 0, r.ticker));
  }
}
```

#### ② `onStartEdit` 콜백을 통한 동적 계산 및 비활성화 처리
* 행 편집이 시작될 때(`onStartEdit`), 거래 구분이 "매수"인 경우 실현손익 입력을 비활성화(`disabled`)하고 값을 `0`으로 세팅합니다.
* 거래 구분이 "매도"인 경우, 해당 주식/ETF의 보유 평균단가(`avg_price`)를 조회하여 **자동으로 계산된 실현손익을 초기 입력값으로 세팅**해줍니다.
  * 계산식: `(매도단가 - 평균단가) * 매도수량`
  * 사용자는 이 계산된 초기값을 확인하고, 오차가 있다면 직접 수정하여 저장할 수 있습니다.
* 거래 구분(`tx_type`) 셀렉트 박스의 변경 이벤트를 감시하여, "매수"로 바꾸면 실현손익 인풋을 끄고 "매도"로 바꾸면 다시 계산값을 채워 활성화시키는 동적 바인딩을 추가합니다.

---

## 5. 구현 시 주의사항 및 예외 처리

1. **외화 환산 처리**:
   * 해외 주식의 경우 `realized_pnl`은 달러($) 기준으로 입력/저장되며, 화면에서 최종적으로 합산 및 렌더링될 때는 `exchange_rate`를 곱해 원화로 변환됩니다. 이 일관성이 유지되도록 처리해야 합니다.
2. **평균단가 데이터 매칭**:
   * 매도 거래 입력 시 종목의 현재 평균단가(`avg_price`) 정보가 필요하므로 `allStocks` 및 `allEtfs` 전역 변수에서 정확히 해당 종목의 `avg_price`를 찾아서 가져오도록 처리합니다.
3. **신규 거래 등록 시 기본값**:
   * 등록 시 `price`와 `quantity` 입력 칸이 빈 상태이므로 초기 계산 손익은 0 또는 빈 상태로 둡니다. 단가와 수량을 입력하는 중 실시간으로 실현손익 입력칸의 기본값이 계산되어 채워지도록 편의 기능을 구현합니다.
