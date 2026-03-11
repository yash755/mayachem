import os
import shutil
import sqlite3
from datetime import datetime
import time

# Configuration
DB_PATH = "instance/hcl_sales.db"
BACKUP_DIR = "backups"
RETENTION_DAYS = 7

def backup_database():
    # 1. Ensure backup directory exists
    if not os.path.exists(BACKUP_DIR):
        print(f"Creating backup directory: {BACKUP_DIR}")
        os.makedirs(BACKUP_DIR)

    # 2. Generate timestamped filename
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_filename = f"backup_{timestamp}.db"
    backup_path = os.path.join(BACKUP_DIR, backup_filename)

    print(f"Starting backup of {DB_PATH} to {backup_path}...")

    # 3. Perform the backup
    try:
        if not os.path.exists(DB_PATH):
            print(f"Error: Database file not found at {DB_PATH}")
            return

        # Use sqlite3's online backup functionality for safety
        with sqlite3.connect(DB_PATH) as src_conn:
            with sqlite3.connect(backup_path) as dst_conn:
                src_conn.backup(dst_conn)
        
        print(f"Backup completed successfully: {backup_path}")
    except Exception as e:
        print(f"Error during backup: {e}")
        return

    # 4. Cleanup old backups (Retention)
    cleanup_old_backups()

def cleanup_old_backups():
    print(f"Cleaning up backups older than {RETENTION_DAYS} days...")
    now = time.time()
    retention_seconds = RETENTION_DAYS * 86400

    try:
        files = os.listdir(BACKUP_DIR)
        for file in files:
            if not file.startswith("backup_") or not file.endswith(".db"):
                continue
            
            file_path = os.path.join(BACKUP_DIR, file)
            # check if it's a file
            if os.path.isfile(file_path):
                file_age = os.path.getmtime(file_path)
                if now - file_age > retention_seconds:
                    print(f"Deleting old backup: {file}")
                    os.remove(file_path)
    except Exception as e:
        print(f"Error during cleanup: {e}")

if __name__ == "__main__":
    backup_database()
