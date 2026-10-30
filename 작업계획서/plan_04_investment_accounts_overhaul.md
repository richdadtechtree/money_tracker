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

## Step 2. 계좌 마스터 + 거래에 계좌 연결 + 데이터 초기화 ✅ 구현됨

### 구현된 DB (`database.py`, 모두 `IF NOT EXISTS`)
```sql
CREATE TABLE IF NOT EXISTS invest_accounts (
    id SERIAL PRIMARY KEY, name TEXT NOT NULL, broker TEXT, acct_type TEXT DEFAULT '일반',
    sort_order INTEGER DEFAULT 0, is_active BOOLEAN NOT NULL DEFAULT TRUE, memo TEXT
);
ALTER TABLE stock_tx ADD COLUMN IF NOT EXISTS account_id INTEGER REFERENCES invest_accounts(id);
ALTER TABLE etf_tx   ADD COLUMN IF NOT EXISTS account_id INTEGER REFERENCES invest_accounts(id);
ALTER TABLE stock_tx ADD COLUMN IF NOT EXISTS is_opening BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE etf_tx   ADD COLUMN IF NOT EXISTS is_opening BOOLEAN NOT NULL DEFAULT FALSE;
```

### 설계 변경: "기초 보유"는 `tx_type='init'`이 아니라 **`매수 + is_opening 플래그`**
- 처음 계획은 `tx_type='init'`이었으나, `tx_type`을 보는 곳이 60군데가 넘어(수량·평단·실현손익·강제값 기준점 등) 하나라도 놓치면 기초 보유가 "매도"로 계산되는 큰 버그가 된다.
- 그래서 **기초 보유 = 매수 거래 + `is_opening=TRUE`** 로 저장한다. 수량/평단/실현손익 계산은 기존 코드가 그대로 처리하고, 아래 곳에서만 `is_opening`을 제외한다.
  1. 거래 입력/수정 시 현금 자동조정 (`_upsert_cash_adj` 건너뜀, 일반 매수→기초 보유로 바꾸면 이전 조정 되돌림)
  2. `recalc-foreign` 현금 재계산
  3. 월별 투자금 집계 (`/api/total-pnl` 순매수, 테크트리 `s_buy`, 자산추이 `s_buy`)
  4. (Step 5에서) 예수금 원장 기록
- 기초 보유는 **매수로만** 입력 가능(매도+기초 보유는 400). 단가 칸에는 **평균 매입단가**를 넣는다.

### 구현된 API
- `GET/POST /api/invest-accounts`, `PUT/DELETE /api/invest-accounts/<id>` — 거래가 연결된 계좌는 삭제 대신 `is_active=false`(사용 중지). `GET ?active=1` 로 사용 중만 조회.
- `/api/stock-tx`, `/api/etf-tx` 의 POST/PUT 이 `account_id`(선택), `is_opening` 을 받고, GET 이 `account_id`, `account_name`, `is_opening` 을 돌려준다. 계좌 미지정 거래도 허용(Step 5에서 필수로 전환).
- **데이터 초기화**: `GET /api/invest-reset`(지울 행 수 미리보기, 아무것도 안 바뀜) / `POST /api/invest-reset` `{"confirm":"초기화","delete_masters":false}`
  - 올해 `realized_pnl_archive`가 없으면 **409 거부**, `confirm`이 "초기화"가 아니면 400.
  - 지우는 것: `stock_tx`, `etf_tx`, 주식/ETF의 `cash_auto_adjustments`. 기본은 **종목 목록(stocks/etf)은 남기고** 수량/평단 흔적(`quantity`, `buy_price`, 강제값)만 0/NULL로 비운다. (`quantity`가 남아 있으면 `init_db`의 "기존 데이터→거래 이전" 마이그레이션이 재시작 때 매수 거래를 다시 만들어 버리기 때문)
  - `delete_masters:true` 면 종목 목록과 리밸런싱 배정까지 삭제.
  - 남기는 것: `realized_pnl_archive`, 코인/공모주, 부동산 납부 현금조정, 투자계획·분할매수 계획.
  - **되돌리지 않는 것**: 과거 매수/매도로 이미 변한 현금관리 통장 잔액. 초기화 후 직접 확인·수정.
- 스크립트 대신 API로 구현한 이유는 Step 1과 같다(앱 import 부작용).

### 구현된 화면 (`investments.html`)
- 상단 **[계좌 관리]** 버튼 → 모달에서 계좌 추가/수정/중지/삭제.
- 주식·ETF 거래내역 표에 **계좌**, **기초보유** 열 추가(입력·수정 가능).

### 계획에서 Step 3으로 옮긴 것
- "종목 목록·손익을 계좌별로 나눠 보기"(계좌 칩 선택, 계좌×종목 평단) 는 포지션 계산을 바꾸는 작업이라 **Step 3**에서 한다. Step 2는 계좌를 만들고 거래에 연결하는 데까지.

### 완료 확인 (로컬 PostgreSQL 16 + 실제 브라우저로 검증함)
- 기초 보유 입력 시 통장 잔액 불변, 일반 매수는 기존처럼 차감, 일반 매수→기초 보유 전환 시 잔액 복구
- 기초 보유 후 매도 시 실현손익이 기초 보유 평단 기준으로 계산됨
- 초기화: 아카이브 없으면 거부, 실행 후 아카이브 보존, 재시작(`init_db`) 후 유령 거래 재생성 없음

---

## Step 3. 계좌별 포지션 · 손익 계산 ✅ 구현됨

### 계산 방식
- 수량·평단·실현손익을 **종목 × 계좌** 단위 이동평균으로 계산한다. (`_walk_positions_by_account`)
  같은 종목을 A계좌 10주@100, B계좌 10주@200에 샀다면 각 계좌 평단은 100 / 200, **전체 평단은 수량 가중평균**(여기선 150)이다.
- 전체 실현손익 = 계좌별 실현손익의 합. 수기 강제값(qty/avg override)은 종목 전체 값이라 **계좌 미지정 거래 묶음에만** 적용한다. (계좌 없는 기존 종목은 예전 계산과 동일)
- 같은 기준으로 맞춘 곳: `recalc_realized_pnl`, `compute_realized_pnl_map`, `_position_with_overrides`, `_calc_realized_records`(레코드에 `account_id` 추가), 대시보드 월별 실현손익·실현손익 내역 2곳

### API
- `GET /api/stocks?account_id=`, `GET /api/etf?account_id=` : `''`=전체, `0`=계좌 미지정, 숫자=해당 계좌. 계좌 지정 시 그 계좌 거래만으로 계산하고 거래가 없는 종목은 뺀다. 수기 강제값은 적용하지 않는다.
- `GET /api/stock-tx?account_id=`, `GET /api/etf-tx?account_id=` : 계좌별 거래 목록 (실현손익도 계좌 기준)
- `GET /api/invest-accounts/summary?year=` : 계좌별 평가금액·매입금액·평가손익·수익률·실현손익(수수료 반영)·합계. 계좌 미지정 행, 공모주 실현손익(`ipo_realized`, 계좌에 속하지 않음) 별도 반환. `year`를 주면 그 해 매도분만.
- **매도 검증이 계좌 기준**: 계좌를 지정한 매도는 그 계좌의 보유 수량(그 거래일까지)까지만 가능. 다른 계좌 보유분은 팔 수 없다. (계좌 미지정 매도는 예전과 동일)

### 화면 (`investments.html`)
- 탭 위에 **계좌 칩**(전체 / 계좌들 / 계좌 미지정)과 접이식 **계좌별 손익** 표. 표의 줄을 눌러도 필터링된다.
- 칩을 선택하면 주식·ETF의 포지션 표, 거래내역, 상단 합계(평가총액·미실현·실현)가 그 계좌 기준으로 바뀐다. 같은 칩을 다시 누르면 전체.
- 계좌를 선택한 채 [거래 입력]을 누르면 계좌가 기본값으로 채워진다. 거래 입력 폼의 종목 선택지는 계좌 필터와 무관하게 전체 종목.

### 알아둘 점
- 상단 "투자 총손익" 카드와 대시보드 평가금액은 기존의 **단순 평균 매입단가**(총매수금액÷총매수수량) 방식이고, 계좌별 표는 **이동평균** 방식이라 **평가손익이 약간 다를 수 있다**. (예: 위 사례에서 150원 차이) 기존에도 종목 표와 상단 카드 사이에 있던 차이이며, Step 7에서 상단 카드를 계좌 합계 기준으로 바꾸면서 정리한다.

### 완료 확인 (로컬 PostgreSQL 16 + 브라우저로 검증함)
- 같은 종목 두 계좌(A 10주@100, B 10주@200): A필터 평단 100, B필터 200, 전체 평단 가중평균, 전체 실현손익 = A 실현 + B 실현
- A계좌에서 보유(5주)보다 많이 매도 → 400 거부 (B 보유분이 있어도)
- 요약 표의 계좌별 합 = 합계, `year` 필터 동작, 실현손익 원장 합계와 일치
- 기존 대시보드·테크트리·자산추이·구분별 손익 API 200 유지

---

## Step 4. 예수금 원장 + 현금관리 "예수금" 행(수정 불가) ✅ 구현됨

### DB (`database.py`)
```sql
ALTER TABLE cash_deposits ADD COLUMN IF NOT EXISTS is_system BOOLEAN NOT NULL DEFAULT FALSE;
CREATE SEQUENCE IF NOT EXISTS account_cash_ref_seq;          -- 환전/이체 등 원천 거래 묶음 번호
CREATE TABLE IF NOT EXISTS account_cash_tx (
    id SERIAL PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES invest_accounts(id),
    tx_date DATE NOT NULL, currency TEXT NOT NULL DEFAULT 'KRW',     -- KRW / USD
    kind TEXT NOT NULL,        -- init / deposit / withdraw / dividend / fee / exchange (Step 5~6: buy/sell/transfer_in/transfer_out)
    amount NUMERIC(18,4) NOT NULL,   -- 해당 통화 단위, 증가(+)/감소(-)
    ref_type TEXT, ref_id INTEGER, memo TEXT, created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (ref_type, ref_id, account_id, currency)
);
```
- `init_db`가 `cash_deposits`에 `name='예수금', is_system=TRUE` 행 1개를 보장한다.
- **잔액은 저장하지 않는다.** 예수금 = 원장 합계(통화별). 거래를 고치거나 지워도 어긋나지 않는다.

### 백엔드
- `get_account_cash_map(db)` : 계좌별 `{krw, usd}` 잔액.
- `_ensure_and_sync_deposit_row(db)` : 예수금 잠금 행을 `krw_amount`=원화 합계, `usd_amount`=달러 합계, `amount`=원화+달러×환율 로 맞춘다. **원장에 쓰는 모든 API가 같은 트랜잭션에서 호출 후 commit.** 현금관리 조회·백업 복구 후에도 호출(어긋남 자동 복구). 환율 갱신(`_refresh_usd_cash_amounts`)은 기존 로직이 같은 식으로 다시 계산한다.
- `GET /api/invest-accounts/<id>/cash` : 잔액 + 원장 내역(최근 500건, 삭제 가능 여부 포함)
- `POST /api/invest-accounts/<id>/cash` : `{kind: init|deposit|withdraw|dividend|fee, currency: KRW|USD, amount(양수), tx_date, memo}`
- `POST /api/invest-accounts/<id>/exchange` : `{from_currency, amount, rate(생략 시 현재 환율), tx_date, memo}` — 원화 줄·달러 줄 2개를 한 트랜잭션으로 기록 (원화→달러는 달러를 소수 2자리로 반올림)
- `DELETE /api/account-cash/<id>` : 수동 입력과 환전(양쪽 줄)만 삭제 가능. 거래·이체로 생긴 줄은 400.
- **잠금**: `PUT/DELETE /api/cash-deposits/<id>` 가 `is_system` 행이면 403.
- **예수금 행이 옛 현금 자동조정에 걸리지 않게**: `_upsert_cash_adj` / `_remove_cash_adj` / `apply` 의 "잔액 최대 통장" 선택에서 `is_system` 제외.
- `GET /api/invest-accounts`, `/api/invest-accounts/summary` 에 `cash_krw`, `cash_usd` 추가(요약 합계 포함). 원장이 있는 계좌는 삭제 대신 사용 중지.
- **백업/복구 대상에 새 테이블 추가**: `invest_accounts`, `account_cash_tx`, `realized_pnl_archive` (FK 순서 반영). Step 2에서 `stock_tx.account_id` 가 생긴 뒤 계좌 테이블이 백업에 없으면 복구가 FK 오류로 실패할 수 있었다.
- 변경하지 않은 것: `api_cash_deposits_detail` 의 "통장 수기 수정 시 `cash_auto_adjustments` 전체 삭제". 이는 "직접 고친 잔액이 기존 자동 조정을 흡수한다"는 기존 의도된 동작이라 유지한다. (계획 초안의 "stock/etf로 한정"은 철회)

### 화면
- **현금관리**: 예수금 행에 자물쇠·"계좌 합계 자동 연동" 배지, 클릭해도 편집 안 됨, 이미지 드롭도 무시. 아래에 투자 계좌별 예수금 구성 표(읽기 전용). (`GridTable` 에 `isLocked` 옵션 추가)
- **투자 관리**: 예수금 바(선택한 계좌, 전체면 합계의 원화/달러) + [입금][출금][환전][내역] 창, 계좌별 손익 표에 예수금 열. 입금/출금/환전은 계좌를 하나 골랐을 때만 활성화.
- 모달은 입력 유실 방지(Form Guard) 규칙에 맞춰 `_afterSaveSuccess` 로 닫는다.

### Step 4 보완 (사용성 피드백 반영)
- **계좌 줄에서 바로 관리**: 계좌별 손익 표의 예수금 칸에 원화·달러를 항상 함께 보여주고, 그 줄의 [잔액설정][입금][출금][환전][내역] 버튼으로 계좌 칩을 고르지 않아도 바로 입력한다. (예수금 바는 선택한 계좌/전체 합계용으로 유지)
- **잔액 직접 설정** `PUT /api/invest-accounts/<id>/cash-balance` `{krw?, usd?, tx_date?, memo?}`: 증권사 앱의 현재 예수금을 그대로 입력하면 현재 원장 합계와의 차이를 `잔액 조정`(kind=adjust) 한 줄로 기록한다. 보낸 통화만 처리, 차이가 없으면 기록 없음, 내역에서 삭제 가능. 처음 입력할 때와 증권사 잔액과 어긋났을 때 쓴다.

### 알아둘 점
- **아직 매수·매도는 예수금에 반영되지 않는다** (Step 5). 지금은 기존 방식(은행 통장 중 잔액 최대 통장 차감)이 그대로이며 예수금 행은 건드리지 않는다.
- 예수금은 마이너스가 될 수 있다(과거 거래를 순서 없이 입력 가능하도록 경고만): 음수는 빨간색으로 표시.
- 달러 예수금은 환율에 따라 원화 환산액과 순자산이 매일 변한다(기존 달러 통장과 동일).

### 완료 확인 (로컬 PostgreSQL 16 + 브라우저로 검증함)
- 원화·달러 입금/출금/수수료 후 예수금 행의 원화·달러·환산 합계가 정확, 환전 시 양쪽 줄 반영/삭제
- 예수금 행 수정·삭제 403, 잔액 불변. 입력 검증(0원/통화/날짜/없는 계좌) 400·404
- 일반 매수의 옛 현금 차감은 은행 통장에만 적용(예수금 행 불변)
- 백업 → 복구 왕복 후 계좌 잔액·예수금 행 동일, 예수금 행 1개 유지

---

## Step 5. 매수/매도 ↔ 예수금 연동 ✅ 구현됨

### 규칙
| 거래 | 예수금 원장 |
|---|---|
| 국내 종목 매수/매도 | 원화 예수금 `-(가격×수량+수수료)` / `+(가격×수량-수수료)` |
| 해외 종목 매수/매도 | **기본 달러 예수금** (달러 그대로) |
| 해외 종목을 원화로 결제 | 원화 예수금에서 `거래금액 × 거래 환율` 만큼 증감 (거래의 **결제** 칸에서 '원화' 선택) |
| 국내 종목을 달러로 결제 | 불가(400) |
| 기초 보유 | 기록 없음 |

- **계좌는 필수**: 주식·ETF 거래(기초 보유 포함) 저장 시 계좌를 지정하지 않으면 400 "계좌를 선택해 주세요". 분할매수 연결 거래(`/linked-tx`)도 동일.
- **결제 통화 저장**: `stock_tx/etf_tx.settle_currency` (기초 보유는 NULL). 거래를 수정할 때 그리드가 현재 값을 그대로 보내므로 원화 결제 거래가 달러로 바뀌지 않는다.
- **예수금 부족은 막지 않고 경고**: 저장은 되고 응답에 `warning` ("[잔액설정]으로 현재 예수금을 맞추거나 [이체]로 입금…"), 화면은 알림창으로 보여준다. 통화별로 판단.
- **원장은 `ref`로 교체**: 거래 수정 시 그 거래의 원장 줄을 지우고 다시 기록하므로 수량·가격·계좌·결제통화가 바뀌어도 어긋나지 않는다. 삭제하면 원장 줄도 지운다. 종목(주식/ETF) 삭제, 분할매수 연결 거래 삭제, 투자 데이터 초기화(거래 연동분만, 입금/출금/환전/이체/잔액 조정은 유지)도 같은 방식으로 정리하고 현금관리 '예수금' 행을 동기화한다.

### 기존 방식 제거
- 주식·ETF에 대한 `_upsert_cash_adj`(은행 통장 중 잔액 최대 통장 차감) 호출을 모두 제거. 이제 `_upsert_cash_adj`는 **부동산 납입**(`re_payment`)에서만 쓴다.
- **옛 방식으로 기록돼 있던 거래**(통장이 이미 차감된 거래)를 수정/삭제하면 `_remove_cash_adj`로 그 통장 차감을 먼저 되돌린다. 수정할 때는 계좌를 지정해야 하므로, 옛 거래를 새 방식(계좌 예수금)으로 옮기는 효과가 있다.
- `recalc-foreign`(달러→원화 재계산) 폐지: 엔드포인트는 아무것도 하지 않고, 현금관리의 버튼·함수를 제거. 현금관리 안내 문구도 갱신.

### 화면
- 주식·ETF 거래내역에 **결제** 열(원화/달러, 비워 두면 국내=원화·해외=달러), 저장 후 예수금 부족 알림, 계좌별 표·예수금 바 갱신. 입력 도움말 문구 갱신.

### 알아둘 점
- **이미 입력된 과거 거래는 예수금에 소급 반영되지 않는다.** 새 방식으로 쓰려면 거래를 계좌에 연결하며 수정하거나, 데이터 초기화 후 계좌별 기초 보유·예수금을 새로 입력한다.
- 해외 종목 가격·수수료는 달러 기준이라 달러 예수금에서 그대로 차감되고(소수 2자리 반올림), 원화 결제일 때만 거래 시점 환율로 환산한다.

### 완료 확인 (로컬 PostgreSQL 16 + 브라우저로 검증함)
- 국내 매수/매도, 해외 달러 결제, 해외 원화 결제, 국내 종목 달러 결제 거부, 계좌 미지정 거부(주식·ETF·분할매수 연결 거래), 기초 보유 예수금 불변
- 수정: 수량 변경 시 원장 1줄 교체, 계좌 이동(A→B), 일반→기초 전환 시 원장 제거, 원화 결제 유지. 삭제·종목 삭제 시 예수금 복구. 예수금 행 = 원장 합계
- 옛 방식(통장 차감) 거래: 계좌 없이 수정 400, 계좌 지정 수정 시 통장 복구 + 계좌 예수금 기록
- 예수금 부족 경고(201), 초기화 후 수동 입력 잔액만 남고 예수금 행 동기화, `recalc-foreign` 무동작
- 브라우저: 계좌 선택 후 매수 → 예수금 감소, 매도 → 증가, 삭제 → 복구, 계좌 없이 저장 시 안내

### Step 5 보완: 빠른 매매 (사용성 피드백 반영)
- 주식·ETF **포지션 표의 종목 줄에 [매수][매도] 버튼**(매매 열)을 추가. 누르면 작은 창이 열린다. (행 클릭은 기존처럼 보유수량·평단 강제 수정이라, 겹치지 않게 별도 버튼으로 구현)
  - 계좌: 계좌 칩으로 선택한 계좌가 기본값, 전체 보기에서는 직접 선택(미선택 시 저장 불가)
  - 날짜: **기본 오늘**(나중에 거래내역에서 수정), 단가: 현재가가 기본값, 수수료 0, 해외 종목은 결제 통화(달러/원화) 선택
  - 입력 중 **거래금액과 예수금 변화 미리보기**(`10,000,000원 → 9,790,000원`, 마이너스가 되면 빨간색), 선택 계좌 기준 보유 수량 안내
  - 저장은 기존 `/api/stock-tx`·`/api/etf-tx`를 그대로 사용하므로 계좌 필수·보유 수량 초과 매도 거부·예수금 부족 경고 규칙이 동일하게 적용된다. Enter 키로도 저장.
- **오늘 날짜 버그 수정**: `new Date().toISOString()`(UTC 기준)은 한국 시간 0~9시에 어제 날짜를 돌려줬다. `todayLocalStr()`(`common.js`)로 바꿔 거래 그리드·이체·예수금 창·수입·가계부 입력의 기본 날짜를 현지 시간 기준으로 맞췄다. (`quick_entry.html`은 `common.js`가 없는 단독 페이지라 같은 계산을 인라인으로)

---

## Step 6. 계좌 간 이체 ✅ 구현됨

### DB
```sql
CREATE TABLE IF NOT EXISTS account_transfers (
    id SERIAL PRIMARY KEY, tx_date DATE NOT NULL,
    from_type TEXT NOT NULL, from_id INTEGER NOT NULL, from_name TEXT,   -- 'bank'(현금관리 통장) / 'invest'(투자 계좌)
    to_type   TEXT NOT NULL, to_id   INTEGER NOT NULL, to_name   TEXT,
    currency TEXT NOT NULL DEFAULT 'KRW',                               -- KRW / USD (이체는 같은 통화끼리)
    amount NUMERIC(18,4) NOT NULL CHECK (amount > 0), memo TEXT, created_at TIMESTAMP DEFAULT NOW()
);
```
- `from_name`/`to_name`은 이체 시점 이름을 저장해, 통장·계좌가 나중에 지워져도 내역에 이름이 남는다.

### 동작
- **통장 → 투자 계좌**: 통장의 원화/달러 잔액 감소 + 계좌 예수금 증가. **투자 계좌 → 통장**은 반대. **투자 계좌 → 투자 계좌**: 한쪽 감소, 다른 쪽 증가(예수금 행 합계는 불변). 통장끼리의 이체와 '예수금' 잠금 행은 불가.
- 투자 계좌 쪽은 예수금 원장(`account_cash_tx`, `ref_type='transfer'`, `kind=transfer_in/out`)에, 통장 쪽은 `cash_deposits.krw_amount/usd_amount/amount`에 반영한다. **한 트랜잭션**이라 도중에 실패하면 어느 쪽도 바뀌지 않는다.
- **통장 잔액이 모자라면 거부**(400), **투자 계좌 예수금이 모자라면 이체는 하되 경고**(Step 5의 "과거 입력 순서" 규칙과 동일).
- **삭제 = 양쪽 원복**. 이미 지운 통장은 건너뛰고, 되돌리는 쪽 잔액이 음수가 돼도 허용한다. 예수금 내역(원장)에서 이체 줄을 지워도 같은 삭제가 실행된다. 이체 수정은 "삭제 후 다시 입력".
- API: `GET/POST /api/account-transfers`, `DELETE /api/account-transfers/<id>`. 백업/복구 대상에 `account_transfers` 추가.

### 화면
- 공용 이체 창 `static/js/transfer.js` (출금/입금 선택지에 선택한 통화 기준 잔액 표시, 출금/입금 바꾸기, 미리보기). 단, 처음 열 때 투자 계좌가 없으면 안내만 한다.
- **현금관리**: 상단 [증권 계좌로 이체] 버튼, 아래 **이체 내역** 표(삭제 버튼). 자동 조정 안내 문구에 "증권 계좌로 옮긴 돈은 이체를 쓰세요" 추가.
- **투자 관리**: 계좌 줄의 [이체] 버튼(그 계좌가 입금 기본값), 예수금 바의 [이체] 버튼.

### 알아둘 점
- 이체는 **환율 환산을 하지 않는다**. 원화 통장 → 원화 예수금, 달러 통장 → 달러 예수금. 통화를 바꾸려면 투자 계좌 안에서 [환전]을 쓴다.
- 이체로 총 현금 합계(통장 + 예수금)는 변하지 않는다.

### 완료 확인 (로컬 PostgreSQL 16 + 브라우저로 검증함)
- 통장→계좌/계좌→통장/계좌→계좌/달러 이체 후 양쪽 잔액·예수금 행·환산액이 정확
- 통장 잔액 부족 시 400 + 전체 롤백(이체 기록·잔액 변화 없음), 투자 계좌 예수금 부족은 201 + 경고
- 입력 검증(같은 대상/통장끼리/예수금 행/없는 대상/0원/통화/날짜) 400, 이체 삭제 원복(원장 내역 경로 포함), 통장이 없어진 뒤 삭제, 백업→복구 왕복
- 브라우저: 현금관리에서 이체→통장 표·예수금 구성·이체 내역 갱신→삭제 원복, 투자 관리 계좌 줄 [이체](달러 포함) 동작

---

## Step 7. 상단 대시보드: 연 기준 총손익 / 실현손익 / 평가손익 ✅ 구현됨

### 정의 (확정)
- **실현손익(연)** = 그 해 매도 실현손익 (주식·ETF·공모주·**코인**) + 초기화 전에 박제한 주식·ETF 분(초기화 후에만)
- **평가손익** = 현재 보유분의 (현재가 − 이동평균 매입단가) × 수량, **계좌 합계 기준**(계좌별 손익 표와 같은 계산). 해외 종목은 현재 환율로 원화 환산. 올해는 실시간, 과거 연도는 `account_year_snapshots` 에 기록한 그 해 말 값(없으면 "기록 없음").
- **총손익(연)** = 실현손익(연) + 평가손익. 연초 기준값 입력은 필요 없다.

### 박제(`realized_pnl_archive`) 합산 규칙 — 이중 계상 방지
- 초기화 **전**에는 박제된 거래가 아직 live 거래로 계산되므로 박제분을 **합산하지 않는다**.
- `POST /api/invest-reset` 이 성공하면 `app_settings.invest_reset_at` 을 기록하고, 그 뒤부터 박제분 중 **주식·ETF**만 합산한다. 공모주·코인은 초기화 후에도 live 데이터가 남으므로 박제분을 쓰지 않는다.
- 초기화 후 새 거래의 실현손익은 박제분에 가산된다.

### 백엔드
- `GET /api/total-pnl?year=YYYY`(기본 올해): `year`, `years`(선택 가능한 연도), `realized_pnl`, `realized_breakdown`(주식/ETF/공모주/코인/이전 기록), `unrealized_pnl`(None 가능), `unrealized_source`(`live`/`snapshot`/`none`), `total_pnl`, `eval_amount`·`cost_basis`·`unrealized_rate`(올해만), `monthly`. 기존 키는 유지.
- 월간 그래프(`monthly`)는 기존 방식(월말 평가금액 − 누적 순매수)을 그대로 쓰고 **선택 연도의 달만** 돌려준다. 누적선은 그 해 시작 대비. 카드와 정의가 달라 합이 정확히 일치하지는 않는다.
- `GET /api/invest-accounts/summary?year=` : 박제분은 `archive_realized`, 코인은 `crypto_realized` 로 별도 반환(계좌에 속하지 않으므로 표 합계 밖). 카드 실현손익 = 표 합계 + 공모주 + 코인 + 이전 기록.
- 포지션 계산을 `_compute_account_positions()` 로 분리해 요약과 카드가 같은 값을 쓴다. 신규 테이블 `account_year_snapshots`(연말 평가손익 기록, Step 8에서 입력·자동 저장).

### 화면
- 상단 카드에 **◀ 2026년 ▶** 연도 선택. 실현손익 아래에 구성(주식·ETF·공모주·코인·이전 기록), 평가손익 라벨은 `보유 중, 현재가 기준` / `2025년 말 기록` / `기록 없음`(이 경우 총손익은 실현손익만 반영한다는 안내).
- 계좌별 손익 표의 실현손익 열 제목이 `실현손익(2026년)` 으로 바뀌고 연도 선택에 따라 갱신된다. 안내 문구에 계좌에 속하지 않는 실현손익을 표시.

### 알아둘 점
- 과거 연도의 평가손익은 연말 기록이 있어야 보인다. **기록 입력 화면은 Step 8**에서 만든다(그때까지 과거 연도는 실현손익만 반영).
- 계좌별 표의 평가금액·평가손익 열은 항상 현재 보유분 기준이다(연도 선택과 무관).

### 완료 확인 (로컬 PostgreSQL 16 + 브라우저로 검증함)
- 올해/전년 실현손익 구성(주식·ETF·공모주·코인), 평가손익(live) = 계좌 합 = 카드, 전년 연말 기록 있음/없음, 연도 목록, 월간 그래프의 연도 필터
- 박제: 초기화 전 합산 안 함, 초기화 후 주식·ETF만 합산(공모주·코인 중복 없음), 새 거래 실현손익 가산, 카드 실현 = 계좌 합 + 공모주 + 코인 + 박제
- 브라우저: ◀ ▶ 이동, 연도 경계 버튼 비활성, 표 머리글·안내 갱신, 월간 그래프가 연도 이동 후에도 유지, 콘솔 오류 없음

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
