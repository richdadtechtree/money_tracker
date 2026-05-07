import sqlite3

DB_PATH = 'finance.db'

def insert_more_samples():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 1. 4월 수입 추가 (Income)
    incomes = [
        ('2024-04-20', '부수입', '당근마켓 판매', '중고 물품', 35000),
        ('2024-04-25', '기타', '세금 환급금', '연말정산', 220000)
    ]
    c.executemany("INSERT INTO income (date, category, name, memo, amount) VALUES (?,?,?,?,?)", incomes)

    # 2. 4월 지출 추가 (Budget/Expenses)
    expenses = [
        ('2024-04-10', '교통', '주유비', 'SK에너지', '카드', 75000, '가득 채움'),
        ('2024-04-12', '의료', '약국', '영양제', '카드', 45000, '비타민 구매'),
        ('2024-04-18', '문화', '영화 관람', 'CGV', '카드', 28000, '팝콘 포함'),
        ('2024-04-22', '식비', '마트 장보기', '이마트', '카드', 125000, '일주일치 식량')
    ]
    c.executemany("INSERT INTO budget (date, category, name, type, payment_method, amount, memo) VALUES (?,?,?,?,?,?,?)", expenses)

    # 3. 대출 정보 추가 (Loans)
    loans = [
        ('전세자금대출', '신한은행', 200000000, 185000000, 650000, 3.8, '2022-05-10', '2024-05-10', '안심전세'),
        ('신용대출', '카카오뱅크', 30000000, 25000000, 450000, 5.2, '2023-11-15', '2025-11-15', '마이너스 통장 대용')
    ]
    c.executemany("""
        INSERT INTO loans (name, institution, principal, remaining, monthly_payment, interest_rate, loan_date, end_date, memo) 
        VALUES (?,?,?,?,?,?,?,?,?)
    """, loans)

    conn.commit()
    conn.close()
    print("Additional April data and Loans inserted successfully!")

if __name__ == '__main__':
    insert_more_samples()
