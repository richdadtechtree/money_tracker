import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'finance.db')


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    c.executescript("""
        CREATE TABLE IF NOT EXISTS income (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            date            TEXT NOT NULL,
            category        TEXT,
            name            TEXT,
            memo            TEXT,
            amount          INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS budget (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            date            TEXT NOT NULL,
            category        TEXT,
            name            TEXT,
            type            TEXT,
            payment_method  TEXT,
            amount          INTEGER NOT NULL DEFAULT 0,
            memo            TEXT
        );

        CREATE TABLE IF NOT EXISTS card_info (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            card_num        INTEGER NOT NULL,
            card_name       TEXT,
            limit_amount    INTEGER DEFAULT 0,
            payment_day     INTEGER,
            billing_day     INTEGER,
            benefit         TEXT
        );

        CREATE TABLE IF NOT EXISTS card_tx (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            card_id         INTEGER REFERENCES card_info(id),
            date            TEXT NOT NULL,
            name            TEXT,
            category        TEXT,
            amount          INTEGER NOT NULL DEFAULT 0,
            installment     INTEGER DEFAULT 1,
            memo            TEXT
        );

        CREATE TABLE IF NOT EXISTS stocks (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
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
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_id    INTEGER NOT NULL REFERENCES stocks(id),
            tx_date     TEXT    NOT NULL,
            tx_type     TEXT    NOT NULL,
            price       INTEGER NOT NULL DEFAULT 0,
            quantity    REAL    NOT NULL DEFAULT 0,
            fee         INTEGER DEFAULT 0,
            memo        TEXT
        );

        CREATE TABLE IF NOT EXISTS etf (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
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
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
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
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            address         TEXT,
            deposit         INTEGER DEFAULT 0,
            monthly_rent    INTEGER DEFAULT 0,
            maintenance     INTEGER DEFAULT 0,
            start_date      TEXT,
            end_date        TEXT
        );

        CREATE TABLE IF NOT EXISTS real_estate (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT,
            re_type         TEXT,
            purchase_date   TEXT,
            purchase_price  INTEGER DEFAULT 0,
            current_price   INTEGER DEFAULT 0,
            memo            TEXT
        );

        CREATE TABLE IF NOT EXISTS loans (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
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
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            pension_type    TEXT,
            name            TEXT,
            institution     TEXT,
            monthly_payment INTEGER DEFAULT 0,
            accumulated     INTEGER DEFAULT 0,
            return_rate     REAL DEFAULT 0,
            memo            TEXT
        );

        CREATE TABLE IF NOT EXISTS goals (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT,
            target_amount   INTEGER DEFAULT 0,
            current_amount  INTEGER DEFAULT 0,
            monthly_saving  INTEGER DEFAULT 0,
            target_date     TEXT,
            memo            TEXT
        );

        CREATE TABLE IF NOT EXISTS cash_deposits (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT,
            amount          INTEGER DEFAULT 0,
            memo            TEXT,
            updated_date    TEXT
        );

        CREATE TABLE IF NOT EXISTS card_mappings (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            card_id  INTEGER UNIQUE REFERENCES card_info(id),
            mapping  TEXT
        );

        CREATE TABLE IF NOT EXISTS card_category_rules (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword  TEXT NOT NULL,
            category TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS categories (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL UNIQUE,
            sort_order INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS tenant_contracts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            real_estate_id  INTEGER NOT NULL REFERENCES real_estate(id),
            contract_type   TEXT NOT NULL,
            deposit         INTEGER NOT NULL DEFAULT 0,
            monthly_rent    INTEGER NOT NULL DEFAULT 0,
            start_date      TEXT,
            end_date        TEXT,
            memo            TEXT
        );

        CREATE TABLE IF NOT EXISTS property_costs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            real_estate_id  INTEGER NOT NULL REFERENCES real_estate(id),
            cost_type       TEXT NOT NULL,
            name            TEXT NOT NULL,
            amount          INTEGER NOT NULL DEFAULT 0,
            date            TEXT,
            memo            TEXT
        );

        CREATE TABLE IF NOT EXISTS fund_groups (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL UNIQUE,
            sort_order INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS fund_group_rules (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword       TEXT NOT NULL,
            fund_group_id INTEGER NOT NULL REFERENCES fund_groups(id)
        );

        CREATE TABLE IF NOT EXISTS monthly_fund_budgets (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            fund_group_id INTEGER NOT NULL REFERENCES fund_groups(id),
            year          INTEGER NOT NULL,
            month         INTEGER NOT NULL,
            budget_amount INTEGER NOT NULL DEFAULT 0,
            UNIQUE(fund_group_id, year, month)
        );
    """)

    # 마이그레이션: 기존 DB에 컬럼 추가 / 데이터 이전
    for sql in [
        "ALTER TABLE budget   ADD COLUMN card_id          INTEGER REFERENCES card_info(id)",
        "ALTER TABLE card_tx  ADD COLUMN budget_id         INTEGER REFERENCES budget(id)",
        "ALTER TABLE card_tx  ADD COLUMN category_locked   INTEGER DEFAULT 0",
        "ALTER TABLE card_tx  ADD COLUMN fund_group_id     INTEGER REFERENCES fund_groups(id)",
        "ALTER TABLE card_tx  ADD COLUMN fund_group_locked INTEGER DEFAULT 0",
        # 기본 카테고리 삽입 (이미 있으면 무시)
        *[f"INSERT OR IGNORE INTO categories (name, sort_order) VALUES ('{n}', {i})"
          for i, n in enumerate(['식비', '쇼핑', '교통', '의료', '문화', '기타'])],
        # 기존 stocks 행을 stock_tx 매수 거래로 이전 (stock_tx가 비어있는 종목만)
        """INSERT INTO stock_tx (stock_id, tx_date, tx_type, price, quantity, fee, memo)
           SELECT id, buy_date, 'buy', buy_price, quantity, 0, '기존데이터'
           FROM stocks
           WHERE (buy_date IS NOT NULL AND buy_date != '')
             AND quantity > 0
             AND id NOT IN (SELECT DISTINCT stock_id FROM stock_tx)""",
    ]:
        try:
            c.execute(sql)
        except Exception:
            pass  # 이미 존재하면 무시

    conn.commit()
    conn.close()
