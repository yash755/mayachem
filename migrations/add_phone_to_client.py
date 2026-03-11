import sqlite3
import os

def apply_migration():
    # Path to the database
    db_path = os.path.join('instance', 'hcl_sales.db')
    
    if not os.path.exists(db_path):
        print(f"Error: Database file not found at {db_path}")
        return

    # SQL command to add the column
    migration_sql = "ALTER TABLE client ADD COLUMN phone VARCHAR(20);"

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if column already exists to avoid errors on re-run
        cursor.execute("PRAGMA table_info(client)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'phone' in columns:
            print("Migration already applied: 'phone' column exists.")
        else:
            print(f"Applying migration to {db_path}...")
            cursor.execute(migration_sql)
            conn.commit()
            print("Migration successful: added 'phone' to 'client' table.")
            
        conn.close()
    except Exception as e:
        print(f"An error occurred during migration: {e}")

if __name__ == "__main__":
    apply_migration()
