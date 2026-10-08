from app import create_app, db
import os

def run_migration():
    print("Initializing Flask App...")
    app = create_app()
    with app.app_context():
        print("Creating new tables (CreditCardExpense, SmsIngestLog) if they don't exist...")
        db.create_all()
        print("Migration complete! Database is ready.")

if __name__ == "__main__":
    run_migration()
