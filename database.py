import os
import psycopg2
from psycopg2.extras import DictCursor
from psycopg2.pool import ThreadedConnectionPool
import psycopg2.extensions

def load_dotenv():
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    if '=' in line:
                        key, val = line.split('=', 1)
                        val = val.strip()
                        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                            val = val[1:-1]
                        os.environ[key.strip()] = val

# 로컬 .env 파일 자동 로드
load_dotenv()

_pool = None
_db_url = None

def _make_conn(db_url):
    """TCP keepalive + connect_timeout 옵션을 포함한 커넥션 생성"""
    conn = psycopg2.connect(
        db_url,
        cursor_factory=DictCursor,
        connect_timeout=10,
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=5,
    )
    conn.autocommit = False
    return conn

def _get_healthy_conn(pool, db_url):
    """풀에서 커넥션을 꺼내되 끊긴 경우 재연결"""
    conn = pool.getconn()
    try:
        conn.cursor().execute("SELECT 1")
    except Exception:
        try:
            pool.putconn(conn, close=True)
        except Exception:
            pass
        conn = _make_conn(db_url)
    return conn

def init_pool():
    global _pool, _db_url
    if _pool is None:
        db_url = os.environ.get('DATABASE_URL')
        if not db_url:
            raise ValueError("DATABASE_URL environment variable is not set")
        _db_url = db_url
        # 최소 1개, 최대 10개 (Render 무료 플랜 커넥션 한도 고려)
        _pool = ThreadedConnectionPool(1, 10, db_url, cursor_factory=DictCursor)

class PooledConnectionWrapper:
    def __init__(self, conn, is_request_scoped=False):
        self._conn = conn
        self._is_request_scoped = is_request_scoped

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if hasattr(self._conn, '__exit__'):
            return self._conn.__exit__(exc_type, exc_val, exc_tb)
        return False

    def close(self):
        # request-scoped 커넥션은 요청이 끝날 때 teardown 훅에서 반환하므로 early close하지 않습니다.
        if self._is_request_scoped:
            return
        global _pool
        if _pool:
            _pool.putconn(self._conn)
        else:
            self._conn.close()

def get_db():
    global _pool
    if _pool is None:
        init_pool()
    
    try:
        from flask import g, has_app_context
    except ImportError:
        g = None
        has_app_context = lambda: False

    if has_app_context():
        if not hasattr(g, 'db_conn'):
            g.db_conn = _get_healthy_conn(_pool, _db_url)
        return PooledConnectionWrapper(g.db_conn, is_request_scoped=True)
    else:
        conn = _get_healthy_conn(_pool, _db_url)
        return PooledConnectionWrapper(conn, is_request_scoped=False)


def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS income (
            id              SERIAL PRIMARY KEY,
            date            TEXT NOT NULL,
            category        TEXT,
            name            TEXT,
            memo            TEXT,
            amount          INTEGER NOT NULL DEFAULT 0,
            currency        TEXT NOT NULL DEFAULT 'KRW',
            exchange_rate   REAL NOT NULL DEFAULT 1.0,
            original_amount REAL NOT NULL DEFAULT 0.0
        );

        CREATE TABLE IF NOT EXISTS budget_recurring (
            id              SERIAL PRIMARY KEY,
            name            TEXT NOT NULL,
            category        TEXT,
            type            TEXT,
            payment_method  TEXT,
            card_id         INTEGER,
            amount          INTEGER NOT NULL DEFAULT 0,
            memo            TEXT,
            active          BOOLEAN DEFAULT TRUE
        );

        CREATE TABLE IF NOT EXISTS budget (
            id              SERIAL PRIMARY KEY,
            date            TEXT NOT NULL,
            category        TEXT,
            name            TEXT,
            type            TEXT,
            payment_method  TEXT,
            amount          INTEGER NOT NULL DEFAULT 0,
            memo            TEXT
        );

        CREATE TABLE IF NOT EXISTS card_info (
            id              SERIAL PRIMARY KEY,
            card_num        INTEGER NOT NULL,
            card_name       TEXT,
            limit_amount    INTEGER DEFAULT 0,
            payment_day     INTEGER,
            billing_day     INTEGER,
            benefit         TEXT
        );

        CREATE TABLE IF NOT EXISTS card_tx (
            id              SERIAL PRIMARY KEY,
            card_id         INTEGER REFERENCES card_info(id),
            date            TEXT NOT NULL,
            name            TEXT,
            category        TEXT,
            amount          INTEGER NOT NULL DEFAULT 0,
            installment     INTEGER DEFAULT 1,
            memo            TEXT
        );

        CREATE TABLE IF NOT EXISTS stocks (
            id              SERIAL PRIMARY KEY,
            name            TEXT,
            ticker          TEXT,
            buy_date        TEXT,
            buy_price       REAL DEFAULT 0,
            quantity        REAL DEFAULT 0,
            current_price   REAL DEFAULT 0,
            dividend        INTEGER DEFAULT 0,
            memo            TEXT
        );

        CREATE TABLE IF NOT EXISTS stock_tx (
            id          SERIAL PRIMARY KEY,
            stock_id    INTEGER NOT NULL REFERENCES stocks(id),
            tx_date     TEXT    NOT NULL,
            tx_type     TEXT    NOT NULL,
            price       REAL NOT NULL DEFAULT 0,
            quantity    REAL    NOT NULL DEFAULT 0,
            fee         REAL DEFAULT 0,
            memo        TEXT
        );

        CREATE TABLE IF NOT EXISTS etf (
            id              SERIAL PRIMARY KEY,
            name            TEXT,
            ticker          TEXT,
            buy_date        TEXT,
            buy_price       REAL DEFAULT 0,
            quantity        REAL DEFAULT 0,
            current_price   REAL DEFAULT 0,
            etf_type        TEXT,
            category        TEXT,
            memo            TEXT,
            invest_strategy VARCHAR(20) DEFAULT 'dca',
            total_budget    BIGINT DEFAULT 0,
            invest_periods  INTEGER DEFAULT 12,
            drawdown_step   NUMERIC(4,1) DEFAULT 5.0
        );

        CREATE TABLE IF NOT EXISTS crypto (
            id              SERIAL PRIMARY KEY,
            name            TEXT,
            symbol          TEXT,
            exchange        TEXT,
            buy_date        TEXT,
            buy_price       REAL DEFAULT 0,
            quantity        REAL DEFAULT 0,
            current_price   REAL DEFAULT 0,
            memo            TEXT
        );

        CREATE TABLE IF NOT EXISTS residence (
            id              SERIAL PRIMARY KEY,
            address         TEXT,
            deposit         INTEGER DEFAULT 0,
            monthly_rent    INTEGER DEFAULT 0,
            maintenance     INTEGER DEFAULT 0,
            start_date      TEXT,
            end_date        TEXT
        );

        CREATE TABLE IF NOT EXISTS real_estate (
            id              SERIAL PRIMARY KEY,
            name            TEXT,
            re_type         TEXT,
            purchase_date   TEXT,
            purchase_price  INTEGER DEFAULT 0,
            current_price   INTEGER DEFAULT 0,
            memo            TEXT,
            sell_date       TEXT,
            sell_tax        INTEGER DEFAULT 0,
            sell_other_costs INTEGER DEFAULT 0,
            sell_memo       TEXT
        );

        CREATE TABLE IF NOT EXISTS loans (
            id              SERIAL PRIMARY KEY,
            name            TEXT,
            institution     TEXT,
            principal       INTEGER DEFAULT 0,
            remaining       INTEGER DEFAULT 0,
            monthly_payment INTEGER DEFAULT 0,
            interest_rate   REAL DEFAULT 0,
            loan_date       TEXT,
            end_date        TEXT,
            memo            TEXT
        );

        CREATE TABLE IF NOT EXISTS pension (
            id              SERIAL PRIMARY KEY,
            pension_type    TEXT,
            name            TEXT,
            institution     TEXT,
            monthly_payment INTEGER DEFAULT 0,
            accumulated     INTEGER DEFAULT 0,
            return_rate     REAL DEFAULT 0,
            memo            TEXT
        );

        CREATE TABLE IF NOT EXISTS goals (
            id              SERIAL PRIMARY KEY,
            name            TEXT,
            target_amount   INTEGER DEFAULT 0,
            current_amount  INTEGER DEFAULT 0,
            monthly_saving  INTEGER DEFAULT 0,
            target_date     TEXT,
            memo            TEXT
        );

        CREATE TABLE IF NOT EXISTS cash_deposits (
            id              SERIAL PRIMARY KEY,
            name            TEXT,
            amount          INTEGER DEFAULT 0,
            memo            TEXT,
            updated_date    TEXT
        );

        CREATE TABLE IF NOT EXISTS cash_auto_adjustments (
            id          SERIAL PRIMARY KEY,
            adj_date    DATE NOT NULL,
            source_type TEXT NOT NULL,
            source_id   INTEGER NOT NULL,
            amount      BIGINT NOT NULL,
            description TEXT,
            applied     BOOLEAN DEFAULT FALSE,
            created_at  TIMESTAMP DEFAULT NOW(),
            UNIQUE(source_type, source_id)
        );

        CREATE TABLE IF NOT EXISTS card_mappings (
            id       SERIAL PRIMARY KEY,
            card_id  INTEGER UNIQUE REFERENCES card_info(id),
            mapping  TEXT
        );

        CREATE TABLE IF NOT EXISTS card_category_rules (
            id       SERIAL PRIMARY KEY,
            keyword  TEXT NOT NULL,
            category TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS categories (
            id         SERIAL PRIMARY KEY,
            name       TEXT NOT NULL UNIQUE,
            sort_order INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS tenant_contracts (
            id              SERIAL PRIMARY KEY,
            real_estate_id  INTEGER NOT NULL REFERENCES real_estate(id),
            contract_type   TEXT NOT NULL,
            deposit         INTEGER NOT NULL DEFAULT 0,
            monthly_rent    INTEGER NOT NULL DEFAULT 0,
            start_date      TEXT,
            end_date        TEXT,
            memo            TEXT
        );

        CREATE TABLE IF NOT EXISTS property_costs (
            id              SERIAL PRIMARY KEY,
            real_estate_id  INTEGER NOT NULL REFERENCES real_estate(id),
            cost_type       TEXT NOT NULL,
            name            TEXT NOT NULL,
            amount          INTEGER NOT NULL DEFAULT 0,
            date            TEXT,
            memo            TEXT
        );

        CREATE TABLE IF NOT EXISTS fund_groups (
            id         SERIAL PRIMARY KEY,
            name       TEXT NOT NULL UNIQUE,
            sort_order INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS fund_group_rules (
            id            SERIAL PRIMARY KEY,
            keyword       TEXT NOT NULL,
            fund_group_id INTEGER NOT NULL REFERENCES fund_groups(id)
        );

        CREATE TABLE IF NOT EXISTS monthly_fund_budgets (
            id            SERIAL PRIMARY KEY,
            fund_group_id INTEGER NOT NULL REFERENCES fund_groups(id),
            year          INTEGER NOT NULL,
            month         INTEGER NOT NULL,
            budget_amount INTEGER NOT NULL DEFAULT 0,
            UNIQUE(fund_group_id, year, month)
        );

        CREATE TABLE IF NOT EXISTS asset_snapshots (
            month           TEXT PRIMARY KEY, -- 'YYYY-MM'
            cash            INTEGER DEFAULT 0,
            stocks          INTEGER DEFAULT 0,
            real_estate     INTEGER DEFAULT 0,
            crypto          INTEGER DEFAULT 0,
            pension         INTEGER DEFAULT 0,
            total           INTEGER DEFAULT 0,
            updated_at      TEXT
        );

        CREATE TABLE IF NOT EXISTS daily_snapshots (
            id          SERIAL PRIMARY KEY,
            day         DATE    NOT NULL UNIQUE,
            cash        BIGINT  DEFAULT 0,
            stocks      BIGINT  DEFAULT 0,
            real_estate BIGINT  DEFAULT 0,
            crypto      BIGINT  DEFAULT 0,
            pension     BIGINT  DEFAULT 0,
            total       BIGINT  DEFAULT 0,
            net_worth   BIGINT  DEFAULT 0,
            updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS lifecycle_profile (
            id         SERIAL PRIMARY KEY,
            role       VARCHAR(20) NOT NULL,
            name       VARCHAR(50),
            birth_year INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS lifecycle_events (
            id          SERIAL PRIMARY KEY,
            event_year  INTEGER NOT NULL,
            event_type  VARCHAR(30) NOT NULL,
            asset_name  VARCHAR(100),
            amount      BIGINT DEFAULT 0,
            memo        VARCHAR(200),
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS lifecycle_settings (
            id                   SERIAL PRIMARY KEY,
            sim_years            INTEGER DEFAULT 30,
            annual_return_stocks NUMERIC(5,2) DEFAULT 7,
            annual_return_re     NUMERIC(5,2) DEFAULT 3,
            annual_return_cash   NUMERIC(5,2) DEFAULT 2,
            annual_expense_growth NUMERIC(5,2) DEFAULT 2,
            override_annual_inflow BIGINT DEFAULT NULL,
            updated_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        INSERT INTO lifecycle_settings (sim_years, annual_return_stocks, annual_return_re, annual_return_cash, annual_expense_growth, override_annual_inflow)
        SELECT 30, 7.00, 3.00, 2.00, 2.00, NULL
        WHERE NOT EXISTS (SELECT 1 FROM lifecycle_settings);

        CREATE TABLE IF NOT EXISTS etf_tx (
            id      SERIAL PRIMARY KEY,
            etf_id  INTEGER NOT NULL REFERENCES etf(id),
            tx_date TEXT    NOT NULL,
            tx_type TEXT    NOT NULL,
            price   REAL NOT NULL DEFAULT 0,
            quantity REAL   NOT NULL DEFAULT 0,
            fee     REAL DEFAULT 0,
            memo    TEXT
        );

        CREATE TABLE IF NOT EXISTS app_settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS budget_categories (
            id         SERIAL PRIMARY KEY,
            name       TEXT NOT NULL UNIQUE,
            sort_order INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS budget_category_rules (
            id       SERIAL PRIMARY KEY,
            keyword  TEXT NOT NULL UNIQUE,
            category TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS stock_categories (
            id         SERIAL PRIMARY KEY,
            name       TEXT NOT NULL UNIQUE,
            sort_order INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS sold_real_estate (
            id              SERIAL PRIMARY KEY,
            name            TEXT,
            re_type         TEXT,
            purchase_date   TEXT,
            purchase_price  INTEGER DEFAULT 0,
            real_inv        INTEGER DEFAULT 0,
            sell_date       TEXT,
            sell_price      INTEGER DEFAULT 0,
            tax             INTEGER DEFAULT 0,
            other_costs     INTEGER DEFAULT 0,
            profit          INTEGER DEFAULT 0,
            roi             REAL DEFAULT 0,
            memo            TEXT,
            lease_memo      TEXT,
            created_at      TEXT
        );

        CREATE TABLE IF NOT EXISTS ipo (
            id              SERIAL PRIMARY KEY,
            name            TEXT NOT NULL,
            listing_date    TEXT NOT NULL,
            ipo_price       INTEGER DEFAULT 0,
            quantity        REAL DEFAULT 0,
            realized_pnl    INTEGER DEFAULT 0,
            fee             INTEGER DEFAULT 0,
            memo            TEXT,
            lockup_ratio    REAL DEFAULT 0,
            floating_ratio  REAL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS crypto_sell (
            id          SERIAL PRIMARY KEY,
            sell_date   DATE NOT NULL,
            name        TEXT NOT NULL,
            pnl         INTEGER DEFAULT 0,
            memo        TEXT,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS real_estate_payments (
            id              SERIAL PRIMARY KEY,
            real_estate_id  INTEGER REFERENCES real_estate(id) ON DELETE CASCADE,
            sold_real_estate_id INTEGER REFERENCES sold_real_estate(id) ON DELETE CASCADE,
            direction       TEXT NOT NULL,   -- 'buy' or 'sell'
            payment_type    TEXT NOT NULL,   -- '계약금', '중도금', '잔금', '기타'
            scheduled_date  TEXT,
            actual_date     TEXT,            -- NULL = not yet paid/received
            amount          INTEGER DEFAULT 0,
            memo            TEXT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS split_buy_plans (
            id              SERIAL PRIMARY KEY,
            name            TEXT NOT NULL,
            ticker          TEXT,
            total_budget    BIGINT NOT NULL DEFAULT 0,
            ath             REAL NOT NULL,
            current_price   REAL,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS split_buy_plan_steps (
            id              SERIAL PRIMARY KEY,
            plan_id         INTEGER NOT NULL REFERENCES split_buy_plans(id) ON DELETE CASCADE,
            step_number     INTEGER NOT NULL,
            drawdown_pct    REAL NOT NULL,
            ratio           REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS split_buy_transactions (
            id              SERIAL PRIMARY KEY,
            plan_id         INTEGER NOT NULL REFERENCES split_buy_plans(id) ON DELETE CASCADE,
            tx_type         TEXT NOT NULL, -- 'buy', 'sell'
            step_number     INTEGER,
            price           REAL NOT NULL,
            quantity        REAL NOT NULL,
            tx_date         TEXT NOT NULL,
            memo            TEXT
        );

        CREATE TABLE IF NOT EXISTS recurring_budget (
            id             SERIAL PRIMARY KEY,
            name           VARCHAR(200) NOT NULL,
            category       VARCHAR(100),
            payment_method VARCHAR(50),
            amount         BIGINT NOT NULL DEFAULT 0,
            card_id        INTEGER REFERENCES card_info(id) ON DELETE SET NULL,
            day_of_month   INTEGER NOT NULL CHECK (day_of_month BETWEEN 1 AND 31),
            start_month    VARCHAR(7) NOT NULL,
            end_month      VARCHAR(7),
            memo           VARCHAR(500),
            is_active      BOOLEAN DEFAULT TRUE,
            created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS invest_plans (
            id              SERIAL PRIMARY KEY,
            stock_id        INTEGER REFERENCES stocks(id)  ON DELETE CASCADE,
            etf_id          INTEGER REFERENCES etf(id)     ON DELETE CASCADE,
            plan_name       VARCHAR(100),
            target_price    BIGINT  NOT NULL,
            upper_pct       NUMERIC(5,2) DEFAULT 0,
            lower_pct       NUMERIC(5,2) DEFAULT 20,
            split_count     INTEGER DEFAULT 5,
            total_budget    BIGINT  DEFAULT 0,
            strategy        VARCHAR(20) DEFAULT 'inverse_pyramid',
            status          VARCHAR(20) DEFAULT 'active',
            memo            VARCHAR(300),
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS invest_plan_steps (
            id          SERIAL PRIMARY KEY,
            plan_id     INTEGER NOT NULL REFERENCES invest_plans(id) ON DELETE CASCADE,
            step_no     INTEGER NOT NULL,
            trigger_price BIGINT NOT NULL,
            target_amount BIGINT NOT NULL,
            target_shares NUMERIC(12,4),
            weight_pct  NUMERIC(5,2),
            executed_at DATE,
            executed_price BIGINT,
            executed_shares NUMERIC(12,4),
            executed_amount BIGINT,
            is_executed BOOLEAN DEFAULT FALSE
        );
    """)

    conn.commit()

    # 마이그레이션: 기존 DB에 컬럼 추가 / 데이터 이전
    migrations = [
        """CREATE TABLE IF NOT EXISTS lifecycle_profile (
            id         SERIAL PRIMARY KEY,
            role       VARCHAR(20) NOT NULL,
            name       VARCHAR(50),
            birth_year INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS lifecycle_events (
            id          SERIAL PRIMARY KEY,
            event_year  INTEGER NOT NULL,
            event_type  VARCHAR(30) NOT NULL,
            asset_name  VARCHAR(100),
            amount      BIGINT DEFAULT 0,
            memo        VARCHAR(200),
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS lifecycle_settings (
            id                   SERIAL PRIMARY KEY,
            sim_years            INTEGER DEFAULT 30,
            annual_return_stocks NUMERIC(5,2) DEFAULT 7,
            annual_return_re     NUMERIC(5,2) DEFAULT 3,
            annual_return_cash   NUMERIC(5,2) DEFAULT 2,
            annual_expense_growth NUMERIC(5,2) DEFAULT 2,
            override_annual_inflow BIGINT DEFAULT NULL,
            updated_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """INSERT INTO lifecycle_settings (sim_years, annual_return_stocks, annual_return_re, annual_return_cash, annual_expense_growth, override_annual_inflow)
        SELECT 30, 7.00, 3.00, 2.00, 2.00, NULL
        WHERE NOT EXISTS (SELECT 1 FROM lifecycle_settings)""",
        """CREATE TABLE IF NOT EXISTS daily_snapshots (
            id          SERIAL PRIMARY KEY,
            day         DATE    NOT NULL UNIQUE,
            cash        BIGINT  DEFAULT 0,
            stocks      BIGINT  DEFAULT 0,
            real_estate BIGINT  DEFAULT 0,
            crypto      BIGINT  DEFAULT 0,
            pension     BIGINT  DEFAULT 0,
            total       BIGINT  DEFAULT 0,
            net_worth   BIGINT  DEFAULT 0,
            updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS real_estate_payments (
            id              SERIAL PRIMARY KEY,
            real_estate_id  INTEGER REFERENCES real_estate(id) ON DELETE CASCADE,
            sold_real_estate_id INTEGER REFERENCES sold_real_estate(id) ON DELETE CASCADE,
            direction       TEXT NOT NULL,
            payment_type    TEXT NOT NULL,
            scheduled_date  TEXT,
            actual_date     TEXT,
            amount          INTEGER DEFAULT 0,
            memo            TEXT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP
        )""",
        "ALTER TABLE budget   ADD COLUMN IF NOT EXISTS card_id          INTEGER REFERENCES card_info(id)",
        "ALTER TABLE budget   ADD COLUMN IF NOT EXISTS recurring_id     INTEGER REFERENCES budget_recurring(id)",
        "ALTER TABLE card_tx  ADD COLUMN IF NOT EXISTS budget_id         INTEGER REFERENCES budget(id)",
        "ALTER TABLE card_tx  ADD COLUMN IF NOT EXISTS category_locked   INTEGER DEFAULT 0",
        "ALTER TABLE card_tx  ADD COLUMN IF NOT EXISTS fund_group_id     INTEGER REFERENCES fund_groups(id)",
        "ALTER TABLE card_tx  ADD COLUMN IF NOT EXISTS fund_group_locked INTEGER DEFAULT 0",
        "ALTER TABLE stocks   ADD COLUMN IF NOT EXISTS category          TEXT",
        "ALTER TABLE etf      ADD COLUMN IF NOT EXISTS category          TEXT",
        "ALTER TABLE real_estate_payments ADD COLUMN IF NOT EXISTS sold_real_estate_id INTEGER REFERENCES sold_real_estate(id) ON DELETE CASCADE",
        "ALTER TABLE real_estate ADD COLUMN IF NOT EXISTS sell_date TEXT",
        "ALTER TABLE real_estate ADD COLUMN IF NOT EXISTS sell_tax INTEGER DEFAULT 0",
        "ALTER TABLE real_estate ADD COLUMN IF NOT EXISTS sell_other_costs INTEGER DEFAULT 0",
        "ALTER TABLE real_estate ADD COLUMN IF NOT EXISTS sell_memo TEXT",
        "ALTER TABLE sold_real_estate ADD COLUMN IF NOT EXISTS lease_memo TEXT",
        "ALTER TABLE ipo ADD COLUMN IF NOT EXISTS lockup_ratio REAL DEFAULT 0",
        "ALTER TABLE ipo ADD COLUMN IF NOT EXISTS floating_ratio REAL DEFAULT 0",
        # ETF 기존 데이터 → etf_tx 이전
        "INSERT INTO etf_tx (etf_id, tx_date, tx_type, price, quantity, fee, memo) "
        "SELECT id, COALESCE(NULLIF(buy_date,''), TO_CHAR(NOW(),'YYYY-MM-DD')), 'buy', buy_price, quantity, 0, '기존데이터' "
        "FROM etf WHERE quantity > 0 AND id NOT IN (SELECT DISTINCT etf_id FROM etf_tx)",
        # 기존 stocks 행을 stock_tx 매수 거래로 이전
        "INSERT INTO stock_tx (stock_id, tx_date, tx_type, price, quantity, fee, memo) "
        "SELECT id, buy_date, 'buy', buy_price, quantity, 0, '기존데이터' "
        "FROM stocks WHERE (buy_date IS NOT NULL AND buy_date != '') AND quantity > 0 "
        "AND id NOT IN (SELECT DISTINCT stock_id FROM stock_tx)",
        # 가계부 기본 카테고리
        "INSERT INTO budget_categories (name, sort_order) VALUES "
        "('식비',0),('카페/간식',1),('술/유흥',2),('교통비',3),('주유/주차',4),"
        "('주거/관리비',5),('공과금/세금',6),('통신비',7),('보험',8),"
        "('의료/건강',9),('약국',10),('쇼핑/의류',11),('미용/뷰티',12),"
        "('교육/학원',13),('육아/아이',14),('문화/여가',15),('여행/숙박',16),"
        "('경조사/선물',17),('반려동물',18),('구독/멤버십',19),('저축/투자',20),('기타',21) "
        "ON CONFLICT (name) DO NOTHING",
        # 카드 거래 기본 카테고리
        "INSERT INTO categories (name, sort_order) VALUES "
        "('식비',0),('카페/간식',1),('술/유흥',2),('교통비',3),('주유/주차',4),"
        "('주거/관리비',5),('공과금/세금',6),('통신비',7),('보험',8),"
        "('의료/건강',9),('약국',10),('쇼핑/의류',11),('미용/뷰티',12),"
        "('교육/학원',13),('육아/아이',14),('문화/여가',15),('여행/숙박',16),"
        "('경조사/선물',17),('반려동물',18),('구독/멤버십',19),('저축/투자',20),('기타',21) "
        "ON CONFLICT (name) DO NOTHING",
        # 주식 구분 기본값
        "INSERT INTO stock_categories (name, sort_order) VALUES "
        "('스윙',0),('올웨더',1),('지수투자',2),('TQQQ',3),('공모주',4),('사이클',5),('해외 스윙',6) "
        "ON CONFLICT (name) DO NOTHING",
        # 외국 주식/ETF 거래 소수점 입력용 REAL 타입 마이그레이션
        "ALTER TABLE stocks ALTER COLUMN current_price TYPE REAL",
        "ALTER TABLE stock_tx ALTER COLUMN price TYPE REAL",
        "ALTER TABLE stock_tx ALTER COLUMN fee TYPE REAL",
        "ALTER TABLE etf ALTER COLUMN buy_price TYPE REAL",
        "ALTER TABLE etf ALTER COLUMN current_price TYPE REAL",
        "ALTER TABLE etf_tx ALTER COLUMN price TYPE REAL",
        "ALTER TABLE etf_tx ALTER COLUMN fee TYPE REAL",
        "ALTER TABLE income ADD COLUMN IF NOT EXISTS currency TEXT NOT NULL DEFAULT 'KRW'",
        "ALTER TABLE income ADD COLUMN IF NOT EXISTS exchange_rate REAL NOT NULL DEFAULT 1.0",
        "ALTER TABLE income ADD COLUMN IF NOT EXISTS original_amount REAL NOT NULL DEFAULT 0.0",
        "ALTER TABLE etf ADD COLUMN IF NOT EXISTS invest_strategy VARCHAR(20) DEFAULT 'dca'",
        "ALTER TABLE etf ADD COLUMN IF NOT EXISTS total_budget BIGINT DEFAULT 0",
        "ALTER TABLE etf ADD COLUMN IF NOT EXISTS invest_periods INTEGER DEFAULT 12",
        "ALTER TABLE etf ADD COLUMN IF NOT EXISTS drawdown_step NUMERIC(4,1) DEFAULT 5.0",
        """CREATE TABLE IF NOT EXISTS split_buy_plans (
            id              SERIAL PRIMARY KEY,
            name            TEXT NOT NULL,
            ticker          TEXT,
            total_budget    BIGINT NOT NULL DEFAULT 0,
            ath             REAL NOT NULL,
            current_price   REAL,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS split_buy_plan_steps (
            id              SERIAL PRIMARY KEY,
            plan_id         INTEGER NOT NULL REFERENCES split_buy_plans(id) ON DELETE CASCADE,
            step_number     INTEGER NOT NULL,
            drawdown_pct    REAL NOT NULL,
            ratio           REAL NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS split_buy_transactions (
            id              SERIAL PRIMARY KEY,
            plan_id         INTEGER NOT NULL REFERENCES split_buy_plans(id) ON DELETE CASCADE,
            tx_type         TEXT NOT NULL,
            step_number     INTEGER,
            price           REAL NOT NULL,
            quantity        REAL NOT NULL,
            tx_date         TEXT NOT NULL,
            memo            TEXT
        )""",
        "ALTER TABLE split_buy_plans ADD COLUMN IF NOT EXISTS drop_from REAL DEFAULT 30",
        "ALTER TABLE split_buy_plans ADD COLUMN IF NOT EXISTS drop_to   REAL DEFAULT 70",
        "ALTER TABLE split_buy_plans ADD COLUMN IF NOT EXISTS step_count INTEGER DEFAULT 5",
        """CREATE TABLE IF NOT EXISTS recurring_budget (
            id             SERIAL PRIMARY KEY,
            name           VARCHAR(200) NOT NULL,
            category       VARCHAR(100),
            payment_method VARCHAR(50),
            amount         BIGINT NOT NULL DEFAULT 0,
            card_id        INTEGER REFERENCES card_info(id) ON DELETE SET NULL,
            day_of_month   INTEGER NOT NULL CHECK (day_of_month BETWEEN 1 AND 31),
            start_month    VARCHAR(7) NOT NULL,
            end_month      VARCHAR(7),
            memo           VARCHAR(500),
            is_active      BOOLEAN DEFAULT TRUE,
            created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        "ALTER TABLE budget ADD COLUMN IF NOT EXISTS is_auto_generated BOOLEAN DEFAULT FALSE",
        "ALTER TABLE budget DROP CONSTRAINT IF EXISTS budget_recurring_id_fkey",
        "ALTER TABLE budget ADD CONSTRAINT fk_budget_recurring_budget FOREIGN KEY (recurring_id) REFERENCES recurring_budget(id) ON DELETE SET NULL",
        """CREATE TABLE IF NOT EXISTS invest_plans (
            id              SERIAL PRIMARY KEY,
            stock_id        INTEGER REFERENCES stocks(id)  ON DELETE CASCADE,
            etf_id          INTEGER REFERENCES etf(id)     ON DELETE CASCADE,
            plan_name       VARCHAR(100),
            target_price    BIGINT  NOT NULL,
            upper_pct       NUMERIC(5,2) DEFAULT 0,
            lower_pct       NUMERIC(5,2) DEFAULT 20,
            split_count     INTEGER DEFAULT 5,
            total_budget    BIGINT  DEFAULT 0,
            strategy        VARCHAR(20) DEFAULT 'inverse_pyramid',
            status          VARCHAR(20) DEFAULT 'active',
            memo            VARCHAR(300),
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS invest_plan_steps (
            id          SERIAL PRIMARY KEY,
            plan_id     INTEGER NOT NULL REFERENCES invest_plans(id) ON DELETE CASCADE,
            step_no     INTEGER NOT NULL,
            trigger_price BIGINT NOT NULL,
            target_amount BIGINT NOT NULL,
            target_shares NUMERIC(12,4),
            weight_pct  NUMERIC(5,2),
            executed_at DATE,
            executed_price BIGINT,
            executed_shares NUMERIC(12,4),
            executed_amount BIGINT,
            is_executed BOOLEAN DEFAULT FALSE
        )""",
        "ALTER TABLE stocks ADD COLUMN IF NOT EXISTS ath REAL DEFAULT 0",
        "ALTER TABLE etf ADD COLUMN IF NOT EXISTS ath REAL DEFAULT 0",
        "ALTER TABLE invest_plan_steps ADD COLUMN IF NOT EXISTS is_executed BOOLEAN DEFAULT FALSE",
        "ALTER TABLE invest_plan_steps ADD COLUMN IF NOT EXISTS executed_at DATE",
        "ALTER TABLE invest_plan_steps ADD COLUMN IF NOT EXISTS executed_price BIGINT",
        "ALTER TABLE invest_plan_steps ADD COLUMN IF NOT EXISTS executed_shares NUMERIC(12,4)",
        "ALTER TABLE invest_plan_steps ADD COLUMN IF NOT EXISTS executed_amount BIGINT",
        "ALTER TABLE invest_plan_steps ALTER COLUMN trigger_price TYPE NUMERIC(14,4) USING trigger_price::NUMERIC",
        "UPDATE stock_tx SET tx_type='buy'  WHERE tx_type='매수'",
        "UPDATE stock_tx SET tx_type='sell' WHERE tx_type='매도'",
        "UPDATE etf_tx   SET tx_type='buy'  WHERE tx_type='매수'",
        "UPDATE etf_tx   SET tx_type='sell' WHERE tx_type='매도'",
        "ALTER TABLE stock_tx ADD COLUMN IF NOT EXISTS realized_pnl REAL DEFAULT 0.0",
        "ALTER TABLE etf_tx   ADD COLUMN IF NOT EXISTS realized_pnl REAL DEFAULT 0.0",
        """CREATE TABLE IF NOT EXISTS rebalance_assignments (
            id          SERIAL PRIMARY KEY,
            source_type TEXT NOT NULL,
            source_id   INTEGER NOT NULL,
            asset_class TEXT NOT NULL,
            UNIQUE(source_type, source_id)
        )""",
        "ALTER TABLE rebalance_assignments ADD COLUMN IF NOT EXISTS cash_amount BIGINT DEFAULT 0",
    ]
    for sql in migrations:
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(sql)
        except psycopg2.Error:
            pass  # 이미 존재하면 무시

    # 특정 ETF 기본 메모 설정 (메모가 없는 경우에만)
    _etf_default_memos = {
        '122630': '지수가 30%, 40%, 50%, 60%, 70% 빠질 때마다 시드 머니의 20% 매수 (해당 계좌의 돈만 사용. 여유자금 생기면 투입 가능)',
        '233740': '지수가 30%, 40%, 50%, 60%, 70% 빠질 때마다 시드 머니의 20% 매수 (해당 계좌의 돈만 사용. 여유자금 생기면 투입 가능)',
    }
    try:
        with conn:
            with conn.cursor() as cur:
                for ticker, memo_text in _etf_default_memos.items():
                    cur.execute(
                        "UPDATE etf SET memo = %s WHERE UPPER(ticker) = UPPER(%s) AND (memo IS NULL OR memo = '')",
                        (memo_text, ticker)
                    )
    except Exception:
        pass

    # 기존 sell 거래내역 realized_pnl 보정
    try:
        with conn:
            with conn.cursor() as cur:
                # 1. 주식 거래내역 보정
                cur.execute("SELECT id, stock_id, tx_date, tx_type, price, quantity, fee, realized_pnl FROM stock_tx ORDER BY stock_id, tx_date, id")
                all_stock_tx = cur.fetchall()
                
                from collections import defaultdict
                tx_by_stock = defaultdict(list)
                for tx in all_stock_tx:
                    tx_by_stock[tx['stock_id']].append(tx)
                
                for stock_id, txs in tx_by_stock.items():
                    qty = 0.0
                    avg_cost = 0.0
                    for tx in txs:
                        tq = float(tx['quantity'] or 0)
                        tp = float(tx['price'] or 0)
                        if tq <= 0:
                            continue
                        if tx['tx_type'] in ('buy', '매수'):
                            new_qty = qty + tq
                            avg_cost = (qty * avg_cost + tq * tp) / new_qty if new_qty > 0 else 0.0
                            qty = new_qty
                        else:
                            if tx['realized_pnl'] is None or float(tx['realized_pnl']) == 0.0:
                                pnl = (tp - avg_cost) * tq
                                cur.execute("UPDATE stock_tx SET realized_pnl = %s WHERE id = %s", (pnl, tx['id']))
                            qty = max(0.0, qty - tq)
                            if qty == 0.0:
                                avg_cost = 0.0
                
                # 2. ETF 거래내역 보정
                cur.execute("SELECT id, etf_id, tx_date, tx_type, price, quantity, fee, realized_pnl FROM etf_tx ORDER BY etf_id, tx_date, id")
                all_etf_tx = cur.fetchall()
                
                tx_by_etf = defaultdict(list)
                for tx in all_etf_tx:
                    tx_by_etf[tx['etf_id']].append(tx)
                
                for etf_id, txs in tx_by_etf.items():
                    qty = 0.0
                    avg_cost = 0.0
                    for tx in txs:
                        tq = float(tx['quantity'] or 0)
                        tp = float(tx['price'] or 0)
                        if tq <= 0:
                            continue
                        if tx['tx_type'] in ('buy', '매수'):
                            new_qty = qty + tq
                            avg_cost = (qty * avg_cost + tq * tp) / new_qty if new_qty > 0 else 0.0
                            qty = new_qty
                        else:
                            if tx['realized_pnl'] is None or float(tx['realized_pnl']) == 0.0:
                                pnl = (tp - avg_cost) * tq
                                cur.execute("UPDATE etf_tx SET realized_pnl = %s WHERE id = %s", (pnl, tx['id']))
                            qty = max(0.0, qty - tq)
                            if qty == 0.0:
                                avg_cost = 0.0
    except Exception as e:
        print("Migration realized_pnl error:", e)

    conn.close()
