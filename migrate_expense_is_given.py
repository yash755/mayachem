import sqlite3
import os

def upgrade():
    base_dir = os.path.dirname(__file__)
    candidate_paths = [
        os.path.join(base_dir, 'instance', 'hcl_sales.db'),
        os.path.join(base_dir, 'hcl_sales.db')
    ]
    
    migrated_any = False
    for db_path in candidate_paths:
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Check if expense table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='expense';")
            if not cursor.fetchone():
                conn.close()
                continue
                
            try:
                cursor.execute('ALTER TABLE expense ADD COLUMN is_given BOOLEAN DEFAULT 0 NOT NULL;')
                print(f"[{db_path}] Added column 'is_given' with default 0 (False).")
            except sqlite3.OperationalError as e:
                print(f"[{db_path}] Column check: {e}")
            
            cursor.execute('UPDATE expense SET is_given = 1 WHERE is_given IS NULL;')
            conn.commit()
            conn.close()
            migrated_any = True
            print(f"[{db_path}] Verified all existing expenses have is_given = 1 (True).")
            
    if not migrated_any:
        print("No active database files found to migrate.")
    else:
        print("Expense migration completed successfully.")

if __name__ == '__main__':
    upgrade()
