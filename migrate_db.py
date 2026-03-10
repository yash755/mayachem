import sqlite3
import os

# This script migrates the database to support per-row GST.
# It adds the 'gst_percent' column to 'sale_item' and copies
# existing global GST data from 'sale' to individual items.

db_path = "instance/hcl_sales.db" 

if not os.path.exists(db_path):
    print(f"Error: {db_path} not found. Please ensure the path is correct.")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    print("Starting migration...")
    # 1. Add gst_percent column to sale_item table
    try:
        cursor.execute("ALTER TABLE sale_item ADD COLUMN gst_percent REAL NOT NULL DEFAULT 0.0")
        print("Column 'gst_percent' added to 'sale_item' table.")
    except sqlite3.OperationalError:
        print("Note: Column 'gst_percent' already exists in 'sale_item'.")

    # 2. Data Migration: Copy global gst_percent from 'sale' to 'sale_item' rows
    print("Migrating existing GST data from 'sale' to 'sale_item'...")
    cursor.execute("""
        UPDATE sale_item 
        SET gst_percent = (
            SELECT gst_percent 
            FROM sale 
            WHERE sale.id = sale_item.sale_id
        )
        WHERE gst_percent = 0.0 OR gst_percent IS NULL
    """)
    conn.commit()
    print(f"Data migration complete. Updated existing records.")

except Exception as e:
    print(f"Error during migration: {e}")
    conn.rollback()
finally:
    conn.close()
    print("Migration finished.")
