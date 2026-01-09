"""
Clear all data from database tables before deployment
Keeps table structure intact, only removes data
"""
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
import os

load_dotenv()

def clear_database():
    """Clear all data from all tables"""
    conn = psycopg2.connect(os.environ['DATABASE_URL'])
    cursor = conn.cursor()

    print("🗑️  Clearing database...")

    try:
        # Delete in correct order to respect foreign key constraints
        # Child tables first, parent tables last

        print("Deleting custom_bets...")
        cursor.execute("DELETE FROM custom_bets;")
        count = cursor.rowcount
        print(f"✅ Deleted {count} rows from custom_bets")

        print("Deleting custom_bet_rounds...")
        cursor.execute("DELETE FROM custom_bet_rounds;")
        count = cursor.rowcount
        print(f"✅ Deleted {count} rows from custom_bet_rounds")

        print("Deleting onchain_bets...")
        cursor.execute("DELETE FROM onchain_bets;")
        count = cursor.rowcount
        print(f"✅ Deleted {count} rows from onchain_bets")

        print("Deleting onchain_rounds...")
        cursor.execute("DELETE FROM onchain_rounds;")
        count = cursor.rowcount
        print(f"✅ Deleted {count} rows from onchain_rounds")

        print("Deleting bets...")
        cursor.execute("DELETE FROM bets;")
        count = cursor.rowcount
        print(f"✅ Deleted {count} rows from bets")

        print("Deleting rounds...")
        cursor.execute("DELETE FROM rounds;")
        count = cursor.rowcount
        print(f"✅ Deleted {count} rows from rounds")

        print("Deleting users...")
        cursor.execute("DELETE FROM users;")
        count = cursor.rowcount
        print(f"✅ Deleted {count} rows from users")

        conn.commit()
        print("\n✅ Database cleared successfully!")
        print("📊 All tables are now empty but structure is preserved")
        print("🚀 Ready for production deployment!")

    except Exception as e:
        print(f"❌ Error: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    response = input("⚠️  This will DELETE ALL DATA from your database. Are you sure? (yes/no): ")
    if response.lower() == 'yes':
        clear_database()
    else:
        print("❌ Cancelled")
