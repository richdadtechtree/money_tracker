import sqlite3

DB_PATH = 'finance.db'

def update_investments_2026():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 기존 투자 데이터 초기화
    tables = ['stocks', 'stock_tx', 'etf', 'crypto']
    for table in tables:
        c.execute(f"DELETE FROM {table}")

    # 1. 주식 (Stocks) - 국내 및 해외 우량주
    stocks = [
        ('삼성전자', '005930', '2024-03-15', 72000, 100, 84500, 1444, '국내 대장주, 장기 보유'),
        ('SK하이닉스', '000660', '2025-01-10', 145000, 30, 182000, 1200, 'AI 반도체 수혜'),
        ('Apple', 'AAPL', '2024-06-20', 185, 20, 215, 0.96, '아이폰17 기대감'),
        ('NVIDIA', 'NVDA', '2023-12-05', 480, 15, 920, 0.16, 'AI GPU 독점적 지위'),
        ('Microsoft', 'MSFT', '2025-05-12', 390, 10, 445, 3.0, '클라우드 및 AI 매출 증가')
    ]
    c.executemany("""
        INSERT INTO stocks (name, ticker, buy_date, buy_price, quantity, current_price, dividend, memo) 
        VALUES (?,?,?,?,?,?,?,?)
    """, stocks)

    # 2. ETF - 지수 추종 및 테마형
    etfs = [
        ('TIGER 미국S&P500', '360750', '2024-01-05', 13500, 500, 16800, '시장 지수 추종', '연금저축계좌'),
        ('KODEX 200', '069500', '2025-02-15', 32000, 100, 35500, '코스피 200 지수', '국내 시장 대응'),
        ('ACE 미국나스닥100', '379810', '2024-08-10', 15800, 300, 19200, '기술주 위주 ETF', '성장성 기대')
    ]
    c.executemany("""
        INSERT INTO etf (name, ticker, buy_date, buy_price, quantity, current_price, etf_type, memo) 
        VALUES (?,?,?,?,?,?,?,?)
    """, etfs)

    # 3. 가상자산 (Crypto)
    cryptos = [
        ('비트코인', 'BTC', 'Upbit', '2024-11-20', 85000000, 0.25, 125000000, '디지털 금, 비중 확대'),
        ('이더리움', 'ETH', 'Bithumb', '2025-03-15', 4500000, 2.5, 6200000, '스마트 컨트랙트 플랫폼'),
        ('솔라나', 'SOL', 'Upbit', '2025-05-01', 185000, 50, 245000, '생태계 확장성 기대')
    ]
    c.executemany("""
        INSERT INTO crypto (name, symbol, exchange, buy_date, buy_price, quantity, current_price, memo) 
        VALUES (?,?,?,?,?,?,?,?)
    """, cryptos)

    conn.commit()
    conn.close()
    print("Investment data (Stocks, ETF, Crypto) updated to 2026!")

if __name__ == '__main__':
    update_investments_2026()
