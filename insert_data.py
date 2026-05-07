import sqlite3
import os
from datetime import datetime

DB_PATH = 'finance.db'

def insert_sample():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 1. 수입 (Income)
    incomes = [
        ('2024-04-01', '급여', '4월 월급', '본캐 월급', 5000000),
        ('2024-04-15', '부수입', '블로그 광고', '애드센스', 150000)
    ]
    c.executemany("INSERT INTO income (date, category, name, memo, amount) VALUES (?,?,?,?,?)", incomes)

    # 2. 카드 정보 (Card Info)
    cards = [
        (1234, '신한 Deep Dream', 5000000, 14, 1, '전가맹점 적립'),
        (5678, '현대 Zero Edition2', 3000000, 25, 10, '무실적 할인')
    ]
    c.executemany("INSERT INTO card_info (card_num, card_name, limit_amount, payment_day, billing_day, benefit) VALUES (?,?,?,?,?,?)", cards)

    # 3. 지출 (Budget/Expenses)
    expenses = [
        ('2024-04-02', '식비', '점심 식사', '고기집', '카드', 15000, '맛있음'),
        ('2024-04-05', '쇼핑', '운동화', '나이키', '카드', 129000, '세일중')
    ]
    c.executemany("INSERT INTO budget (date, category, name, type, payment_method, amount, memo) VALUES (?,?,?,?,?,?,?)", expenses)

    # 4. 주식 (Stocks)
    stocks = [
        ('삼성전자', '005930', '2023-01-10', 60000, 100, 84000, 1444, '장기보유'),
        ('Apple', 'AAPL', '2023-05-20', 170, 10, 190, 0.24, '미국주식')
    ]
    c.executemany("INSERT INTO stocks (name, ticker, buy_date, buy_price, quantity, current_price, dividend, memo) VALUES (?,?,?,?,?,?,?,?)", stocks)

    # 5. 목표 (Goals)
    goals = [
        ('내 집 마련', 500000000, 50000000, 2000000, '2030-12-31', '꿈은 이루어진다'),
        ('유럽 여행', 10000000, 3000000, 500000, '2025-06-01', '여름 휴가')
    ]
    c.executemany("INSERT INTO goals (name, target_amount, current_amount, monthly_saving, target_date, memo) VALUES (?,?,?,?,?,?)", goals)

    conn.commit()
    conn.close()
    print("Sample data inserted successfully!")

if __name__ == '__main__':
    insert_sample()
