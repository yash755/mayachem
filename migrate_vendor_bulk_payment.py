import os
import shutil
from sqlalchemy import text
from app import create_app, db


def run_migration():
    print("🚀 Starting Migration: Vendor Bulk Payment (VendorCollection)...")

    app = create_app()
    with app.app_context():
        # 1. Backup the database
        db_path = "instance/hcl_sales.db"
        backup_path = "instance/hcl_sales_before_vendor_collection.db"
        if os.path.exists(db_path):
            shutil.copy(db_path, backup_path)
            print(f"✅ Backup created at {backup_path}")
        else:
            print("⚠️  DB not found at instance/hcl_sales.db — skipping backup.")

        # 2. Create the new vendor_collection table (safe if already exists via db.create_all)
        try:
            db.create_all()
            print("✅ vendor_collection table created (or already exists).")
        except Exception as e:
            print(f"❌ Error running db.create_all(): {e}")

        # 3. Add collection_id to purchase_payment if missing
        column_defs = [
            ("purchase_payment", "collection_id", "INTEGER REFERENCES vendor_collection(id)"),
        ]

        for table, col_name, col_type in column_defs:
            try:
                db.session.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type};")
                )
                db.session.commit()
                print(f"✅ Added column: {table}.{col_name}")
            except Exception as e:
                db.session.rollback()
                if "duplicate column name" in str(e).lower():
                    print(f"ℹ️  Column already exists: {table}.{col_name}")
                else:
                    print(f"❌ Error adding {table}.{col_name}: {e}")

    print("\n🎉 Migration complete! Restart the application to apply changes.")


if __name__ == "__main__":
    run_migration()
