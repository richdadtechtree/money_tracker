import os
import psycopg2
from psycopg2.extras import DictCursor

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

def get_db():
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        raise ValueError("DATABASE_URL environment variable is not set")
    conn = psycopg2.connect(db_url, cursor_factory=DictCursor)
    return conn


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
            amount          INTEGER NOT NULL DEFAULT 0
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
            buy_price       INTEGER DEFAULT 0,
            quantity        REAL DEFAULT 0,
            current_price   INTEGER DEFAULT 0,
            dividend        INTEGER DEFAULT 0,
            memo            TEXT
        );

        CREATE TABLE IF NOT EXISTS stock_tx (
            id          SERIAL PRIMARY KEY,
            stock_id    INTEGER NOT NULL REFERENCES stocks(id),
            tx_date     TEXT    NOT NULL,
            tx_type     TEXT    NOT NULL,
            price       INTEGER NOT NULL DEFAULT 0,
            quantity    REAL    NOT NULL DEFAULT 0,
            fee         INTEGER DEFAULT 0,
            memo        TEXT
        );

        CREATE TABLE IF NOT EXISTS etf (
            id              SERIAL PRIMARY KEY,
            name            TEXT,
            ticker          TEXT,
            buy_date        TEXT,
            buy_price       INTEGER DEFAULT 0,
            quantity        REAL DEFAULT 0,
            current_price   INTEGER DEFAULT 0,
            etf_type        TEXT,
            memo            TEXT
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
            memo            TEXT
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

        CREATE TABLE IF NOT EXISTS etf_tx (
            id      SERIAL PRIMARY KEY,
            etf_id  INTEGER NOT NULL REFERENCES etf(id),
            tx_date TEXT    NOT NULL,
            tx_type TEXT    NOT NULL,
            price   INTEGER NOT NULL DEFAULT 0,
            quantity REAL   NOT NULL DEFAULT 0,
            fee     INTEGER DEFAULT 0,
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
            memo            TEXT
        );

        CREATE TABLE IF NOT EXISTS real_estate_payments (
            id              SERIAL PRIMARY KEY,
            real_estate_id  INTEGER REFERENCES real_estate(id) ON DELETE CASCADE,
            direction       TEXT NOT NULL,   -- 'buy' or 'sell'
            payment_type    TEXT NOT NULL,   -- '계약금', '중도금', '잔금', '기타'
            scheduled_date  TEXT,
            actual_date     TEXT,            -- NULL = not yet paid/received
            amount          INTEGER DEFAULT 0,
            memo            TEXT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)

    conn.commit()

    # 마이그레이션: 기존 DB에 컬럼 추가 / 데이터 이전
    migrations = [
        """CREATE TABLE IF NOT EXISTS real_estate_payments (
            id              SERIAL PRIMARY KEY,
            real_estate_id  INTEGER REFERENCES real_estate(id) ON DELETE CASCADE,
            direction       TEXT NOT NULL,
            payment_type    TEXT NOT NULL,
            scheduled_date  TEXT,
            actual_date     TEXT,
            amount          INTEGER DEFAULT 0,
            memo            TEXT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP
        )""",
        "ALTER TABLE budget   ADD COLUMN card_id          INTEGER REFERENCES card_info(id)",
        "ALTER TABLE budget   ADD COLUMN recurring_id     INTEGER REFERENCES budget_recurring(id)",
        "ALTER TABLE card_tx  ADD COLUMN budget_id         INTEGER REFERENCES budget(id)",
        "ALTER TABLE card_tx  ADD COLUMN category_locked   INTEGER DEFAULT 0",
        "ALTER TABLE card_tx  ADD COLUMN fund_group_id     INTEGER REFERENCES fund_groups(id)",
        "ALTER TABLE card_tx  ADD COLUMN fund_group_locked INTEGER DEFAULT 0",
        "ALTER TABLE stocks   ADD COLUMN category          TEXT",
        # ETF 기존 데이터 → etf_tx 이전
        "INSERT INTO etf_tx (etf_id, tx_date, tx_type, price, quantity, fee, memo) "
        "SELECT id, COALESCE(NULLIF(buy_date,''), TO_CHAR(NOW(),'YYYY-MM-DD')), 'buy', buy_price, quantity, 0, '기존데이터' "
        "FROM etf WHERE quantity > 0 AND id NOT IN (SELECT DISTINCT etf_id FROM etf_tx)",
    ]
    for sql in migrations:
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(sql)
        except psycopg2.Error:
            pass  # 이미 존재하면 무시

    try:
        with conn:
            with conn.cursor() as cur:
                # 가계부 기본 카테고리 삽입
                _budget_cats = ['식비','교통비','주거비','의료비','교육비','문화/여가','쇼핑','통신비','보험','술','기타']
                for i, n in enumerate(_budget_cats):
                    cur.execute("INSERT INTO budget_categories (name, sort_order) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING", (n, i))
                # 주식 구분 기본값 삽입
                _stock_cats = ['스윙','올웨더','지수투자','TQQQ','공모주','사이클','해외스윙']
                for i, n in enumerate(_stock_cats):
                    cur.execute("INSERT INTO stock_categories (name, sort_order) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING", (n, i))
                # 기본 카테고리 삽입
                for i, n in enumerate(['식비', '쇼핑', '교통', '의료', '문화', '기타']):
                    cur.execute("INSERT INTO categories (name, sort_order) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING", (n, i))
                
                # 기존 stocks 행을 stock_tx 매수 거래로 이전 (stock_tx가 비어있는 종목만)
                cur.execute("""
                    INSERT INTO stock_tx (stock_id, tx_date, tx_type, price, quantity, fee, memo)
                    SELECT id, buy_date, 'buy', buy_price, quantity, 0, '기존데이터'
                    FROM stocks
                    WHERE (buy_date IS NOT NULL AND buy_date != '')
                      AND quantity > 0
                      AND id NOT IN (SELECT DISTINCT stock_id FROM stock_tx)
                """)
    except psycopg2.Error:
        pass

    conn.close()
