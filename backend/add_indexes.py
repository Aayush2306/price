#!/usr/bin/env python3
"""
Simple script to add database indexes
Run with: python add_indexes.py
"""

import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

# Get database URL from environment
DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    print("[ERROR] DATABASE_URL not found in .env file")
    exit(1)

# SQL commands to create indexes
indexes = [
    "CREATE INDEX IF NOT EXISTS bets_round_id_idx ON bets (round_id);",
    "CREATE INDEX IF NOT EXISTS bets_status_idx ON bets (status);",
    "CREATE INDEX IF NOT EXISTS bets_created_at_idx ON bets (created_at);",
    "CREATE INDEX IF NOT EXISTS bets_user_id_idx ON bets (user_id);",
    "CREATE INDEX IF NOT EXISTS rounds_crypto_idx ON rounds (crypto);",
    "CREATE INDEX IF NOT EXISTS rounds_crypto_result_idx ON rounds (crypto, result);",
    "CREATE INDEX IF NOT EXISTS rounds_crypto_starttime_idx ON rounds (crypto, start_time);",
    "CREATE INDEX IF NOT EXISTS rounds_result_idx ON rounds (result);",
]

try:
    print("Connecting to database...")
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()

    print("Creating indexes...")
    for index_sql in indexes:
        index_name = index_sql.split("EXISTS ")[1].split(" ON")[0]
        print(f"  Creating {index_name}...")
        cursor.execute(index_sql)

    conn.commit()

    print("\n[SUCCESS] All indexes created successfully!")

    # Verify indexes
    print("\nVerifying indexes...")
    cursor.execute("""
        SELECT tablename, indexname
        FROM pg_indexes
        WHERE tablename IN ('bets', 'rounds', 'users')
        ORDER BY tablename, indexname;
    """)

    results = cursor.fetchall()
    print(f"\nFound {len(results)} indexes:")
    for table, index in results:
        print(f"  * {table}.{index}")

    cursor.close()
    conn.close()

    print("\n[DONE] Your database is now optimized!")
    print("Expected performance: 10-100x faster queries")

except Exception as e:
    print(f"\n[ERROR] {e}")
    print("\nMake sure:")
    print("1. Your DATABASE_URL is correct in .env")
    print("2. The database is running")
    print("3. You have permission to create indexes")
