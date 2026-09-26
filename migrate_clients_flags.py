import sqlite3
import os

def upgrade():
    db_path = os.path.join(os.path.dirname(__file__), 'instance', 'hcl_sales.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute('ALTER TABLE client ADD COLUMN is_client BOOLEAN DEFAULT 1 NOT NULL;')
    except sqlite3.OperationalError:
        pass # column exists
    try:
        cursor.execute('ALTER TABLE client ADD COLUMN is_vendor BOOLEAN DEFAULT 0 NOT NULL;')
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute('ALTER TABLE client ADD COLUMN is_active BOOLEAN DEFAULT 1 NOT NULL;')
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute('ALTER TABLE client ADD COLUMN is_other BOOLEAN DEFAULT 0 NOT NULL;')
    except sqlite3.OperationalError:
        pass
        
    conn.commit()
    conn.close()
    print("Clients migration completed.")

if __name__ == '__main__':
    upgrade()
