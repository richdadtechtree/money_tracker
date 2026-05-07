import sqlite3
import os

DB_PATH = 'finance.db'

def reset_and_fill_realistic():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 기존 데이터 삭제 (깔끔한 시작을 위해)
    tables = ['income', 'budget', 'card_info', 'card_tx', 'stocks', 'stock_tx', 'real_estate', 'loans', 'pension', 'goals', 'cash_deposits']
    for table in tables:
        try: c.execute(f"DELETE FROM {table}")
        except: pass

    # 1. 수입 (Income) - 4월 정기 수입
    incomes = [
        ('2024-04-25', '급여', '사이버텍 4월 급여', '실수령액', 4850000),
        ('2024-04-10', '부수입', '당근마켓 판매', '아이폰 케이스', 25000),
        ('2024-04-15', '이자/배당', '삼성전자 배당금', '분기 배당', 36000)
    ]
    c.executemany("INSERT INTO income (date, category, name, memo, amount) VALUES (?,?,?,?,?)", incomes)

    # 2. 지출 (Budget) - 4월 주요 지출
    expenses = [
        ('2024-04-01', '주거/통신', '월세/관리비', '정기 이체', '계좌이체', 850000, '숨만 쉬어도 나감'),
        ('2024-04-05', '식비', '이마트 장보기', '식재료 구매', '카드', 158000, '일주일치'),
        ('2024-04-12', '교통', '지하철/버스', '후불 교통비', '카드', 125400, '출퇴근'),
        ('2024-04-15', '쇼핑', '무신사 옷 구매', '봄 자켓', '카드', 89000, '지름신'),
        ('2024-04-18', '의료', '치과 치료', '스케일링/검진', '카드', 65000, '정기검진'),
        ('2024-04-20', '식비', '배달의민족', '치킨', '카드', 24000, '주말 보상')
    ]
    c.executemany("INSERT INTO budget (date, category, name, type, payment_method, amount, memo) VALUES (?,?,?,?,?,?,?)", expenses)

    # 3. 카드 정보 (Card Info)
    cards = [
        (4512, '신한 Mr.Life', 10000000, 14, 1, '공과금/마트 할인'),
        (9410, '현대 NAVER 카드', 5000000, 25, 10, '네이버페이 5% 적립')
    ]
    c.executemany("INSERT INTO card_info (card_num, card_name, limit_amount, payment_day, billing_day, benefit) VALUES (?,?,?,?,?,?)", cards)

    # 4. 주식/투자 (Stocks)
    stocks = [
        ('삼성전자', '005930', '2023-05-15', 68000, 50, 84200, 1444, '국장 대장주'),
        ('NVIDIA', 'NVDA', '2023-11-20', 450, 15, 880, 0.16, 'AI 반도체 대장'),
        ('TIGER 미국S&P500', '360750', '2024-01-10', 14500, 200, 16200, 0, '연금저축용')
    ]
    c.executemany("INSERT INTO stocks (name, ticker, buy_date, buy_price, quantity, current_price, dividend, memo) VALUES (?,?,?,?,?,?,?,?)", stocks)

    # 5. 부동산 (Real Estate)
    real_estate = [
        ('서울 마포구 오피스텔', '주거용', '2022-05-10', 350000000, 380000000, '실거주 중'),
        ('경기도 용인시 아파트', '투자용', '2023-08-20', 600000000, 620000000, '갭투자/임대중')
    ]
    c.executemany("INSERT INTO real_estate (name, re_type, purchase_date, purchase_price, current_price, memo) VALUES (?,?,?,?,?,?)", real_estate)

    # 6. 대출 (Loans)
    loans = [
        ('디딤돌 대출', '우리은행', 250000000, 235000000, 850000, 2.5, '2022-05-10', '2052-05-10', '저금리 정부상품'),
        ('자동차 할부', '현대캐피탈', 20000000, 12000000, 450000, 5.8, '2023-01-15', '2026-01-15', '무출고 출고')
    ]
    c.executemany("""
        INSERT INTO loans (name, institution, principal, remaining, monthly_payment, interest_rate, loan_date, end_date, memo) 
        VALUES (?,?,?,?,?,?,?,?,?)
    """, loans)

    # 7. 연금 (Pension)
    pensions = [
        ('국민연금', '국민연금공단', '정기납부', 450000, 12500000, 0, '직장인 의무'),
        ('개인연금저축', '미래에셋증권', 'IRP', 300000, 4500000, 5.2, '세액공제용')
    ]
    c.executemany("INSERT INTO pension (pension_type, name, institution, monthly_payment, accumulated, return_rate, memo) VALUES (?,?,?,?,?,?,?)", pensions)

    # 8. 목표 (Goals)
    goals = [
        ('1억 모으기', 100000000, 65000000, 2000000, '2025-12-31', '종잣돈 만들기'),
        ('테슬라 모델3 구매', 60000000, 15000000, 1000000, '2026-06-01', '내 드림카')
    ]
    c.executemany("INSERT INTO goals (name, target_amount, current_amount, monthly_saving, target_date, memo) VALUES (?,?,?,?,?,?)", goals)

    conn.commit()
    conn.close()
    print("All categories filled with realistic data!")

if __name__ == '__main__':
    reset_and_fill_realistic()
