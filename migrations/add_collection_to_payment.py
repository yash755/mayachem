import sqlite3
import os

def apply_migration():
    # Path to the database
    db_path = os.path.join('instance', 'hcl_sales.db')
    
    if not os.path.exists(db_path):
        print(f"Error: Database file not found at {db_path}")
        return

    # SQL command to add the column
    migration_sql = "ALTER TABLE sale_payment ADD COLUMN collection_id INTEGER REFERENCES client_collection(id);"

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if column already exists
        cursor.execute("PRAGMA table_info(sale_payment)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'collection_id' in columns:
            print("Migration already applied: 'collection_id' column exists.")
        else:
            print(f"Applying migration to {db_path}...")
            cursor.execute(migration_sql)
            conn.commit()
            print("Migration successful: added 'collection_id' to 'sale_payment' table.")
            
        conn.close()
    except Exception as e:
        print(f"An error occurred during migration: {e}")

if __name__ == "__main__":
    apply_migration()
