import sqlite3

def run():
    conn = sqlite3.connect('instance/hcl_sales.db')
    cursor = conn.cursor()
    try:
        cursor.execute("ALTER TABLE loan ADD COLUMN payment_frequency VARCHAR(20) NOT NULL DEFAULT 'one_time'")
        cursor.execute("ALTER TABLE loan ADD COLUMN total_emi INTEGER DEFAULT 0")
        conn.commit()
        print("Migration successful.")
    except Exception as e:
        print("Migration failed:", e)
    finally:
        conn.close()

if __name__ == '__main__':
    run()
