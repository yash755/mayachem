import sqlite3

def run():
    conn = sqlite3.connect('instance/hcl_sales.db')
    cursor = conn.cursor()
    try:
        cursor.execute("""
            CREATE TABLE recurring_expense (
                id INTEGER NOT NULL, 
                name VARCHAR(120) NOT NULL, 
                amount FLOAT NOT NULL, 
                PRIMARY KEY (id)
            )
        """)
    except Exception as e:
        print("Table recurring_expense creation failed (might exist):", e)

    conn.commit()
    print("Migration successful.")
    conn.close()

if __name__ == '__main__':
    run()
