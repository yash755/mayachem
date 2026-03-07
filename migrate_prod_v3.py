"""
Migration v3 – March 2025
Adds:
  1. 'product' table  (new)
  2. 'product_id' column on sale_item
  3. 'product_id' column on purchase_item

Safe to run multiple times – skips anything that already exists.

Usage (on production):
    python3 migrate_prod_v3.py
"""

import os, shutil
from datetime import datetime
from sqlalchemy import text
from app import create_app, db


def run_migration():
    print("🚀  Starting Production Migration v3 ...")

    app = create_app()
    with app.app_context():

        # ── 1. Backup ────────────────────────────────────────────────
        db_path = "instance/hcl_sales.db"
        if os.path.exists(db_path):
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = f"instance/hcl_sales_backup_v3_{stamp}.db"
            shutil.copy(db_path, backup)
            print(f"✅  Backup created → {backup}")
        else:
            print("⚠️  DB file not found at instance/hcl_sales.db – skipping backup")

        # ── 2. Create any new tables (e.g. 'product') ────────────────
        db.create_all()
        print("✅  db.create_all() done – new tables created if missing")

        # ── 3. Add product_id to sale_item ────────────────────────────
        try:
            db.session.execute(
                text("ALTER TABLE sale_item ADD COLUMN product_id INTEGER REFERENCES product(id)")
            )
            db.session.commit()
            print("✅  Column added: sale_item.product_id")
        except Exception as e:
            db.session.rollback()
            if "duplicate column" in str(e).lower():
                print("ℹ️   sale_item.product_id already exists – skipped")
            else:
                print(f"ℹ️   sale_item.product_id: {e}")

        # ── 4. Add product_id to purchase_item ────────────────────────
        try:
            db.session.execute(
                text("ALTER TABLE purchase_item ADD COLUMN product_id INTEGER REFERENCES product(id)")
            )
            db.session.commit()
            print("✅  Column added: purchase_item.product_id")
        except Exception as e:
            db.session.rollback()
            if "duplicate column" in str(e).lower():
                print("ℹ️   purchase_item.product_id already exists – skipped")
            else:
                print(f"ℹ️   purchase_item.product_id: {e}")

    print("\n🎉  Migration v3 complete! Restart your app now.")


if __name__ == "__main__":
    run_migration()
