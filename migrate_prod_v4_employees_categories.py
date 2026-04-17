"""
Migration v4 – April 2026
Adds:
  1. 'employee' table (new)
  2. 'expense_category' table (new)
  3. 'employee_id' column on expense table
  4. Seeds 'expense_category' table with initial categories

Safe to run multiple times – skips anything that already exists.

Usage (on production):
    python3 migrate_prod_v4_employees_categories.py
"""

import os, shutil
from datetime import datetime
from sqlalchemy import text
from app import create_app, db, ExpenseCategory, EXPENSE_CATEGORIES


def run_migration():
    print("🚀  Starting Production Migration v4 ...")

    app = create_app()
    with app.app_context():

        # ── 1. Backup ────────────────────────────────────────────────
        db_path = "instance/hcl_sales.db"
        if os.path.exists(db_path):
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = f"instance/hcl_sales_backup_v4_{stamp}.db"
            shutil.copy(db_path, backup)
            print(f"✅  Backup created → {backup}")
        else:
            print("⚠️  DB file not found at instance/hcl_sales.db – skipping backup")

        # ── 2. Create any new tables (employee, expense_category) ────
        db.create_all()
        print("✅  db.create_all() done – new tables created if missing")

        # ── 3. Add employee_id to expense ────────────────────────────
        try:
            db.session.execute(
                text("ALTER TABLE expense ADD COLUMN employee_id INTEGER REFERENCES employee(id)")
            )
            db.session.commit()
            print("✅  Column added: expense.employee_id")
        except Exception as e:
            db.session.rollback()
            if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                print("ℹ️   expense.employee_id already exists – skipped")
            else:
                print(f"ℹ️   expense.employee_id error: {e}")

        # ── 4. Seed ExpenseCategory if empty ─────────────────────────
        if ExpenseCategory.query.count() == 0:
            print("🌱  Seeding ExpenseCategory table...")
            for cat_name in EXPENSE_CATEGORIES:
                db.session.add(ExpenseCategory(name=cat_name))
            db.session.commit()
            print("✅  ExpenseCategory table seeded.")
        else:
            print("ℹ️   ExpenseCategory table already contains data – skipped seeding")

    print("\n🎉  Migration v4 complete! Restart your app now.")


if __name__ == "__main__":
    run_migration()
