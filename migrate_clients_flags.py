import sqlite3

def upgrade():
    conn = sqlite3.connect('/Users/yash/Desktop/mayachem/instance/hcl_sales.db')
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
