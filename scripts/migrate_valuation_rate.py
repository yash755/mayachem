import os
from sqlalchemy import text
from app import create_app, db

def run_migration():
    print("🚀 Starting Database Migration for valuation_rate...")
    
    app = create_app()
    with app.app_context():
        # 1. Back up the database first
        db_path = "instance/hcl_sales.db"
        backup_path = "instance/hcl_sales_backup_valuation.db"
        if os.path.exists(db_path):
            import shutil
            shutil.copy(db_path, backup_path)
            print(f"✅ Backup created at {backup_path}")
        else:
            print("⚠️ Database file not found at instance/hcl_sales.db. Skipping backup.")

        # 2. Add valuation_rate column
        col_def = "valuation_rate FLOAT DEFAULT 0.0 NOT NULL"
        col_name = "valuation_rate"
        
        try:
            db.session.execute(text(f"ALTER TABLE product ADD COLUMN {col_def};"))
            db.session.commit()
            print(f"✅ Column added: {col_name}")
        except Exception as e:
            db.session.rollback()
            if "duplicate column name" in str(e).lower():
                print(f"ℹ️ Column already exists: {col_name}")
            else:
                print(f"❌ Error adding column {col_name}: {e}")

    print("\n🎉 Migration Complete!")

if __name__ == "__main__":
    run_migration()
