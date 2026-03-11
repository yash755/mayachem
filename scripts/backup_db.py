import os
import shutil
import sqlite3
import subprocess
from datetime import datetime
import time

# Configuration
DB_PATH = "instance/hcl_sales.db"
BACKUP_DIR = "backups_repo" # Local folder for the cloned backup repo
# The user should set this environment variable on the server
REPO_URL = os.environ.get("BACKUP_REPO_URL") 
RETENTION_DAYS = 30 # Can keep more in Git as it's efficient

def run_command(command, cwd=None):
    try:
        result = subprocess.run(command, cwd=cwd, check=True, capture_output=True, text=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Command failed: {' '.join(command)}")
        print(f"Error: {e.stderr}")
        return None

def setup_git_repo():
    if not REPO_URL:
        print("Error: BACKUP_REPO_URL environment variable not set.")
        return False

    if not os.path.exists(BACKUP_DIR):
        print(f"Cloning backup repository from {REPO_URL}...")
        if run_command(["git", "clone", REPO_URL, BACKUP_DIR]) is None:
            return False
    else:
        print("Updating local backup repository...")
        # Ignore pull errors (e.g., if the remote is empty/new)
        subprocess.run(["git", "pull"], cwd=BACKUP_DIR, capture_output=True)
    return True

def backup_database():
    if not setup_git_repo():
        return

    # 1. Generate timestamped filename
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_filename = f"backup_{timestamp}.db"
    backup_path = os.path.join(BACKUP_DIR, backup_filename)

    print(f"Starting backup of {DB_PATH} to Git repo...")

    # 2. Perform the backup
    try:
        if not os.path.exists(DB_PATH):
            print(f"Error: Database file not found at {DB_PATH}")
            return

        with sqlite3.connect(DB_PATH) as src_conn:
            with sqlite3.connect(backup_path) as dst_conn:
                src_conn.backup(dst_conn)
        
        print(f"Backup created locally: {backup_path}")
    except Exception as e:
        print(f"Error during backup: {e}")
        return

    # 3. Git operations
    print("Pushing backup to remote repository...")
    run_command(["git", "add", backup_filename], cwd=BACKUP_DIR)
    run_command(["git", "commit", "-m", f"Database backup {timestamp}"], cwd=BACKUP_DIR)
    if run_command(["git", "push"], cwd=BACKUP_DIR) is not None:
        print("Backup successfully pushed to Git!")

    # 4. Cleanup old backups locally (Git history remains)
    cleanup_old_backups()

def cleanup_old_backups():
    # We still keep a few local copies in the repo folder for quick access
    # But Git itself stores the full history.
    print(f"Running local cleanup in {BACKUP_DIR}...")
    now = time.time()
    retention_seconds = RETENTION_DAYS * 86400

    try:
        files = os.listdir(BACKUP_DIR)
        for file in files:
            if not file.startswith("backup_") or not file.endswith(".db"):
                continue
            
            file_path = os.path.join(BACKUP_DIR, file)
            if os.path.isfile(file_path):
                file_age = os.path.getmtime(file_path)
                if now - file_age > retention_seconds:
                    print(f"Removing old backup from local tracking: {file}")
                    run_command(["git", "rm", file], cwd=BACKUP_DIR)
                    run_command(["git", "commit", "-m", f"Cleanup old backup {file}"], cwd=BACKUP_DIR)
                    run_command(["git", "push"], cwd=BACKUP_DIR)
    except Exception as e:
        print(f"Error during cleanup: {e}")

if __name__ == "__main__":
    backup_database()
