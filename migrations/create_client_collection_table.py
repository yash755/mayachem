import sqlite3
import os

def apply_migration():
    # Path to the database
    db_path = os.path.join('instance', 'hcl_sales.db')
    
    if not os.path.exists(db_path):
        print(f"Error: Database file not found at {db_path}")
        return

    # SQL command to create the table
    migration_sql = """
    CREATE TABLE IF NOT EXISTS client_collection (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER NOT NULL,
        date DATE NOT NULL,
        amount FLOAT NOT NULL,
        mode VARCHAR(50),
        notes VARCHAR(250),
        FOREIGN KEY (client_id) REFERENCES client (id)
    );
    """

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        print(f"Applying migration to {db_path}...")
        cursor.execute(migration_sql)
        conn.commit()
        print("Migration successful: 'client_collection' table created.")
            
        conn.close()
    except Exception as e:
        print(f"An error occurred during migration: {e}")

if __name__ == "__main__":
    apply_migration()
