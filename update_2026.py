

import sqlite3
from datetime import datetime

DB_PATH = 'finance.db'

def update_to_2026():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 기존 데이터 삭제
    tables = ['income', 'budget', 'card_tx']
    for table in tables:
        c.execute(f"DELETE FROM {table}")

    # 1. 2026년 4월 수입
    incomes = [
        ('2026-04-25', '급여', '4월 정기 급여', '실수령액', 5200000),
        ('2026-04-10', '부수입', '당근마켓 판매', '중고 노트북', 450000),
        ('2026-04-15', '이자/배당', '배당금 입금', '삼성전자', 42000)
    ]
    c.executemany("INSERT INTO income (date, category, name, memo, amount) VALUES (?,?,?,?,?)", incomes)

    # 2. 2026년 4월 지출
    expenses = [
        ('2026-04-01', '주거/통신', '월세/관리비', '정기 이체', '계좌이체', 950000, '숨만 쉬어도 나감'),
        ('2026-04-05', '식비', '이마트 장보기', '식재료', '카드', 185000, '장바구니 물가ㅠㅠ'),
        ('2026-04-12', '교통', '후불 교통비', '출퇴근', '카드', 135000, '대중교통'),
        ('2026-04-15', '쇼핑', '백화점 쇼핑', '선물 구매', '카드', 250000, '친구 생일'),
        ('2026-04-18', '의료', '약국', '영양제', '카드', 45000, '건강 챙기기'),
        ('2026-04-20', '식비', '외식/배달', '주말 식사', '카드', 85000, '가족 식사')
    ]





    
    c.executemany("INSERT INTO budget (date, category, name, type, payment_method, amount, memo) VALUES (?,?,?,?,?,?,?)", expenses)

    conn.commit()
    conn.close()
    print("Data updated to April 2026!")

if __name__ == '__main__':
    update_to_2026()
