import sqlite3
import os

def run_migration():
    print("Adding employee_id column to cash_ledger table...")
    for db_path in ["instance/hcl_sales.db", "hcl_sales.db"]:
        if not os.path.exists(db_path):
            continue
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("ALTER TABLE cash_ledger ADD COLUMN employee_id INTEGER REFERENCES employee(id);")
            conn.commit()
            conn.close()
            print(f"[{db_path}] Migration complete! employee_id column added successfully.")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                print(f"[{db_path}] Column employee_id already exists. Migration skipped.")
            else:
                print(f"[{db_path}] Error: {e}")

if __name__ == "__main__":
    run_migration()
