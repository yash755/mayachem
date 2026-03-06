import os
from sqlalchemy import text
from app import create_app, db, Sale

def run_migration():
    print("🚀 Starting Production Migration...")
    
    app = create_app()
    with app.app_context():
        # 1. Back up the database first
        db_path = "instance/hcl_sales.db"
        backup_path = "instance/hcl_sales_prod_backup.db"
        if os.path.exists(db_path):
            import shutil
            shutil.copy(db_path, backup_path)
            print(f"✅ Backup created at {backup_path}")
        else:
            print("⚠️ Database file not found at instance/hcl_sales.db. Skipping backup.")

        # 2. Add missing columns to 'sale' table if they don't exist
        # We use a try-except block for each column because 'ADD COLUMN' might fail if it already exists
        columns_to_add = [
            "cgst_amount FLOAT DEFAULT 0.0",
            "sgst_amount FLOAT DEFAULT 0.0",
            "igst_amount FLOAT DEFAULT 0.0"
        ]
        
        for col_def in columns_to_add:
            try:
                col_name = col_def.split()[0]
                db.session.execute(text(f"ALTER TABLE sale ADD COLUMN {col_def};"))
                db.session.commit()
                print(f"✅ Column added: {col_name}")
            except Exception as e:
                db.session.rollback()
                if "duplicate column name" in str(e).lower():
                    print(f"ℹ️ Column already exists: {col_name}")
                else:
                    print(f"❌ Error adding column {col_name}: {e}")

        # 3. Recalculate Subtotal and Grand Total from Line Items
        try:
            print("📝 Recalculating settlement totals from line items...")
            sales = Sale.query.all()
            updated_count = 0
            for s in sales:
                # Use the model's total_sp() method to get the raw revenue
                raw_revenue = s.total_sp()
                
                # Update subtotal if it's missing or if we want to sync it
                s.subtotal = round(raw_revenue, 2)
                
                # Calculate Settlement (Grand Total) = Subtotal + GST
                gst_total = (s.cgst_amount or 0) + (s.sgst_amount or 0) + (s.igst_amount or 0)
                s.grand_total = round(s.subtotal + gst_total, 2)
                
                updated_count += 1
            
            db.session.commit()
            print(f"✅ Successfully recalculated {updated_count} sales records.")
        except Exception as e:
            db.session.rollback()
            print(f"❌ Error during recalculation: {e}")

    print("\n🎉 Migration Complete! You can now restart your application.")

if __name__ == "__main__":
    run_migration()
