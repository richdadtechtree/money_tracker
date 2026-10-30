# 기능 계획서 #4 — 투자 관리 대개편 (계좌별 관리 · 예수금 · 계좌 이체 · 연 단위 손익)

> **목적**: 투자 관리를 "종목 중심"에서 "계좌 중심"으로 바꾼다.
> 계좌별로 종목·손익을 관리하고, 계좌마다 예수금(증권사에 넣어둔 현금)을 갖게 하며,
> 매수/매도·계좌 간 이체가 예수금에 자동 반영되게 한다. 상단 대시보드는 연 단위 손익을 보여주고, 과거 연도는 별도 공간에서 본다.
>
> **진행 방식**: 아래 Step 1 → 9를 **순서대로, 한 Step씩 따로 배포·확인**한다. 각 Step 끝의 "완료 확인"을 통과해야 다음으로 넘어간다.

---

## 0. 현황 분석 (코드 확인 결과)

| 항목 | 현재 상태 | 위치 |
|---|---|---|
| 계좌 개념 | **없음**. `stocks`/`etf`는 종목 마스터, 거래는 `stock_tx`/`etf_tx`에 종목 단위로만 저장 | `database.py` 216~250, 479 |
| 매수 시 현금 | 매수/매도하면 `cash_auto_adjustments`에 기록하고 **현금관리에서 잔액이 가장 큰 통장**의 금액을 증감 | `app.py` `_upsert_cash_adj` (4985), 호출부 1829·1870·2048·2099·3159·3176·5187·5206 |
| 같은 함수의 다른 사용처 | **부동산 납부(`re_payment`)도 같은 함수로 현금을 조정** → 건드리면 안 됨 | `app.py` 4714·4762 |
| 현금관리 | `cash_deposits`(통장명, KRW/USD, 합계). 모든 금액을 직접 수정 가능 | `templates/cash.html`, `app.py` 5051~ |
| 현금 합계 사용처 | `SUM(cash_deposits.amount)`을 대시보드·테크트리·생애주기·리밸런싱·스냅샷 등 **9곳 이상**에서 직접 사용 | `app.py` 5715, 5803, 6315, 6611, 6962, 7417, 7562, 7902, 8960 |
| 실현손익 계산 | 종목별(`source`, `asset_id`) 이동평균으로 계산. 공모주(`ipo`) 포함 | `_calc_realized_records()` (5215) |
| 총손익 카드 | 실현손익은 **전 기간 누적**, 평가손익은 현재 보유분. 연 단위 구분 없음 | `/api/total-pnl` (5556~), `investments.html` 상단 카드 |
| DB | 운영은 PostgreSQL(Render). 저장소의 `finance.db`(SQLite)는 옛 파일이라 무관 | `claude.md` |

### 핵심 설계 결정 (먼저 합의 필요한 부분은 §11에 모음)

1. **예수금은 저장하지 않고 "원장(거래 장부)의 합계"로 계산한다.**
   잔액 숫자를 직접 들고 있으면 거래 수정/삭제 때 어긋난다(지금 `_upsert_cash_adj`가 그 구조). 입금·출금·이체·매수·매도를 모두 `account_cash_tx`에 한 줄씩 적고, 잔액 = 합계. 틀어져도 원장을 다시 합산하면 복구된다.
2. **현금관리의 "예수금" 행은 `cash_deposits`에 잠금 행 1개로 두고, 모든 계좌 예수금 합계와 자동 동기화한다.**
   그러면 위 9곳의 `SUM(cash_deposits.amount)`을 하나도 고치지 않아도 순자산이 맞게 나온다. (가장 안전한 방법)
3. **손익은 "계좌 × 종목" 단위로 계산한다.** 같은 종목을 두 계좌에 갖고 있으면 평단가도 계좌마다 따로.
4. **"기초 보유(opening)" 거래 유형을 추가한다.** 데이터를 새로 입력할 때 "현재 보유 수량·평단가"만 넣고 예수금은 건드리지 않는 용도. 이게 없으면 지금 보유 종목을 다시 입력할 때마다 예수금이 깎인다.

---

## Step 1. 백업 및 올해 실현손익 보존

**왜 먼저?** 이후 단계에서 거래 데이터를 초기화한다. 올해 실현손익만은 반드시 남겨야 한다.
실현손익은 과거 매수 평단가에 의존하므로, 거래를 지우면 재계산이 불가능하다 → **지금 계산된 값을 그대로 박제**한다.

### 작업
1. 운영 DB 전체 백업 (`pg_dump`) — 되돌릴 수 있게 파일로 보관. (사용자가 직접 실행, 명령어는 계획 진행 시 안내)
2. 신규 테이블 `realized_pnl_archive` (마이그레이션 목록에 `CREATE TABLE IF NOT EXISTS`):
   ```sql
   CREATE TABLE IF NOT EXISTS realized_pnl_archive (
       id          SERIAL PRIMARY KEY,
       year        INTEGER NOT NULL,
       tx_date     DATE,
       source      TEXT,            -- stock / etf / ipo / crypto
       name        TEXT,
       ticker      TEXT,
       pnl         BIGINT NOT NULL, -- 원화
       cost        BIGINT DEFAULT 0,
       account_id  INTEGER,         -- 나중에 Step 2 이후 계좌 배정(NULL=미분류)
       memo        TEXT
   );
   ```
3. **API로 구현** (스크립트 대신): `app.py`를 import하면 버전 자동 증가·스케줄러가 같이 실행되는 부작용이 있어 별도 스크립트보다 API가 안전하다.
   - `GET /api/realized-archive?year=2026` : 저장된 합계 + 현재 거래 기준 미리보기 합계 + 일치 여부(`match`)
   - `POST /api/realized-archive` `{"year":2026}` : 올해 실현손익(주식·ETF·공모주 = `_calc_realized_records()` 결과, 코인 = `crypto_sell`)을 박제. 저장 직후 합계를 다시 읽어 불일치 시 **롤백**.
   - **이미 저장된 연도는 `overwrite:true` 없이는 409로 거부** — 데이터 초기화 후 실수로 다시 실행해 빈 값으로 덮어쓰는 사고 방지.
4. 알아둘 점: 해외 종목 손익은 박제 시점의 환율로 원화 환산되어 고정된다. 코인 매도는 현재 총손익 카드에는 안 들어가지만, 연도 실현손익(Step 7)에 합산하기 위해 함께 박제한다.

### 완료 확인
- `GET` 응답의 `match`가 true (저장 합계 == 현재 2026 실현손익 합계: 주식+ETF+공모주+코인)
- 같은 연도를 다시 POST하면 409로 거부되고 기존 합계가 그대로임

---

## Step 2. 계좌 마스터 + 거래에 계좌 연결 + 데이터 초기화

### DB (`database.py` `migrations` 목록, 모두 `IF NOT EXISTS`)
```sql
CREATE TABLE IF NOT EXISTS invest_accounts (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,           -- 예: "키움 일반", "토스 ISA"
    broker      TEXT,
    acct_type   TEXT DEFAULT '일반',     -- 일반 / ISA / 연금저축 / IRP 등 (표시용)
    sort_order  INTEGER DEFAULT 0,
    is_active   BOOLEAN DEFAULT TRUE,
    memo        TEXT
);
ALTER TABLE stock_tx ADD COLUMN IF NOT EXISTS account_id INTEGER REFERENCES invest_accounts(id);
ALTER TABLE etf_tx   ADD COLUMN IF NOT EXISTS account_id INTEGER REFERENCES invest_accounts(id);
```
- `tx_type`에 `init`(기초 보유) 허용. 기존 코드가 `buy/매수`가 아니면 전부 매도로 처리하는 곳이 많다(`_calc_realized_records`, `/api/total-pnl` 등) → **`init`을 매수와 동일하게 취급하도록 해당 분기 전부 수정** (놓치면 기초 보유가 매도로 계산되는 큰 버그. `grep "tx_type"`로 전수 점검).
- 코인(`crypto`)·공모주(`ipo`)는 이번 범위에서 **계좌 연결 제외**(§11 결정사항 참고). 실현손익은 대시보드에 그대로 합산.

### API / 화면
- `GET/POST /api/invest-accounts`, `PUT/DELETE /api/invest-accounts/<id>` (거래가 있는 계좌는 삭제 대신 `is_active=false`)
- `investments.html` 주식/ETF 탭 상단에 **계좌 선택 칩**(전체 / 계좌1 / 계좌2 …) + 거래 입력 폼에 계좌 필수 선택

### 데이터 초기화 (이 Step 마지막, 일회성 스크립트 `scripts/reset_invest_data.py`)
- 지우는 것: `stock_tx`, `etf_tx`, `stocks`, `etf`, `cash_auto_adjustments`(주식/ETF 분만), 분할매수·투자계획 실행 기록 중 거래와 연결된 것
- **남기는 것**: `realized_pnl_archive`(Step 1), 코인/공모주 데이터, 부동산 납부 관련 `cash_auto_adjustments`(`source_type='re_payment'`)
- 실행 전 `--dry-run`으로 지울 행 수 출력 → 사용자 확인 후 `--apply`. 운영 `init_db`에 자동 실행되지 않게 분리.
- 초기화 후 사용자가: 계좌 등록 → 종목별 `init`(기초 보유)로 현재 보유분 입력.

### 완료 확인
- 계좌 3개 생성, 계좌별로 `init` 거래 입력 시 종목 목록이 계좌별로 분리되어 보임
- 기초 보유 입력 후 `/api/total-pnl`의 실현손익이 변하지 않음(매도로 오인 안 함)

---

## Step 3. 계좌별 포지션 · 손익 계산

### 백엔드
- `calc_position()`(1451), `_calc_realized_records()`(5215), `compute_realized_pnl_map()`(1582) 의 그룹 키를 `(source, asset_id)` → **`(source, asset_id, account_id)`** 로 변경. 결과 레코드에 `account_id` 포함.
- 신규 `GET /api/invest-accounts/summary?year=YYYY` → 계좌별 `{평가금액, 매입금액, 평가손익, 실현손익, 예수금}` 반환 (예수금은 Step 4 이후 채움).
- 아카이브(`realized_pnl_archive`)는 실현손익 집계 함수에서 `UNION`으로 합산 (연도 필터 적용).
- 기존 `/api/stocks`·`/api/etf`·`/api/stocks-etf-total`은 응답 형태를 유지한 채 `account_id` 쿼리 파라미터만 추가(미지정=전체). 다른 화면(대시보드·테크트리 등)이 깨지지 않게.

### 화면
- 계좌 칩 선택 시 종목 표/거래내역/손익이 해당 계좌로 필터링. "전체"는 합산(같은 종목은 합쳐서 표시).

### 주의/디버깅 힌트
- 같은 종목을 계좌 A에서 사고 B에서 팔 수는 없음 → 계좌 단위 수량이 음수가 되면 입력 단계에서 경고.
- 해외주식 환율: 기존처럼 거래 시점 `exchange_rate` 사용.

### 완료 확인
- 같은 종목을 두 계좌에 다른 평단으로 입력 → 계좌별 평단·평가손익이 각각 맞고, "전체"는 가중평균으로 일치
- 기존 대시보드 주식/ETF 평가금액이 변하지 않음

---

## Step 4. 예수금 원장 + 현금관리 "예수금" 행(수정 불가)

### DB
```sql
CREATE TABLE IF NOT EXISTS account_cash_tx (
    id          SERIAL PRIMARY KEY,
    account_id  INTEGER NOT NULL REFERENCES invest_accounts(id),
    tx_date     DATE NOT NULL,
    currency    TEXT NOT NULL DEFAULT 'KRW',   -- KRW / USD  (계좌 하나가 두 통화 예수금을 동시에 가질 수 있음)
    kind        TEXT NOT NULL,   -- init / deposit / withdraw / transfer_in / transfer_out / buy / sell / dividend / fee / exchange
    amount      NUMERIC(18,4) NOT NULL, -- 해당 통화 단위의 증가(+) / 감소(-). KRW는 원, USD는 달러(소수)
    ref_type    TEXT,            -- stock_tx / etf_tx / transfer / exchange
    ref_id      INTEGER,
    memo        TEXT,
    created_at  TIMESTAMP DEFAULT NOW(),
    UNIQUE (ref_type, ref_id, account_id, currency)   -- 같은 거래가 중복 기록되지 않게 (환전은 KRW·USD 2줄)
);
ALTER TABLE cash_deposits ADD COLUMN IF NOT EXISTS is_system BOOLEAN DEFAULT FALSE;
```
- `cash_deposits`에 `name='예수금'`, `is_system=TRUE` 행 1개를 `init_db`에서 보장(없으면 생성).

### 백엔드
- `get_account_cash(db, account_id=None)`: 원장 합계 계산 함수 (단일 계좌 / 전체). **통화별로 `{krw, usd}` 두 값**을 반환.
- `_sync_deposit_row(db)`: 전체 합계를 계산해 `cash_deposits`의 예수금 행에 `krw_amount`=KRW 합계, `usd_amount`=USD 합계, `amount`=KRW + USD×환율로 기록. (이 테이블은 이미 KRW·USD 동시 보유 구조이고 `_refresh_usd_cash_amounts`가 환율 갱신 시 `amount`를 다시 계산하므로 별도 환산 코드가 필요 없음) **원장에 쓰는 모든 코드가 같은 트랜잭션에서 호출**.
- 기초 예수금 입력 / 입금·출금 수동 기록 API: `POST /api/invest-accounts/<id>/cash` (kind = init/deposit/withdraw/dividend/fee, **currency = KRW/USD 선택**).
- **환전 API** `POST /api/invest-accounts/<id>/exchange`: 같은 계좌 안에서 KRW↔USD 전환. 원장에 KRW 줄과 USD 줄 2개를 한 트랜잭션으로 기록 (`kind='exchange'`, 적용 환율 입력 가능, 기본값=현재 환율).
- **잠금**: `PUT/DELETE /api/cash-deposits/<id>`(5077)에서 `is_system` 행이면 403 + 안내 메시지. (직접 수정 시 합계가 어긋나는 것 방지)
- `api_cash_deposits_detail`(5077~5100)이 통장 수정 시 `DELETE FROM cash_auto_adjustments` 를 전체 삭제하는 코드 확인됨 → 부동산 납부 조정 기록까지 지우지 않도록 `source_type IN ('stock_tx','etf_tx')`로 한정하거나 제거.

### 화면
- `cash.html`: 예수금 행은 자물쇠 아이콘 + 입력칸 비활성 + "계좌 합계 자동 연동" 배지. 클릭하면 계좌별 예수금 내역 펼침(읽기 전용).
- `investments.html`: 계좌 칩 옆에 해당 계좌 예수금을 **원화 / 달러 두 칸**으로 표시 + 입금/출금/환전 버튼.

### 완료 확인
- 계좌별 예수금 입력 → 현금관리 예수금 행이 합계와 같고 수정 불가
- 원화·달러를 둘 다 입력 → 예수금 행의 원화/달러/환산 합계가 각각 맞음, 환전 시 원화↓ 달러↑ 이고 환산 합계는 (환율 차이 외) 변하지 않음
- 대시보드 순자산(현금 포함)이 입력 전후로 예수금만큼만 변함 (이중 계상 없음)

---

## Step 5. 매수/매도 ↔ 예수금 연동

### 규칙
| 거래 | 예수금 원장 |
|---|---|
| 국내 종목 매수 | KRW 예수금 `-(가격 × 수량 + 수수료)` |
| 국내 종목 매도 | KRW 예수금 `+(가격 × 수량 - 수수료)` |
| 해외 종목 매수 | **기본 USD 예수금** `-(가격 × 수량 + 수수료)` (달러 그대로) |
| 해외 종목 매도 | **기본 USD 예수금** `+(가격 × 수량 - 수수료)` |
| 기초 보유(init) | 기록 없음 |

- 거래 입력 폼에 **"결제 통화" 선택**(KRW / USD)을 둔다. 기본값은 국내=KRW, 해외=USD.
  해외 종목을 원화 예수금으로 결제(증권사 자동환전)하는 경우 KRW를 선택하면 `거래금액 × 거래 환율`을 원화로 차감한다.
- 국내 종목은 항상 KRW 예수금만 사용.

### 작업
- 신규 `_upsert_account_cash(cur, account_id, ref_type, ref_id, ...)` / `_remove_account_cash(...)` — 기존 `_upsert_cash_adj` 패턴(거래 수정 시 이전 기록 교체, 삭제 시 역적용)을 원장 방식으로 구현. (원장은 `ref`로 upsert하므로 "역적용 계산"이 필요 없음)
- 호출부 교체: `app.py` 1829·1832·1870~1887(주식), 2048~2104(ETF), 3159~3192(분할매수/투자계획 실행·취소), 5187·5206(`recalc-foreign`)
  **`re_payment`(4714·4762)는 기존 `_upsert_cash_adj` 그대로 유지.**
- 이미 `_sync_deposit_row`를 같은 트랜잭션에서 호출.
- 예수금 부족 시(**통화별로** 판단): 입력은 **허용하되 경고 표시**(과거 거래를 순서 없이 입력하다 일시적으로 마이너스가 될 수 있음). 예수금이 음수인 계좌는 목록에서 빨간색.
- `account_id` 없는 거래 저장은 400 에러(필수).
- 분할매수/투자계획 화면(`split_buy_*`, `invest_plan_*`)의 "실행" 버튼에도 계좌 선택 추가.

### 주의/디버깅 힌트
- 거래 **수정**에서 계좌를 A→B로 바꾸면 A 원장은 삭제, B에 신규 기록해야 함(UNIQUE가 `account_id` 포함이라 자연스럽게 처리되지만 이전 행 삭제 로직을 꼭 확인).
- 이전 방식(잔액 최대 통장 차감)이 남아 있으면 이중 차감 → `grep _upsert_cash_adj`로 stock/etf 호출이 0건인지 확인.

### 완료 확인
- 국내 매수 100만원 → 해당 계좌 원화 예수금 -100만원, 현금관리 예수금 행도 -100만원, 다른 통장 불변
- 해외 매수 $1,000 → 해당 계좌 달러 예수금 -$1,000 (원화 예수금 불변), 현금관리 예수금 행의 달러 칸도 -$1,000
- 해당 매수 수정(수량 변경)/삭제 → 예수금 정확히 복구
- 부동산 납부 입력은 기존처럼 현금 통장을 조정

---

## Step 6. 계좌 간 이체

### DB
```sql
CREATE TABLE IF NOT EXISTS account_transfers (
    id            SERIAL PRIMARY KEY,
    tx_date       DATE NOT NULL,
    from_type     TEXT NOT NULL,   -- 'invest' (증권 예수금) / 'bank' (현금관리 통장)
    from_id       INTEGER NOT NULL,
    to_type       TEXT NOT NULL,
    to_id         INTEGER NOT NULL,
    currency      TEXT NOT NULL DEFAULT 'KRW',   -- KRW / USD (이체는 같은 통화끼리)
    amount        NUMERIC(18,4) NOT NULL CHECK (amount > 0),
    memo          TEXT,
    created_at    TIMESTAMP DEFAULT NOW()
);
```
### 동작
- 증권 → 증권: 출금 계좌 원장 `transfer_out(-)`, 입금 계좌 원장 `transfer_in(+)` 을 **한 트랜잭션**에서 기록 (`ref_type='transfer'`, `ref_id=이체 id`).
- 은행 ↔ 증권: 은행 쪽은 `cash_deposits.krw_amount`(KRW) 또는 `usd_amount`(USD)와 `amount`를 증감, 증권 쪽은 원장 기록. 은행 통장에 해당 통화 잔액이 없으면 경고.
- 이체 삭제/수정 시 양쪽 모두 원복. 출금 계좌 = 입금 계좌면 거부.
- 화면: 투자관리에 "이체" 버튼 → 모달(출금 계좌, 입금 계좌, **통화**, 금액, 날짜, 메모) + 이체 내역 표.

### 완료 확인
- A→B 50만원: A 예수금 -50만, B +50만, 전체 예수금 합계 불변 (현금관리 예수금 행 불변)
- 은행→증권: 은행 -50만, 예수금 +50만, 순자산 불변
- 이체 삭제 시 양쪽 복구, 도중 오류 시 한쪽만 반영되지 않음(롤백)

---

## Step 7. 상단 대시보드: 연 기준 총손익 / 실현손익 / 평가손익

### 정의 (확정)
- **실현손익(연)** = 해당 연도 매도 실현손익 합 (주식·ETF·공모주·코인 + 아카이브)
- **평가손익** = 현재 보유 종목의 **(현재가 − 매입 평균단가) × 수량** 합계. (올해 증감이 아니라 "지금 보유분의 평가손익")
  - 현재 연도: 실시간 계산. 과거 연도: 그 해 말에 저장해 둔 값(Step 8).
  - 해외 종목은 현재 환율로 원화 환산.
- **총손익(연)** = 실현손익(연) + 평가손익
  - 연초 기준값 입력이 필요 없다. (예전 계획의 "2026 연초 평가손익 입력"은 삭제)
- 월간 그래프는 기존 방식(월말 평가금액 − 누적 순매수의 월별 증감)을 **그대로 유지**하고 선택 연도의 12개월만 보여준다. 카드의 총손익과 정의가 달라 합이 일치하지 않을 수 있으므로 그래프 설명 문구에 그 점을 명시한다.

### 백엔드
- `/api/total-pnl?year=YYYY` 확장 (기본값=올해). 응답에 `accounts: [{id,name,realized,unrealized,total}]` 포함.
- 월간 그래프도 선택 연도의 12개월로 표시.

### 화면
- 상단 카드 제목 옆에 **연도 선택(◀ 2026 ▶)**. 카드: 총손익 / 실현손익 / 평가손익(+수익률) — 전체 계좌 합산.
- 카드 아래 접이식 "계좌별 손익" 표(계좌, 평가금액, 예수금, 실현, 평가, 총).

### 완료 확인
- 계좌별 합 == 카드 합계
- 2026 실현손익 = 아카이브 + 신규 입력 매도분, Step 1에서 보존한 숫자와 일치(신규 매도 입력 전)
- 평가손익 = 종목 표의 (현재가 − 평단) × 수량 합계와 일치

---

## Step 8. 과거 연도 데이터 공간 ("연도별 기록" 탭)

### DB
```sql
CREATE TABLE IF NOT EXISTS account_year_snapshots (
    id              SERIAL PRIMARY KEY,
    year            INTEGER NOT NULL,
    account_id      INTEGER REFERENCES invest_accounts(id),  -- NULL = 코인/공모주 등 계좌 외
    eval_amount     BIGINT DEFAULT 0,    -- 연말 평가금액
    cost_amount     BIGINT DEFAULT 0,    -- 연말 매입금액
    unrealized_pnl  BIGINT DEFAULT 0,    -- 연말 시점 평가손익 (보유분의 현재가−평단 기준)
    realized_pnl    BIGINT DEFAULT 0,    -- 해당 연도 실현손익
    cash_krw        BIGINT DEFAULT 0,    -- 연말 원화 예수금
    cash_usd        NUMERIC(18,2) DEFAULT 0, -- 연말 달러 예수금
    is_manual       BOOLEAN DEFAULT FALSE,
    memo            TEXT,
    UNIQUE (year, account_id)
);
```
- 기존 `APScheduler`에 **12/31 23:59 연말 스냅샷 작업** 추가(`app.py` 스케줄러 영역, 매일 23:59:30 스냅샷 작업 옆). 올해 값은 마감 전까지 실시간 계산이므로 이 테이블에 안 쌓아도 됨.
- 과거 연도(2025 이전)는 **수기 입력/수정 가능**(`is_manual=true`) — 데이터가 사라졌으므로 필요.

### 화면
- 투자관리 탭에 **"연도별 기록"** 추가:
  연도 × (총손익 / 실현 / 평가 / 연말 평가금액 / 입출금) 표 + 연도 선택 시 계좌별 상세. 막대 그래프(연도별 총손익).
- 과거 연도 행은 편집 가능, 올해 행은 자동 계산(읽기 전용)(연말에 자동 저장되기 전까지).

### 완료 확인
- 연도 추가/수정/삭제 동작, 상단 카드에서 해당 연도 선택 시 같은 숫자가 보임

---

## Step 9. 정리 및 문서

- 사용하지 않게 된 코드 제거: stock/etf용 `_upsert_cash_adj` 호출, 현금관리의 "자동 조정 적용" UI(`/api/cash-auto-adjustments*` 중 stock/etf 관련)
- `claude.md` 스키마 요약에 신규 테이블 5개(`invest_accounts`, `account_cash_tx`, `account_transfers`, `account_year_snapshots`, `realized_pnl_archive`) 반영
- 회귀 점검 체크리스트: 대시보드 순자산, 테크트리, 생애주기 시뮬레이션, 리밸런싱의 현금 값이 Step 4 이전과 일치

---

## 10. 위험 요소와 대응

| 위험 | 대응 |
|---|---|
| 데이터 초기화 실수 | `pg_dump` 백업 + `--dry-run` 후 `--apply`, `init_db`에 자동 실행 금지 |
| `init`(기초 보유)을 매도로 오인 | `tx_type` 분기 전수 점검(`grep tx_type`), Step 2 완료 확인에 포함 |
| 예수금 이중 반영(옛 방식 + 새 방식) | Step 5 종료 시 stock/etf 대상 `_upsert_cash_adj` 호출 0건 확인 |
| 부동산 납부 현금 조정이 깨짐 | `re_payment` 경로는 건드리지 않고, 통장 수정 시 전체 삭제 코드(5090)만 한정 |
| 이체 도중 한쪽만 반영 | 한 트랜잭션 + 예외 시 `rollback` |
| 올해 실현손익 중복 집계 | 올해 이미 팔린 종목의 매도 거래는 **다시 입력하지 않기**(아카이브가 대신함) |
| 원화 환산 오차 | 달러는 달러 그대로 원장에 저장(환산하지 않음). 원화 환산은 표시할 때만 현재 환율 사용 |
| 달러 예수금 환율 변동으로 순자산이 매일 변함 | 의도된 동작 (기존 달러 통장과 동일). `_refresh_usd_cash_amounts`가 갱신 |

## 11. 결정 사항

**확정**
- 연 평가손익 = **현재 보유분의 (현재가 − 매입 평균단가) 기준 평가손익**, 총손익 = 연 실현손익 + 평가손익 (연초 기준값 입력 없음)
- 예수금은 **원화·달러 모두 입력/관리**, 계좌 안에서 환전 가능

**추천대로 진행 예정 (이견 있으면 알려주세요)**
1. 코인·공모주는 이번엔 계좌 연결 제외, 손익만 대시보드에 합산
2. 은행 통장 ↔ 증권 계좌 이체도 지원 (원화/달러 각각)

**Step 2 진행 시 필요**: 계좌 목록(이름/종류)
