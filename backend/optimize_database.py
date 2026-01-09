"""
Production Optimization Script for PredictGram Database
Adds indexes and optimizations for better performance
"""

import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

def optimize_database():
    """Add indexes and optimizations to database"""
    conn = psycopg2.connect(os.environ['DATABASE_URL'])
    cursor = conn.cursor()

    print("Starting database optimization...")

    try:
        # ========== ROUNDS TABLE ==========
        print("\n[1/15] Adding index on rounds(crypto, start_time)...")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_rounds_crypto_start
            ON rounds(crypto, start_time DESC);
        """)

        print("[2/15] Adding index on rounds(result)...")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_rounds_result
            ON rounds(result) WHERE result IS NOT NULL;
        """)

        print("[3/15] Adding index on rounds(end_time)...")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_rounds_end_time
            ON rounds(end_time);
        """)

        # ========== BETS TABLE ==========
        print("[4/15] Adding index on bets(user_id, status)...")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_bets_user_status
            ON bets(user_id, status);
        """)

        print("[5/15] Adding index on bets(round_id)...")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_bets_round
            ON bets(round_id);
        """)

        print("[6/15] Adding index on bets(created_at)...")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_bets_created
            ON bets(created_at DESC);
        """)

        # Add created_at column if missing
        print("[7/15] Adding bets.created_at column if missing...")
        cursor.execute("""
            ALTER TABLE bets
            ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();
        """)

        # Add profit column if missing
        print("[8/15] Adding bets.profit column if missing...")
        cursor.execute("""
            ALTER TABLE bets
            ADD COLUMN IF NOT EXISTS profit INTEGER DEFAULT 0;
        """)

        # ========== CUSTOM_BET_ROUNDS TABLE ==========
        print("[9/15] Adding index on custom_bet_rounds(status, end_time)...")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_custom_rounds_status_end
            ON custom_bet_rounds(status, end_time);
        """)

        print("[10/15] Adding index on custom_bet_rounds(token_ca, status)...")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_custom_rounds_token_status
            ON custom_bet_rounds(token_ca, status);
        """)

        print("[11/15] Adding index on custom_bet_rounds(creator_id)...")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_custom_rounds_creator
            ON custom_bet_rounds(creator_id);
        """)

        # ========== CUSTOM_BETS TABLE ==========
        print("[12/15] Adding index on custom_bets(user_id, status)...")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_custom_bets_user_status
            ON custom_bets(user_id, status);
        """)

        print("[13/15] Adding index on custom_bets(round_id)...")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_custom_bets_round
            ON custom_bets(round_id);
        """)

        # ========== ONCHAIN_ROUNDS TABLE ==========
        print("[14/15] Adding index on onchain_rounds(category, end_time)...")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_onchain_rounds_category_end
            ON onchain_rounds(category, end_time);
        """)

        print("[14b/15] Adding index on onchain_rounds(result)...")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_onchain_rounds_result
            ON onchain_rounds(result) WHERE result IS NOT NULL;
        """)

        # ========== ONCHAIN_BETS TABLE ==========
        print("[15/15] Adding index on onchain_bets(user_id, round_id)...")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_onchain_bets_user_round
            ON onchain_bets(user_id, round_id);
        """)

        # Commit all changes
        conn.commit()
        print("\n✅ Database optimization complete!")
        print("\nIndexes added:")
        print("  - rounds: crypto+start_time, result, end_time")
        print("  - bets: user_id+status, round_id, created_at")
        print("  - custom_bet_rounds: status+end_time, token_ca+status, creator_id")
        print("  - custom_bets: user_id+status, round_id")
        print("  - onchain_rounds: category+end_time, result")
        print("  - onchain_bets: user_id+round_id")

    except Exception as e:
        conn.rollback()
        print(f"\n❌ Error during optimization: {e}")
        raise
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    optimize_database()
