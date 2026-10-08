import sqlite3

def run_migration():
    print("Adding expense_id column to cash_ledger table...")
    try:
        conn = sqlite3.connect("instance/hcl_sales.db")
        cursor = conn.cursor()
        cursor.execute("ALTER TABLE cash_ledger ADD COLUMN expense_id INTEGER REFERENCES expense(id);")
        conn.commit()
        conn.close()
        print("Migration complete! Column added successfully.")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e):
            print("Column already exists. Migration skipped.")
        else:
            print(f"Error: {e}")

if __name__ == "__main__":
    run_migration()
