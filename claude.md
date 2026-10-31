# 💰 Money Tracker - Claude AI 가이드 (`claude.md`)

이 문서는 AI 어시스턴트(Claude 등)가 이 프로젝트의 구조, 설계 의도, 데이터베이스 스키마 및 핵심 기능들을 빠르게 파악하고 일관된 코드 수정 및 개발을 진행할 수 있도록 돕는 개발 가이드입니다.

---

## 📌 1. 프로젝트 개요
* **프로젝트명**: Money Tracker (가계부 및 개인 자산 통합 관리 시스템)
* **목적**: 개인의 수입/지출/카드 내역 관리부터 주식, ETF, 암호화폐, 부동산, 대출, 연금, 목표 금액 등 **모든 자산 유형의 현황을 종합적으로 모니터링하고 시뮬레이션**하는 웹 애플리케이션입니다.

---

## 🛠️ 2. 기술 스택
* **Backend**: Python (Flask)
* **Database**: PostgreSQL (연동 설정: `psycopg2-binary`, Connection Pool 사용)
* **Frontend**: HTML5, Vanilla JavaScript, Vanilla CSS (별도 프레임워크 없음)
* **주요 라이브러리**:
  * `yfinance`, `pykrx`: 국내외 주식/ETF 실시간 가격 정보 갱신
  * `openpyxl`, `xlrd`: 신용카드 명세서 엑셀 파싱 및 카테고리 매핑
  * `Flask-Caching`: 성능 최적화를 위한 단순 캐싱
  * `APScheduler`: 매일 자산 스냅샷 생성 및 Render 슬립 방지용 Ping 스케줄러

---

## 📂 3. 디렉토리 구조 및 핵심 파일
```bash
d:\python work\Money\
├── app.py                     # Flask 메인 애플리케이션 (라우팅, API 비즈니스 로직, 스케줄러)
├── database.py                # PostgreSQL 커넥션 풀 관리, 스키마 정의 및 초기 마이그레이션
├── requirements.txt           # 프로젝트 의존 라이브러리 목록
├── version.json               # 애플리케이션 버전 및 최근 업데이트 일자 정보
├── insert_realistic_data.py   # 시뮬레이션 및 로컬 테스트용 현실적인 샘플 데이터 삽입 스크립트
├── update_2026.py             # 특정 연도(2026년) 기준 자산 데이터 업데이트 시뮬레이션 스크립트
├── 작업계획서/                 # 기능별 작업 계획서 (투자 관리 대개편은 plan_04_investment_accounts_overhaul.md)
├── templates/                 # 각 화면의 HTML 템플릿 파일 폴더
│   ├── login.html
│   ├── dashboard.html
│   ├── income.html
│   ├── budget.html
│   ├── cards.html
│   ├── investments.html
│   └── ... (기타 페이지)
└── static/                    # 공통 CSS, JS 및 이미지 에셋 폴더
    └── js/ (common.js: GridTable·fetchJSON·todayLocalStr·Form Guard, transfer.js: 계좌 간 이체 창 등)
```

---

## 🗄️ 4. 데이터베이스 테이블 스키마 요약
데이터베이스 초기화 및 테이블 생성은 `database.py`의 `init_db()`에서 수행됩니다.

* **수입/지출 관련**:
  * `income`: 수입 내역 (날짜, 카테고리, 금액, 원화 외 USD 설정 가능)
  * `budget`: 지출 내역 (일반 지출 및 `recurring_budget`에서 자동 생성된 지출 통합 관리)
  * `recurring_budget`: 고정 지출 템플릿 (매월 특정 일자에 자동 지출 항목을 budget 테이블에 자동 인서트)
* **신용카드 관련**:
  * `card_info`: 보유 카드 마스터 정보 (한도, 결제일, 결제 기준일 등)
  * `card_tx`: 카드 결제 승인 내역 (가계부 budget 테이블의 지출과 연동)
  * `card_category_rules`: 가맹점명 키워드별 카테고리 자동 분류 규칙
* **투자 관련**:
  * `stocks` / `stock_tx`: 국내외 주식 마스터 및 매수/매도 거래 내역. 거래에는 `account_id`(투자 계좌), `is_opening`(기초 보유), `settle_currency`(결제 통화 KRW/USD)가 있다.
  * `etf` / `etf_tx`: ETF 마스터 및 거래 내역 (DCA, Drawdown 등 매수 전략 필드 포함). 거래 컬럼은 `stock_tx`와 동일.
  * `invest_accounts`: 투자(증권) 계좌 마스터 (이름·증권사·종류·사용 여부). 거래·예수금이 연결된 계좌는 삭제 대신 사용 중지.
  * `account_cash_tx`: **계좌별 예수금 원장**. 잔액을 저장하지 않고 이 원장의 통화별(KRW/USD) 합계가 예수금이다. `kind`=init/deposit/withdraw/dividend/fee/exchange/transfer_in/transfer_out/buy/sell/adjust, `ref_type`/`ref_id`로 원천 거래(stock_tx·etf_tx·transfer·exchange)와 연결.
  * `account_transfers`: 현금관리 통장 ↔ 투자 계좌, 투자 계좌 ↔ 투자 계좌 이체 내역 (이체 시점 이름 스냅샷 포함).
  * `account_year_snapshots`: 연말(또는 직접 입력한) 계좌별 평가금액·평가손익·실현손익·예수금 기록. 연도별 기록 탭과 과거 연도 총손익의 원천.
  * `realized_pnl_archive`: 투자 데이터 초기화 전에 박제한 연도별 실현손익.
  * `crypto` / `crypto_sell`: 암호화폐 보유 현황 및 매도 기록
  * `split_buy_plans` / `split_buy_plan_steps` / `split_buy_transactions`: 분할 매수 계획 및 실행 내역
  * `invest_plans` / `invest_plan_steps`: 피라미딩/역피라미딩 등 고급 투자 계획 및 트리거 단계 기록
* **부동산/대출/연금 관련**:
  * `real_estate`: 부동산 자산 (취득가, 현재가, 처분 예정 등)
  * `real_estate_payments`: 부동산 중도금/잔금 등 일정별 납부 계획 관리
  * `tenant_contracts`: 보유 부동산의 임대차 계약 정보 (보증금, 월세 수입)
  * `property_costs`: 부동산 유지 관리비 지출 내역
  * `loans`: 대출 현황 (원금, 잔액, 이자율, 월 상환액)
  * `pension`: 연금 자산 (국민연금, 퇴직연금, 개인연금 등 누적액 및 수익률)
* **기타 및 시뮬레이션**:
  * `goals`: 목돈 만들기 등의 자산 목표 및 달성률
  * `cash_deposits`: 예적금 및 일반 현금 자산 정보. `is_system=TRUE`인 **"예수금" 행**은 모든 투자 계좌 예수금의 합계(원화·달러)로 자동 갱신되며 직접 수정/삭제할 수 없다. 그래서 `SUM(cash_deposits.amount)`을 쓰는 대시보드·테크트리·생애주기 등은 수정 없이 예수금을 한 번만 포함한다.
  * `daily_snapshots`: 일별 자산군별 스냅샷 및 순자산 기록 (대시보드 트렌드 그래프에 활용)
  * `lifecycle_profile` / `lifecycle_events` / `lifecycle_settings`: 생애 주기 재무 시뮬레이션 설정 및 이벤트

---

## ⚙️ 5. 핵심 시스템 메커니즘
1. **구글 로그인 인증 및 이메일 화이트리스트 (`app.py`)**:
   * Google OAuth 인증 정보를 이용해 프론트엔드에서 전달받은 `credential` 토큰을 구글 서버 API로 직접 검증합니다.
   * `ALLOWED_EMAILS` 화이트리스트 변수에 등록된 이메일 계정(`bbonoyo@gmail.com`, `mybpilatesmyb@gmail.com`)만 접근을 승인합니다.
2. **자동 버전 관리 (`app.py`)**:
   * 앱이 재시작(구동)될 때마다 `version.json` 파일의 version 값을 `0.01`씩 자동으로 증가시키고 오늘 날짜를 `updated`에 기록합니다.
3. **고정지출 자동 생성 (`app.py` & `budget.html` 호출 연동)**:
   * 사용자가 특정 연월의 가계부를 조회할 때, `_generate_recurring_budget()` 함수가 호출되어 활성화된 `recurring_budget` 템플릿을 기반으로 오늘 날짜 이전까지의 미생성 항목을 자동 생성하여 `budget`에 삽입합니다.
4. **캐시 비우기 데코레이터**:
   * Caching을 적용하고 있으며, `POST`, `PUT`, `DELETE` 요청이 성공하면 모든 API 요약 캐시를 자동으로 무효화(`_clear_summary_cache`)합니다.
5. **스케줄러 동작**:
   * `BackgroundScheduler`를 활용하여 매일 23시 59분 30초에 자산별 현황 스냅샷을 저장하고, Render 웹서버 무료 티어의 절전 모드 방지를 위해 10분마다 ping을 보냅니다.
   * 매년 12월 31일 23시 58분에 `_scheduled_year_end_snapshot()`이 계좌별 연말 기록(`account_year_snapshots`)을 저장합니다. 직접 입력한 기록이 있는 해는 덮어쓰지 않습니다.
6. **투자 관리 구조 (계좌 · 예수금 · 이체 · 연 단위 손익)** — 자세한 설계와 검증 내용은 `작업계획서/plan_04_investment_accounts_overhaul.md`:
   * **종목 × 계좌 단위 이동평균**으로 수량·평단·실현손익을 계산한다(`_walk_positions_by_account`). 전체 평단은 수량 가중평균, 전체 실현손익은 계좌별 합. 수기 강제값(qty/avg override)은 "계좌 미지정" 거래에만 적용된다.
   * **기초 보유**는 새 거래 유형이 아니라 `tx_type='buy' + is_opening=TRUE`로 저장한다(수량·평단·실현손익 계산은 그대로, 예수금·월별 투자금 집계에서만 제외).
   * **매수·매도는 계좌 예수금 원장에 기록**된다(`_record_trade_cash`): 국내=원화, 해외=달러(원화 결제 선택 시 거래 환율로 환산). 계좌 지정은 필수, 예수금 부족은 막지 않고 경고(`warning`)만 한다. 거래 수정은 원장 줄을 지우고 다시 쓴다(`ref_type`/`ref_id`). 옛 방식(은행 통장 차감, `cash_auto_adjustments`)은 부동산 납입(`re_payment`)에서만 남아 있다.
   * **원장에 쓰는 모든 코드는 같은 트랜잭션에서 `_ensure_and_sync_deposit_row(db)`를 호출**해 현금관리 "예수금" 행을 맞춘다(커밋 포함).
   * **총손익(연)** = 그 해 실현손익(주식·ETF·공모주·코인 + 초기화 후 박제분) + 평가손익(현재 보유분의 (현재가−평단)×수량, 계좌 합계). 지난 해에 `account_year_snapshots` 기록이 있으면 실현·평가손익 모두 그 기록을 쓴다. 박제분은 `invest_reset_at`(초기화 실행 표시)이 있을 때만 합산한다(이중 계상 방지).
   * 데이터 초기화는 `GET/POST /api/invest-reset` (올해 박제가 없으면 거부, `confirm:"초기화"` 필요, 거래 연동 예수금만 지우고 입금·출금·환전·이체·잔액 조정은 유지). 실행 전 앱의 백업 파일을 받아 둔다.
   * 백업/복구(`/api/backup`, `/api/restore`)는 `invest_accounts`, `account_cash_tx`, `account_transfers`, `account_year_snapshots`, `realized_pnl_archive`를 FK 순서(`_BACKUP_DELETE_ORDER`/`_BACKUP_INSERT_ORDER`)에 맞춰 포함한다. 새 테이블을 만들면 두 목록에 반드시 추가한다.
7. **프런트엔드 규칙**:
   * 화면의 "오늘" 기본값은 `todayLocalStr()`(`common.js`)를 쓴다. `new Date().toISOString()`은 UTC 기준이라 한국 시간 0~9시에 어제 날짜가 나온다.
   * 모달은 입력 유실 방지(Form Guard)가 걸려 있어 저장 후에는 `_afterSaveSuccess(modalId, callback)`로 닫고, 미리 채운 입력칸에는 `data-no-dirty`를 붙인다.
   * Flask 템플릿은 서버 시작 시 캐시되므로 템플릿을 고친 뒤 로컬 서버를 다시 띄워야 반영된다.

---

## 🚀 6. 개발 및 실행 방법
1. **의존 라이브러리 설치**:
   ```bash
   pip install -r requirements.txt
   ```
2. **환경 변수 구성**:
   * 루트 폴더에 `.env` 파일을 작성하고 PostgreSQL 접속 정보 및 필요한 구글 로그인 키를 추가합니다.
   ```env
   DATABASE_URL=postgresql://사용자:비밀번호@호스트:포트/데이터베이스
   FLASK_SECRET_KEY=임의의_시크릿_키
   GOOGLE_CLIENT_ID=구글_클라이언트_ID
   ```
3. **샘플 데이터 세팅 (테스트 시)**:
   ```bash
   python insert_realistic_data.py
   ```
4. **애플리케이션 구동**:
   ```bash
   python app.py
   ```
   * 기본 주소: `http://127.0.0.1:5000`
