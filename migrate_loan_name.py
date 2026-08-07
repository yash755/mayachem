import sqlite3

def run():
    conn = sqlite3.connect('instance/hcl_sales.db')
    cursor = conn.cursor()
    try:
        cursor.execute("ALTER TABLE loan ADD COLUMN loan_name VARCHAR(200)")
    except Exception as e:
        print("Loan name add failed (might exist):", e)
        
    try:
        cursor.execute("ALTER TABLE expense ADD COLUMN loan_id INTEGER REFERENCES loan(id)")
    except Exception as e:
        print("Expense loan_id add failed:", e)

    conn.commit()
    print("Migration successful.")
    conn.close()

if __name__ == '__main__':
    run()
