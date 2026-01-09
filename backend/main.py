import eventlet
eventlet.monkey_patch()
from flask import Flask, request, jsonify
from flask_cors import CORS
import uuid
from flask_socketio import SocketIO, emit
import threading
import time
import requests
import psycopg2
import psycopg2.extras
import psycopg2.pool
import os
import datetime
import random
from datetime import datetime, timedelta
import pytz
import schedule
from flask_session import Session
from flask import session
from flask import send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix
import redis
from dotenv import load_dotenv
load_dotenv()
from psycopg2.pool import ThreadedConnectionPool
from contextlib import contextmanager
from flask_socketio import join_room
from flask_socketio import leave_room
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import base58
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError
import json
from validation import (
    validate_bet_amount,
    validate_direction,
    validate_crypto_symbol,
    validate_stock_symbol,
    validate_solana_address,
    validate_duration,
    validate_onchain_category
)

app = Flask(__name__)

# CORS configuration - use environment variable for production
ALLOWED_ORIGINS = os.environ.get('ALLOWED_ORIGINS', '*').split(',')
socketio = SocketIO(app, cors_allowed_origins=ALLOWED_ORIGINS)

app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
redis_url = os.environ.get('REDIS_URL')
redis_disabled = os.environ.get('REDIS_DISABLE') == '1'
if redis_url and not redis_disabled:
    try:
        redis_client = redis.from_url(redis_url)
        redis_client.ping()
        app.config['SESSION_TYPE'] = 'redis'
        app.config['SESSION_REDIS'] = redis_client
    except Exception as exc:
        print(f"⚠️ Redis unavailable, falling back to filesystem sessions: {exc}")
        app.config['SESSION_TYPE'] = 'filesystem'
else:
    app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_COOKIE_NAME'] = 'bet_session'
app.config['SESSION_PERMANENT'] = False
app.config['SESSION_USE_SIGNER'] = True
app.config['SESSION_KEY_PREFIX'] = 'sess:'
app.config['SESSION_COOKIE_SAMESITE'] = os.environ.get("SESSION_COOKIE_SAMESITE", "Lax")
app.config['SESSION_COOKIE_SECURE'] = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
app.config['SESSION_COOKIE_HTTPONLY'] = True



app.config['SECRET_KEY'] = os.environ['SECRET_KEY']  # You can change this

Session(app)
CORS(app, resources={r"/*": {"origins": ALLOWED_ORIGINS}}, supports_credentials=True)

# Symbol to CoinGecko ID mapping
CRYPTO_MAP = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "MATIC": "polygon",
    "XRP": "ripple",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "DOT": "polkadot",
    "AVAX": "avalanche-2"
}

STOCK_MAP = {
    "AAPL": "Apple Inc.",
    "GOOGL": "Google Inc.",
    "AMZN": "Amazon.com Inc.",
    "MSFT": "Microsoft Corp.",
    "TSLA": "Tesla Inc.",
    "META": "Meta Platforms Inc.",
    "NVDA": "NVIDIA Corp.",
    "NFLX": "Netflix Inc.",
}

CG_API_KEY = os.environ['CG_API_KEY']


# DB Pool
pool = ThreadedConnectionPool(
    1,
    80,
    os.environ['DATABASE_URL'],
    cursor_factory=psycopg2.extras.RealDictCursor
)

@contextmanager
def get_db_cursor(real_dict=False):
    conn = pool.getconn()
    try:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor if real_dict else None)
        yield cursor, conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        pool.putconn(conn)



def get_conn():
    return pool.getconn()


def release_conn(conn):
    pool.putconn(conn)


def release_db_connection(conn):
    pool.putconn(conn)


def ensure_user_schema():
    with get_db_cursor() as (cursor, _):
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT,
                username TEXT,
                joined_at TIMESTAMP DEFAULT NOW(),
                credits INTEGER DEFAULT 1000
            );
        """)
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS name TEXT")
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS username TEXT")
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS joined_at TIMESTAMP DEFAULT NOW()")
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS credits INTEGER DEFAULT 1000")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_username_lower_idx ON users (LOWER(username))")


def init_db():
    ensure_user_schema()
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rounds (
            id SERIAL PRIMARY KEY,
            crypto TEXT,
            start_price REAL,
            end_price REAL,
            start_time INTEGER,
            end_time INTEGER,
            result TEXT DEFAULT NULL
        );
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bets (
            id SERIAL PRIMARY KEY,
            user_id TEXT,
            round_id INTEGER,
            crypto TEXT,
            direction TEXT,
            amount INTEGER,
            status TEXT DEFAULT 'pending'
        );
    ''')
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS bets_user_round_idx ON bets (user_id, round_id)")

    # On-chain prediction tables
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS onchain_rounds (
            id SERIAL PRIMARY KEY,
            category TEXT,
            start_value REAL,
            end_value REAL,
            reference_value REAL,
            start_time INTEGER,
            end_time INTEGER,
            result TEXT DEFAULT NULL,
            metadata JSONB
        );
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS onchain_bets (
            id SERIAL PRIMARY KEY,
            user_id TEXT,
            round_id INTEGER,
            category TEXT,
            prediction TEXT,
            amount INTEGER,
            status TEXT DEFAULT 'pending',
            profit INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW()
        );
    ''')
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS onchain_bets_user_round_idx ON onchain_bets (user_id, round_id)")

    # Custom bet tables
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS custom_bet_rounds (
            id SERIAL PRIMARY KEY,
            creator_id TEXT NOT NULL,
            token_ca TEXT NOT NULL,
            token_name TEXT,
            token_symbol TEXT,
            start_price REAL,
            end_price REAL,
            start_mcap REAL,
            duration_minutes INTEGER,
            start_time INTEGER,
            end_time INTEGER,
            result TEXT DEFAULT NULL,
            total_pool INTEGER DEFAULT 0,
            creator_earnings INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT NOW()
        );
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS custom_bets (
            id SERIAL PRIMARY KEY,
            user_id TEXT NOT NULL,
            round_id INTEGER NOT NULL,
            prediction TEXT NOT NULL,
            amount INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            profit INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW()
        );
    ''')
    cursor.execute("CREATE INDEX IF NOT EXISTS custom_bets_round_idx ON custom_bets (round_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS custom_bet_rounds_status_idx ON custom_bet_rounds (status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS custom_bet_rounds_token_ca_idx ON custom_bet_rounds (token_ca, status)")

    conn.commit()
    cursor.close()
    release_conn(conn)


def reset_and_init_db():
    conn = get_conn()
    cursor = conn.cursor()

    # 🚨 WARNING: This will delete all user, round, and bet data!
    cursor.execute("DROP TABLE IF EXISTS bets")
    cursor.execute("DROP TABLE IF EXISTS rounds")
    cursor.execute("DROP TABLE IF EXISTS users")

    # 👤 Users table with extra fields
    cursor.execute("""
        CREATE TABLE users (
            id TEXT PRIMARY KEY,
            name TEXT,
            username TEXT UNIQUE,
            joined_at TIMESTAMP DEFAULT NOW(),
            credits INTEGER DEFAULT 1000
        );
    """)
    cursor.execute("CREATE UNIQUE INDEX users_username_lower_idx ON users (LOWER(username))")

    # 🔁 Rounds table
    cursor.execute("""
        CREATE TABLE rounds (
            id SERIAL PRIMARY KEY,
            crypto TEXT,
            start_price REAL,
            end_price REAL,
            start_time INTEGER,
            end_time INTEGER,
            result TEXT DEFAULT NULL
        );
    """)

    # 💰 Bets table with created_at and profit field
    cursor.execute("""
        CREATE TABLE bets (
            id SERIAL PRIMARY KEY,
            user_id TEXT,
            round_id INTEGER,
            crypto TEXT,
            direction TEXT,
            amount INTEGER,
            status TEXT DEFAULT 'pending',
            profit INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS bets_user_round_idx ON bets (user_id, round_id)")

    conn.commit()
    cursor.close()
    release_conn(conn)
    print("✅ Database reset and initialized with updated schema.")


def reset_users_table():
    conn = get_conn()
    cursor = conn.cursor()

    # Drop old table if exists
    cursor.execute("DROP TABLE IF EXISTS users")

    # Recreate with new schema
    cursor.execute("""
        CREATE TABLE users (
            id TEXT PRIMARY KEY,
            name TEXT,
            username TEXT UNIQUE,
            joined_at TIMESTAMP DEFAULT NOW(),
            credits INTEGER DEFAULT 1000
        )
    """)
    cursor.execute("CREATE UNIQUE INDEX users_username_lower_idx ON users (LOWER(username))")
    conn.commit()
    cursor.close()
    release_conn(conn)
    print("✅ users table reset successfully.")





@app.route("/api/user", methods=["GET", "POST"])
def create_or_get_user():
    with get_db_cursor() as (cursor, conn):

        # 🔹 GET = return session-based user info (used after login or refresh)
        if request.method == "GET":
            if 'user' not in session:
                return jsonify({"error": "Not logged in"}), 401

            user_id = session['user']['user_id']
            cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
            return jsonify(user)

        # 🔸 POST = used only for legacy manual creation
        data = request.json
        user_id = data.get("user_id")
        name = data.get("name", "Guest")
        username = data.get("username")

        if username:
            cursor.execute(
                "SELECT id FROM users WHERE LOWER(username) = LOWER(%s) AND id <> %s",
                (username, user_id)
            )
            if cursor.fetchone():
                return jsonify({"error": "Username already taken"}), 409

        cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()

        if not user:
            cursor.execute(
                """
                INSERT INTO users (id, name, username, joined_at, credits)
                VALUES (%s, %s, %s, NOW(), %s)
                """, (user_id, name, username, 1000))
            cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()

    return jsonify({
        "user_id": user["id"],
        "name": user.get("name"),
        "username": user.get("username"),
        "joined_at": user.get("joined_at"),
        "credits": user.get("credits")
    })

@app.route("/api/auth/phantom/nonce", methods=["POST"])
def phantom_nonce():
    data = request.json or {}
    wallet_address = data.get("wallet_address")

    if not wallet_address:
        return jsonify({"error": "Missing wallet_address"}), 400

    nonce = uuid.uuid4().hex
    session["phantom_nonce"] = nonce
    session["phantom_wallet"] = wallet_address

    message = f"PredictGram login\nWallet: {wallet_address}\nNonce: {nonce}"
    return jsonify({"message": message})


@app.route("/api/auth/phantom/verify", methods=["POST"])
def phantom_verify():
    data = request.json or {}
    wallet_address = data.get("wallet_address")
    signature_b64 = data.get("signature")
    name = data.get("name")
    username = data.get("username")

    session_wallet = session.get("phantom_wallet")
    nonce = session.get("phantom_nonce")

    if not wallet_address or not signature_b64:
        return jsonify({"error": "Missing wallet_address or signature"}), 400
    if not nonce or session_wallet != wallet_address:
        return jsonify({"error": "No active login session"}), 400

    message = f"PredictGram login\nWallet: {wallet_address}\nNonce: {nonce}"
    try:
        signature = base64.b64decode(signature_b64)
        pubkey_bytes = base58.b58decode(wallet_address)
        VerifyKey(pubkey_bytes).verify(message.encode("utf-8"), signature)
    except (ValueError, BadSignatureError):
        return jsonify({"error": "Invalid signature"}), 401

    with get_db_cursor(real_dict=True) as (cursor, conn):
        cursor.execute(
            "SELECT id, name, username, joined_at, credits FROM users WHERE id = %s",
            (wallet_address,))
        user = cursor.fetchone()

        if not user:
            if not name or not username:
                return jsonify({"error": "Name and username required"}), 400

            cursor.execute("SELECT id FROM users WHERE LOWER(username) = LOWER(%s)", (username,))
            existing = cursor.fetchone()
            if existing:
                return jsonify({"error": "Username already taken"}), 409

            cursor.execute(
                """
                INSERT INTO users (id, name, username, joined_at, credits)
                VALUES (%s, %s, %s, NOW(), %s)
                """,
                (wallet_address, name, username, 1000)
            )
            cursor.execute(
                "SELECT id, name, username, joined_at, credits FROM users WHERE id = %s",
                (wallet_address,))
            user = cursor.fetchone()

    session['user'] = {
        "user_id": user["id"],
        "name": user["name"],
        "username": user["username"],
        "joined_at": str(user["joined_at"].date()) if user.get("joined_at") else None
    }

    session.pop("phantom_nonce", None)
    session.pop("phantom_wallet", None)

    return jsonify(user)


@app.route("/api/profile")
def get_profile():
    if 'user' not in session:
        return jsonify({"error": "Not logged in"}), 401

    user_id = session['user']['user_id']

    with get_db_cursor() as (cursor, conn):
        cursor.execute(
            """
            SELECT id, name, username, joined_at, credits
            FROM users
            WHERE id = %s
            """, (user_id,)
        )
        user = cursor.fetchone()

    if not user:
        return jsonify({"error": "User not found"}), 404

    return jsonify(user)


@app.route("/api/bet", methods=["POST"])
def place_bet():
    data = request.json
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session['user']['user_id']
    round_id = data.get("round_id")
    crypto = data.get("crypto", "").upper()
    direction = data.get("direction")
    amount = data.get("amount")

    # Validate inputs
    if not round_id:
        return jsonify({"error": "Round ID is required"}), 400

    is_valid, result = validate_crypto_symbol(crypto)
    if not is_valid:
        return jsonify({"error": result}), 400
    crypto = result

    is_valid, result = validate_direction(direction)
    if not is_valid:
        return jsonify({"error": result}), 400
    direction = result

    is_valid, result = validate_bet_amount(amount)
    if not is_valid:
        return jsonify({"error": result}), 400
    amount = result

    with get_db_cursor() as (cursor, conn):
        cursor.execute(
            "SELECT id FROM bets WHERE user_id = %s AND round_id = %s",
            (user_id, round_id)
        )
        if cursor.fetchone():
            return jsonify({"error": "Bet already placed for this round"}), 409

        cursor.execute("SELECT credits FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()

        if not user:
            return jsonify({"error": "User not found"}), 404

        if user["credits"] < amount:
            return jsonify({"error": "Not enough credits"}), 400

        # Deduct user credits
        cursor.execute("UPDATE users SET credits = credits - %s WHERE id = %s", (amount, user_id))

        room = f"{crypto}-room"
        socketio.emit("credits_update", {
           "user_id": user_id,
           "change": -amount
          }, room=room)
        socketio.emit("credits_update", {
           "user_id": user_id,
           "change": -amount
          }, room=f"user-{user_id}")


        # Insert bet with timestamp
        cursor.execute(
            """
            INSERT INTO bets (user_id, round_id, crypto, direction, amount, created_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            """, (user_id, round_id, crypto, direction, amount)
        )

        conn.commit()

    room = f"{crypto}-room"
    socketio.emit("new_bet", {
       "crypto": crypto,
       "round_id": round_id,
       "direction": direction,
       "amount": amount
       }, room=room)


    return jsonify({"message": "Bet placed successfully"})



@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"message": "Logged out successfully"}), 200


@app.route("/api/live-bets", methods=["GET"])
def get_live_bets():
    round_id = request.args.get("round_id")
    crypto = request.args.get("crypto")
    
    if not round_id or not crypto:
        return jsonify({"error": "Missing round_id or crypto"}), 400

    with get_db_cursor() as (cursor, _):
        cursor.execute(
            "SELECT amount, direction FROM bets WHERE round_id = %s AND crypto = %s ORDER BY id DESC LIMIT 10",
            (round_id, crypto)
        )
        bets = cursor.fetchall()

    return jsonify(bets)

@app.route("/api/rounds", methods=["GET"])
def get_current_round():
    crypto = request.args.get("crypto", "BTC")
    with get_db_cursor() as (cursor, _):
        cursor.execute(
            "SELECT * FROM rounds WHERE crypto = %s ORDER BY id DESC LIMIT 1",
            (crypto,)
        )
        round_data = cursor.fetchone()

    if not round_data:
        return jsonify({"waiting": True, "message": "Waiting for first round to start..."}), 200

    return jsonify(round_data)

@app.route("/api/my-stats", methods=["GET"])
def get_my_stats():
    if 'user' not in session:
        return jsonify({"error": "Not logged in"}), 401

    user_id = session['user']['user_id']

    with get_db_cursor() as (cursor, _):
        cursor.execute(
            '''
            SELECT bets.*, rounds.start_price, rounds.end_price, rounds.result
            FROM bets
            JOIN rounds ON bets.round_id = rounds.id
            WHERE bets.user_id = %s
            ORDER BY bets.id DESC
            LIMIT 10
            ''', (user_id,)
        )
        data = cursor.fetchall()

    return jsonify(data)

@app.route("/api/leaderboard", methods=["GET"])
def leaderboard():
    period = request.args.get("period", "daily")  # daily or weekly
    now = datetime.utcnow()
    since = now - timedelta(days=1 if period == "daily" else 7)

    with get_db_cursor(real_dict=True) as (cursor, _):
        cursor.execute(
            """
            SELECT 
                b.user_id,
                u.username,
                COUNT(*) AS total_bets,
                SUM(CASE WHEN b.status = 'won' THEN b.amount * 0.8 ELSE 0 END) AS profit,
                SUM(CASE WHEN b.status = 'lost' THEN b.amount ELSE 0 END) AS loss,
                ROUND(SUM(CASE WHEN b.status = 'won' THEN 1 ELSE 0 END)::numeric / NULLIF(COUNT(*), 0) * 100, 2) AS win_rate,
                MAX(u.credits) AS credits
            FROM bets b
            JOIN users u ON b.user_id = u.id
            WHERE b.created_at >= %s
            GROUP BY b.user_id, u.username
            """,
            (since,)
        )
        rows = cursor.fetchall()

    return jsonify({
        "highest_win_rate": sorted(rows, key=lambda x: x['win_rate'] or 0, reverse=True)[:5],
        "most_bets": sorted(rows, key=lambda x: x['total_bets'], reverse=True)[:5],
        "most_credits": sorted(rows, key=lambda x: x['credits'], reverse=True)[:5],
        "biggest_losers": sorted(rows, key=lambda x: x['loss'], reverse=True)[:5],
    })


@app.route("/api/recent-wins", methods=["GET"])
def recent_wins():
    with get_db_cursor() as (cursor, _):
        cursor.execute('''
            SELECT bets.*, rounds.start_price, rounds.end_price 
            FROM bets 
            JOIN rounds ON bets.round_id = rounds.id 
            WHERE bets.status = 'won' 
            ORDER BY bets.id DESC 
            LIMIT 5
        ''')
        wins = cursor.fetchall()
    return jsonify(wins)


@app.route("/api/recent-rounds", methods=["GET"])
def get_recent_rounds():
    crypto = request.args.get("crypto", "BTC")
    with get_db_cursor() as (cursor, _):
        cursor.execute(
            '''
            SELECT id, start_price, end_price, result
            FROM rounds
            WHERE crypto = %s AND result IS NOT NULL
            ORDER BY id DESC
            LIMIT 5
        ''', (crypto,))
        recent = cursor.fetchall()
    return jsonify(list(reversed(recent)))

@app.route("/api/round-result", methods=["GET"])
def get_round_result():
    round_id = request.args.get("round_id")
    if not round_id:
        return jsonify({"error": "Missing round_id"}), 400

    with get_db_cursor() as (cursor, _):
        cursor.execute("SELECT end_price, result FROM rounds WHERE id = %s", (round_id,))
        round_data = cursor.fetchone()

    if not round_data or round_data["result"] is None:
        return jsonify({"message": "Result not ready"}), 404

    return jsonify(round_data)



@app.route("/api/user-bets", methods=["GET"])
def get_user_bets():
    if 'user' not in session:
        return jsonify({"error": "Not logged in"}), 401

    user_id = session['user']['user_id']
    round_id = request.args.get("round_id")
    if not round_id:
        return jsonify({"error": "Missing round_id"}), 400

    with get_db_cursor() as (cursor, _):
        cursor.execute("SELECT * FROM bets WHERE user_id = %s AND round_id = %s",
                       (user_id, round_id))
        bets = cursor.fetchall()
    return jsonify(bets)

@app.route("/api/user-bets-history", methods=["GET"])
def user_bets_history():
    if 'user' not in session:
        return jsonify({"error": "Not logged in"}), 401

    user_id = session['user']['user_id']
    with get_db_cursor() as (cursor, _):
        cursor.execute(
            '''
            SELECT b.*, r.start_price, r.end_price
            FROM bets b
            JOIN rounds r ON b.round_id = r.id
            WHERE b.user_id = %s
            ORDER BY b.id DESC
            LIMIT 10
        ''', (user_id,))
        bets = cursor.fetchall()
    return jsonify(bets)

@app.route("/api/notifications", methods=["GET"])
def get_notifications():
    if 'user' not in session:
        return jsonify({"error": "Not logged in"}), 401

    user_id = session['user']['user_id']
    all_notifications = []

    with get_db_cursor() as (cursor, _):
        # Get regular crypto bets
        cursor.execute(
            '''
            SELECT
                b.id,
                b.round_id,
                b.crypto,
                b.direction,
                b.amount,
                b.status,
                b.profit,
                b.created_at,
                r.start_price,
                r.end_price,
                r.result,
                r.start_time,
                r.end_time,
                'crypto' as bet_type
            FROM bets b
            JOIN rounds r ON b.round_id = r.id
            WHERE b.user_id = %s AND b.status != 'pending'
        ''', (user_id,))
        all_notifications.extend(cursor.fetchall())

        # Get custom bets
        cursor.execute(
            '''
            SELECT
                cb.id,
                cb.round_id,
                cbr.token_symbol as crypto,
                cb.prediction as direction,
                cb.amount,
                cb.status,
                cb.profit,
                cb.created_at,
                cbr.start_price,
                cbr.end_price,
                cbr.result,
                cbr.created_at as start_time,
                cbr.end_time,
                'custom' as bet_type
            FROM custom_bets cb
            JOIN custom_bet_rounds cbr ON cb.round_id = cbr.id
            WHERE cb.user_id = %s AND cb.status != 'pending'
        ''', (user_id,))
        all_notifications.extend(cursor.fetchall())

        # Get on-chain bets
        cursor.execute(
            '''
            SELECT
                ob.id,
                ob.round_id,
                obr.category as crypto,
                ob.prediction as direction,
                ob.amount,
                ob.status,
                ob.profit,
                ob.created_at,
                NULL as start_price,
                NULL as end_price,
                obr.result,
                obr.start_time,
                obr.end_time,
                'onchain' as bet_type
            FROM onchain_bets ob
            JOIN onchain_rounds obr ON ob.round_id = obr.id
            WHERE ob.user_id = %s AND ob.status != 'pending'
        ''', (user_id,))
        all_notifications.extend(cursor.fetchall())

    # Sort all notifications by created_at DESC and limit to 50
    all_notifications.sort(key=lambda x: x['created_at'], reverse=True)
    return jsonify(all_notifications[:50])

@app.route("/api/market-status", methods=["GET"])
def get_market_status():
    is_open = is_us_market_open()
    now_utc = datetime.utcnow()
    eastern = pytz.timezone('US/Eastern')
    now_est = now_utc.replace(tzinfo=pytz.utc).astimezone(eastern)

    return jsonify({
        "is_open": is_open,
        "current_time_est": now_est.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "day_of_week": now_est.strftime("%A")
    })

# ===== ON-CHAIN PREDICTION ENDPOINTS =====

@app.route("/api/onchain/categories", methods=["GET"])
def get_onchain_categories():
    """Get all available on-chain prediction categories"""
    categories = [
        {
            "id": "pumpfun_launches",
            "name": "pump.fun Token Launches",
            "description": "Predict if more or fewer tokens will launch than yesterday",
            "icon": "🚀"
        },
        {
            "id": "pumpfun_graduations",
            "name": "pump.fun Graduations",
            "description": "Predict if more or fewer tokens will graduate than yesterday",
            "icon": "🎓"
        }
    ]
    return jsonify(categories)

@app.route("/api/onchain/rounds", methods=["GET"])
def get_onchain_rounds():
    """Get active on-chain rounds"""
    category = request.args.get("category")

    with get_db_cursor() as (cursor, _):
        if category:
            cursor.execute(
                """
                SELECT * FROM onchain_rounds
                WHERE category = %s
                ORDER BY id DESC LIMIT 1
                """, (category,))
        else:
            cursor.execute(
                """
                SELECT * FROM onchain_rounds
                ORDER BY id DESC LIMIT 10
                """)

        rounds = cursor.fetchall()

    return jsonify(rounds if rounds else [])

@app.route("/api/onchain/bet", methods=["POST"])
def place_onchain_bet():
    """Place a bet on an on-chain prediction"""
    data = request.json
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session['user']['user_id']
    round_id = data.get("round_id")
    category = data.get("category")
    prediction = data.get("prediction")  # "higher" or "lower"

    try:
        amount = int(data.get("amount"))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid amount format"}), 400

    if not all([user_id, round_id, category, prediction]) or prediction not in ("higher", "lower") or amount <= 0:
        return jsonify({"error": "Invalid request"}), 400

    with get_db_cursor() as (cursor, conn):
        # Check if bet already placed
        cursor.execute(
            "SELECT id FROM onchain_bets WHERE user_id = %s AND round_id = %s",
            (user_id, round_id)
        )
        if cursor.fetchone():
            return jsonify({"error": "Bet already placed for this round"}), 409

        # Check user credits
        cursor.execute("SELECT credits FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()

        if not user:
            return jsonify({"error": "User not found"}), 404

        if user["credits"] < amount:
            return jsonify({"error": "Not enough credits"}), 400

        # Deduct credits
        cursor.execute("UPDATE users SET credits = credits - %s WHERE id = %s", (amount, user_id))

        # Insert bet
        cursor.execute(
            """
            INSERT INTO onchain_bets (user_id, round_id, category, prediction, amount, created_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            """, (user_id, round_id, category, prediction, amount)
        )

        conn.commit()

    return jsonify({"message": "Bet placed successfully"})

@app.route("/api/onchain/user-bets", methods=["GET"])
def get_user_onchain_bets():
    """Get user's on-chain bet history"""
    if 'user' not in session:
        return jsonify({"error": "Not logged in"}), 401

    user_id = session['user']['user_id']

    with get_db_cursor() as (cursor, _):
        cursor.execute(
            """
            SELECT ob.*, or.start_value, or.end_value, or.reference_value, or.result
            FROM onchain_bets ob
            JOIN onchain_rounds or ON ob.round_id = or.id
            WHERE ob.user_id = %s
            ORDER BY ob.created_at DESC
            LIMIT 20
            """, (user_id,)
        )
        bets = cursor.fetchall()

    return jsonify(bets)

# ===== CUSTOM BET ENDPOINTS =====

@app.route("/api/custom-bet/create", methods=["POST"])
def create_custom_bet():
    """Create a new custom bet round"""
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    user_id = session['user']['user_id']
    token_ca = data.get("token_ca", "").strip()
    duration = data.get("duration")

    # Validate inputs
    is_valid, result = validate_solana_address(token_ca)
    if not is_valid:
        return jsonify({"error": result}), 400
    token_ca = result

    is_valid, result = validate_duration(duration)
    if not is_valid:
        return jsonify({"error": result}), 400
    duration = result

    try:
        from dexscreener_client import DexScreenerClient

        # Check if there's already an active bet for this token
        with get_db_cursor() as (cursor, conn):
            cursor.execute(
                """
                SELECT id FROM custom_bet_rounds
                WHERE token_ca = %s AND status = 'active'
                """, (token_ca,)
            )
            if cursor.fetchone():
                return jsonify({"error": "Active bet already exists for this token"}), 409

            # Validate token via DexScreener
            dex_client = DexScreenerClient()
            is_valid, token_data, error = dex_client.validate_token(token_ca, min_mcap=200000)

            if not is_valid:
                return jsonify({"error": error or "Token validation failed"}), 400

            # Create the custom bet round
            now = int(time.time())
            end_time = now + (duration * 60)

            cursor.execute(
                """
                INSERT INTO custom_bet_rounds
                (creator_id, token_ca, token_name, token_symbol, start_price, start_mcap,
                 duration_minutes, start_time, end_time, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'active')
                RETURNING id
                """,
                (user_id, token_ca, token_data['name'], token_data['symbol'],
                 token_data['price_usd'], token_data['mcap'], duration, now, end_time)
            )
            round_id = cursor.fetchone()['id']
            conn.commit()

            return jsonify({
                "message": "Custom bet created successfully",
                "round_id": round_id,
                "token": {
                    "name": token_data['name'],
                    "symbol": token_data['symbol'],
                    "mcap": token_data['mcap']
                }
            })

    except Exception as e:
        print(f"[CUSTOM BET] Error creating bet: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/custom-bet/active", methods=["GET"])
def get_active_custom_bets():
    """Get all active custom bet rounds"""
    with get_db_cursor() as (cursor, _):
        cursor.execute(
            """
            SELECT cbr.*,
                   COUNT(cb.id) as bet_count,
                   u.username as creator_username
            FROM custom_bet_rounds cbr
            LEFT JOIN custom_bets cb ON cbr.id = cb.round_id
            LEFT JOIN users u ON cbr.creator_id = u.id
            WHERE cbr.status = 'active'
            GROUP BY cbr.id, u.username
            ORDER BY cbr.created_at DESC
            """)
        rounds = cursor.fetchall()

    return jsonify(rounds)

@app.route("/api/custom-bet/<int:round_id>", methods=["GET"])
def get_custom_bet_details(round_id):
    """Get details of a specific custom bet round"""
    with get_db_cursor() as (cursor, _):
        cursor.execute(
            """
            SELECT cbr.*,
                   COUNT(cb.id) as bet_count,
                   SUM(CASE WHEN cb.prediction = 'higher' THEN cb.amount ELSE 0 END) as higher_pool,
                   SUM(CASE WHEN cb.prediction = 'lower' THEN cb.amount ELSE 0 END) as lower_pool,
                   u.username as creator_username
            FROM custom_bet_rounds cbr
            LEFT JOIN custom_bets cb ON cbr.id = cb.round_id
            LEFT JOIN users u ON cbr.creator_id = u.id
            WHERE cbr.id = %s
            GROUP BY cbr.id, u.username
            """, (round_id,))
        round_data = cursor.fetchone()

    if not round_data:
        return jsonify({"error": "Round not found"}), 404

    return jsonify(round_data)

@app.route("/api/custom-bet/place", methods=["POST"])
def place_custom_bet():
    """Place a bet on a custom round"""
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    user_id = session['user']['user_id']
    round_id = data.get("round_id")
    prediction = data.get("prediction")
    amount = data.get("amount")

    if not all([round_id, prediction, amount]) or prediction not in ["higher", "lower"]:
        return jsonify({"error": "Invalid bet data"}), 400

    try:
        amount = int(amount)
        if amount <= 0:
            return jsonify({"error": "Invalid amount"}), 400
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid amount format"}), 400

    with get_db_cursor() as (cursor, conn):
        # Check round exists and is active
        cursor.execute(
            "SELECT * FROM custom_bet_rounds WHERE id = %s AND status = 'active'",
            (round_id,)
        )
        round_data = cursor.fetchone()

        if not round_data:
            return jsonify({"error": "Round not found or inactive"}), 404

        # Check if betting window is still open (must be >5 minutes remaining)
        now = int(time.time())
        time_left = round_data['end_time'] - now

        if time_left < 300:  # 5 minutes
            return jsonify({"error": "Betting window closed"}), 400

        # Check user credits
        cursor.execute("SELECT credits FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()

        if not user or user['credits'] < amount:
            return jsonify({"error": "Insufficient credits"}), 400

        # Deduct credits
        cursor.execute("UPDATE users SET credits = credits - %s WHERE id = %s", (amount, user_id))

        # Place bet
        cursor.execute(
            """
            INSERT INTO custom_bets (user_id, round_id, prediction, amount)
            VALUES (%s, %s, %s, %s)
            """, (user_id, round_id, prediction, amount)
        )

        # Update round pool
        cursor.execute(
            "UPDATE custom_bet_rounds SET total_pool = total_pool + %s WHERE id = %s",
            (amount, round_id)
        )

        conn.commit()

    return jsonify({"message": "Bet placed successfully"})

@app.route("/api/custom-bet/user-bets", methods=["GET"])
def get_user_custom_bets():
    """Get user's custom bet history"""
    if 'user' not in session:
        return jsonify({"error": "Not logged in"}), 401

    user_id = session['user']['user_id']

    with get_db_cursor() as (cursor, _):
        cursor.execute(
            """
            SELECT cb.*, cbr.token_name, cbr.token_symbol, cbr.token_ca,
                   cbr.start_price, cbr.end_price, cbr.duration_minutes, cbr.result
            FROM custom_bets cb
            JOIN custom_bet_rounds cbr ON cb.round_id = cbr.id
            WHERE cb.user_id = %s
            ORDER BY cb.created_at DESC
            LIMIT 50
            """, (user_id,)
        )
        bets = cursor.fetchall()

    return jsonify(bets)

@app.route("/api/custom-bet/creator-earnings", methods=["GET"])
def get_creator_earnings():
    """Get user's earnings as a bet creator"""
    if 'user' not in session:
        return jsonify({"error": "Not logged in"}), 401

    user_id = session['user']['user_id']

    with get_db_cursor() as (cursor, _):
        cursor.execute(
            """
            SELECT SUM(creator_earnings) as total_earnings,
                   COUNT(*) as total_rounds_created
            FROM custom_bet_rounds
            WHERE creator_id = %s AND status = 'resolved'
            """, (user_id,)
        )
        earnings = cursor.fetchone()

    return jsonify(earnings or {"total_earnings": 0, "total_rounds_created": 0})

def manage_stock_rounds(price_data):
    with get_db_cursor() as (cursor, conn):
        now = datetime.utcnow()
        today = now.date()
        tomorrow = today + timedelta(days=1)
        end_of_tomorrow = int(
            datetime.combine(tomorrow,
                             datetime.strptime("20:00", "%H:%M").time()).timestamp())

        for symbol, details in price_data.items():
            price = details["close"]

            # Check if a round already exists for today
            cursor.execute(
                """
                SELECT * FROM rounds 
                WHERE crypto = %s AND DATE(to_timestamp(start_time)) = %s
                """, (symbol, today))
            existing = cursor.fetchone()

            if not existing:
                start_timestamp = int(now.timestamp())
                cursor.execute(
                    """
                    INSERT INTO rounds (crypto, start_price, start_time, end_time)
                    VALUES (%s, %s, %s, %s)
                    """, (symbol, price, start_timestamp, end_of_tomorrow))
                conn.commit()


def is_us_market_open():
    now_utc = datetime.utcnow()
    eastern = pytz.timezone('US/Eastern')
    now_est = now_utc.replace(tzinfo=pytz.utc).astimezone(eastern)

    if now_est.weekday() >= 5:  # Saturday or Sunday
        return False

    market_open = now_est.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now_est.replace(hour=16, minute=0, second=0, microsecond=0)

    return market_open <= now_est <= market_close


def run_stock_open_rounds():
    #print("📈 Creating stock rounds at market open...")
    stock_prices = get_all_stock_prices()
    if stock_prices:
        formatted = {
            symbol: {
                "close": price
            }
            for symbol, price in stock_prices.items()
        }
        manage_stock_rounds(formatted)


def run_stock_close_resolution():
    stock_prices = get_all_stock_prices()

    with get_db_cursor() as (cursor, conn):
        for symbol, end_price in stock_prices.items():
            today = datetime.utcnow().date()
            cursor.execute(
                "SELECT * FROM rounds WHERE crypto = %s AND DATE(to_timestamp(start_time)) = %s AND result IS NULL",
                (symbol, today))
            round_data = cursor.fetchone()

            if round_data:
                result = "same"
                if end_price > round_data["start_price"]:
                    result = "up"
                elif end_price < round_data["start_price"]:
                    result = "down"

                cursor.execute(
                    "UPDATE rounds SET end_price = %s, result = %s WHERE id = %s",
                    (end_price, result, round_data["id"]))
                conn.commit()
                resolve_round(round_data["id"], result)



def schedule_stock_tasks():
    # At 9:30 AM EST = 14:30 UTC → create stock rounds when market opens
    schedule.every().day.at("14:30").do(run_stock_open_rounds)

    # At 4:00 PM EST = 21:00 UTC → resolve stock rounds when market closes
    schedule.every().day.at("21:00").do(run_stock_close_resolution)

    while True:
        schedule.run_pending()
        time.sleep(1)


TWELVE_API_KEY = os.environ['TWELVE_API_KEY']


def get_all_stock_prices():
    symbols = ",".join(STOCK_MAP.keys())  # e.g., AAPL,GOOGL,MSFT,...
    url = f"https://api.twelvedata.com/price?symbol={symbols}&apikey={TWELVE_API_KEY}"

    try:
        res = requests.get(url)
        data = res.json()

        # Normalize: convert to dict of {symbol: price}
        prices = {}
        for symbol in STOCK_MAP:
            price_data = data.get(symbol)
            if isinstance(price_data, dict) and "price" in price_data:
                prices[symbol] = float(price_data["price"])
        return prices
    except Exception as e:
        #print("❌ Error fetching stock prices:", e)
        return {}


def get_all_prices():
    """Fetch all crypto prices in parallel for speed"""
    print("[PRICES] Fetching prices...")
    start_time = time.time()

    # Method 1: Try Binance bulk API (all symbols in ONE request)
    try:
        symbols_list = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "MATICUSDT",
                       "XRPUSDT", "ADAUSDT", "DOGEUSDT", "DOTUSDT", "AVAXUSDT"]
        # Binance allows fetching all prices at once
        url = "https://api.binance.com/api/v3/ticker/price"
        res = requests.get(url, timeout=3)
        data = res.json()

        # Map Binance symbols back to our symbols
        symbol_map = {
            "BTCUSDT": "BTC", "ETHUSDT": "ETH", "SOLUSDT": "SOL",
            "BNBUSDT": "BNB", "MATICUSDT": "MATIC", "XRPUSDT": "XRP",
            "ADAUSDT": "ADA", "DOGEUSDT": "DOGE", "DOTUSDT": "DOT",
            "AVAXUSDT": "AVAX"
        }

        prices = {}
        for item in data:
            if item["symbol"] in symbol_map and "price" in item:
                symbol = symbol_map[item["symbol"]]
                prices[symbol] = {"usd": float(item["price"])}

        if len(prices) >= 8:  # At least 8 out of 10 prices
            elapsed = time.time() - start_time
            print(f"[BINANCE] Got {len(prices)} prices in {elapsed:.2f}s")
            return prices
    except Exception as e:
        print(f"[BINANCE] API failed: {e}")

    # Method 2: Fallback to CoinGecko (single request for all)
    try:
        cg_ids = {
            "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
            "BNB": "binancecoin", "MATIC": "polygon", "XRP": "ripple",
            "ADA": "cardano", "DOGE": "dogecoin", "DOT": "polkadot",
            "AVAX": "avalanche-2",
        }
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {"ids": ",".join(cg_ids.values()), "vs_currencies": "usd"}
        headers = {"accept": "application/json", "x-cg-demo-api-key": CG_API_KEY}
        res = requests.get(url, params=params, headers=headers, timeout=5)
        data = res.json()

        prices = {}
        for symbol, cg_id in cg_ids.items():
            if cg_id in data and "usd" in data[cg_id]:
                prices[symbol] = {"usd": float(data[cg_id]["usd"])}

        elapsed = time.time() - start_time
        print(f"[COINGECKO] Got {len(prices)} prices in {elapsed:.2f}s")
        return prices
    except Exception as e:
        print(f"[COINGECKO] API failed: {e}")
        return {}




def resolve_round(round_id, result):
    with get_db_cursor() as (cursor, conn):
        # ✅ First, fetch round info (needed for room and emit)
        cursor.execute("SELECT end_price, crypto FROM rounds WHERE id = %s", (round_id,))
        round_info = cursor.fetchone()
        room = f"{round_info['crypto']}-room"

        # ✅ Emit round resolution IMMEDIATELY so frontend updates
        socketio.emit("round_resolved", {
            "round_id": round_id,
            "crypto": round_info["crypto"],
            "end_price": round_info["end_price"],
            "result": result
        }, room=room)

        # ✅ Fetch all bets for the round
        cursor.execute("SELECT * FROM bets WHERE round_id = %s", (round_id,))
        all_bets = cursor.fetchall()

        # ✅ Process result
        if result == "same":
            for bet in all_bets:
                cursor.execute(
                    "UPDATE users SET credits = credits + %s WHERE id = %s",
                    (bet['amount'], bet['user_id']))
                cursor.execute(
                    "UPDATE bets SET status = 'refunded', profit = 0 WHERE id = %s",
                    (bet['id'],))
                socketio.emit("credits_update", {
                    "user_id": bet['user_id'],
                    "change": bet['amount']
                }, room=room)
                socketio.emit("credits_update", {
                    "user_id": bet['user_id'],
                    "change": bet['amount']
                }, room=f"user-{bet['user_id']}")
                socketio.emit("bet_result", {
                    "round_id": round_id,
                    "crypto": round_info["crypto"],
                    "status": "refunded",
                    "end_price": round_info["end_price"],
                    "amount": bet['amount'],
                    "profit": 0
                }, room=f"user-{bet['user_id']}")
        else:
            for bet in all_bets:
                if bet['direction'] == result:
                    winnings = int(bet['amount'] * 1.8)
                    profit = winnings - bet['amount']
                    cursor.execute(
                        "UPDATE users SET credits = credits + %s WHERE id = %s",
                        (winnings, bet['user_id']))
                    cursor.execute(
                        "UPDATE bets SET status = 'won', profit = %s WHERE id = %s",
                        (profit, bet['id']))
                    socketio.emit("credits_update", {
                        "user_id": bet['user_id'],
                        "change": winnings
                    }, room=room)
                    socketio.emit("credits_update", {
                        "user_id": bet['user_id'],
                        "change": winnings
                    }, room=f"user-{bet['user_id']}")
                    socketio.emit("bet_result", {
                        "round_id": round_id,
                        "crypto": round_info["crypto"],
                        "status": "won",
                        "end_price": round_info["end_price"],
                        "amount": bet['amount'],
                        "profit": profit
                    }, room=f"user-{bet['user_id']}")
                else:
                    loss = -bet['amount']
                    cursor.execute(
                        "UPDATE bets SET status = 'lost', profit = %s WHERE id = %s",
                        (loss, bet['id']))
                    socketio.emit("credits_update", {
                        "user_id": bet['user_id'],
                        "change": 0
                    }, room=room)
                    socketio.emit("credits_update", {
                        "user_id": bet['user_id'],
                        "change": 0
                    }, room=f"user-{bet['user_id']}")
                    socketio.emit("bet_result", {
                        "round_id": round_id,
                        "crypto": round_info["crypto"],
                        "status": "lost",
                        "end_price": round_info["end_price"],
                        "amount": bet['amount'],
                        "profit": loss
                    }, room=f"user-{bet['user_id']}")

        # Commit all database changes
        conn.commit()
        print(f"  [BETS] Resolved {len(all_bets)} bets for round #{round_id}")


def manage_round_for_symbol(symbol, price_data):
    if symbol not in price_data:
        return

    price = price_data[symbol]["usd"]
    current_time = int(time.time())

    with get_db_cursor() as (cursor, conn):
        cursor.execute(
            "SELECT * FROM rounds WHERE crypto = %s ORDER BY id DESC LIMIT 1",
            (symbol,))
        last_round = cursor.fetchone()

        # 🧠 Only create a new round if no round exists or the last one has ended
        if not last_round or current_time > last_round["end_time"]:
            start_time = current_time
            end_time = current_time + 120
            cursor.execute(
                "INSERT INTO rounds (crypto, start_price, start_time, end_time) VALUES (%s, %s, %s, %s)",
                (symbol, price, start_time, end_time))
            conn.commit()

            room = f"{symbol}-room"
            socketio.emit("round_update", {
                "crypto": symbol,
                "start_price": price,
                "start_time": start_time,
                "end_time": end_time
            }, room=room)

            print(f"[NEW ROUND] {symbol}: {start_time} -> {end_time}")




def run_rounds_forever():
    round_duration = 900  # 15 minutes
    pause_duration = 15

    # Start immediately without alignment for instant rounds
    while True:
        # Fetch start price once for all tokens
        prices = get_all_prices()
        round_start = int(time.time())
        round_end = round_start + round_duration

        for symbol in CRYPTO_MAP.keys():
            price = prices.get(symbol, {}).get("usd")
            if not price:
                continue

            with get_db_cursor() as (cursor, conn):
                cursor.execute(
                    "INSERT INTO rounds (crypto, start_price, start_time, end_time) VALUES (%s, %s, %s, %s) RETURNING id",
                    (symbol, price, round_start, round_end)
                )
                round_id = cursor.fetchone()['id']
                conn.commit()

                room = f"{symbol}-room"
                socketio.emit("round_update", {
                    "crypto": symbol,
                    "round_id": round_id,
                    "start_price": price,
                    "start_time": round_start,
                    "end_time": round_end
                }, room=room)

        print(f"[ROUNDS] Round started at {round_start} and will end at {round_end}")
        time.sleep(round_duration)

        # At round end, fetch current price and resolve
        print(f"[ROUNDS] Round ended! Fetching end prices...")
        prices = get_all_prices()

        if not prices:
            print(f"[ERROR] Failed to get prices! Skipping resolution...")
            continue

        print(f"[RESOLUTION] Got prices for {len(prices)} cryptos. Resolving all rounds in parallel...")

        # Helper function to resolve a single symbol's round
        def resolve_single_symbol(symbol):
            try:
                with get_db_cursor() as (cursor, conn):
                    cursor.execute("SELECT * FROM rounds WHERE crypto = %s ORDER BY id DESC LIMIT 1", (symbol,))
                    round_data = cursor.fetchone()

                    if not round_data or round_data["result"] is not None:
                        return None

                    end_price = prices.get(symbol, {}).get("usd", round_data["start_price"])
                    result = "same"
                    if end_price > round_data["start_price"]:
                        result = "up"
                    elif end_price < round_data["start_price"]:
                        result = "down"

                    cursor.execute(
                        "UPDATE rounds SET end_price = %s, result = %s WHERE id = %s",
                        (end_price, result, round_data["id"])
                    )
                    conn.commit()

                    print(f"  [RESOLVE] {symbol} Round #{round_data['id']}: {round_data['start_price']} -> {end_price} = {result.upper()}")
                    resolve_round(round_data["id"], result)
                    return symbol
            except Exception as e:
                print(f"  [ERROR] Error resolving {symbol}: {e}")
                return None

        # Resolve all rounds in parallel using ThreadPoolExecutor
        resolved_count = 0
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(resolve_single_symbol, symbol): symbol for symbol in CRYPTO_MAP.keys()}
            for future in as_completed(futures):
                if future.result() is not None:
                    resolved_count += 1

        print(f"[SUCCESS] Resolved {resolved_count} rounds in parallel. Pausing exactly {pause_duration}s before next round starts instantly...")
        time.sleep(pause_duration)
        print(f"[ROUNDS] Starting new round immediately after pause!")




# ===== ON-CHAIN PREDICTION MANAGEMENT =====

def create_onchain_round(category):
    """Create a new 24-hour on-chain prediction round"""
    try:
        # Import here to avoid circular imports
        from dune_client import PREDICTION_CATEGORIES

        if category not in PREDICTION_CATEGORIES:
            print(f"[ONCHAIN] Unknown category: {category}")
            return

        config = PREDICTION_CATEGORIES[category]

        # Get yesterday's value as reference
        yesterday_data = config["fetch_function"]()
        if not yesterday_data:
            print(f"[ONCHAIN] Failed to fetch data for {category}")
            return

        reference_value = yesterday_data.get(config["metric_key"], 0)

        # Create 24-hour round
        now = int(time.time())
        end_time = now + 86400  # 24 hours

        with get_db_cursor() as (cursor, conn):
            cursor.execute(
                """
                INSERT INTO onchain_rounds (category, start_value, reference_value, start_time, end_time, metadata)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (category, 0, reference_value, now, end_time, json.dumps({'yesterday_data': yesterday_data}))
            )
            round_id = cursor.fetchone()['id']
            conn.commit()

            print(f"[ONCHAIN] Created round #{round_id} for {category} - Reference: {reference_value}")

    except Exception as e:
        print(f"[ONCHAIN] Error creating round for {category}: {e}")


def resolve_onchain_round(round_id):
    """Resolve an on-chain prediction round"""
    try:
        from dune_client import PREDICTION_CATEGORIES

        with get_db_cursor() as (cursor, conn):
            cursor.execute("SELECT * FROM onchain_rounds WHERE id = %s", (round_id,))
            round_data = cursor.fetchone()

            if not round_data or round_data["result"] is not None:
                return

            category = round_data["category"]
            config = PREDICTION_CATEGORIES.get(category)

            if not config:
                print(f"[ONCHAIN] Unknown category: {category}")
                return

            # Fetch today's data
            today_data = config["fetch_function"]()
            if not today_data:
                print(f"[ONCHAIN] Failed to fetch resolution data for {category}")
                return

            end_value = today_data.get(config["metric_key"], 0)
            reference_value = round_data["reference_value"]

            # Determine result
            if end_value > reference_value:
                result = "higher"
            elif end_value < reference_value:
                result = "lower"
            else:
                result = "same"

            # Update round
            cursor.execute(
                "UPDATE onchain_rounds SET end_value = %s, result = %s WHERE id = %s",
                (end_value, result, round_id)
            )
            conn.commit()

            print(f"[ONCHAIN] Round #{round_id} - {category}: {reference_value} -> {end_value} = {result.upper()}")

            # Resolve bets
            resolve_onchain_bets(round_id, result)

    except Exception as e:
        print(f"[ONCHAIN] Error resolving round #{round_id}: {e}")


def resolve_onchain_bets(round_id, result):
    """Resolve all bets for an on-chain round"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("SELECT * FROM onchain_bets WHERE round_id = %s", (round_id,))
        all_bets = cursor.fetchall()

        if result == "same":
            # Refund all bets
            for bet in all_bets:
                cursor.execute(
                    "UPDATE users SET credits = credits + %s WHERE id = %s",
                    (bet['amount'], bet['user_id'])
                )
                cursor.execute(
                    "UPDATE onchain_bets SET status = 'refunded', profit = 0 WHERE id = %s",
                    (bet['id'],)
                )
        else:
            # Process wins and losses
            for bet in all_bets:
                if bet['prediction'] == result:
                    # Winner
                    winnings = int(bet['amount'] * 1.8)
                    profit = winnings - bet['amount']
                    cursor.execute(
                        "UPDATE users SET credits = credits + %s WHERE id = %s",
                        (winnings, bet['user_id'])
                    )
                    cursor.execute(
                        "UPDATE onchain_bets SET status = 'won', profit = %s WHERE id = %s",
                        (profit, bet['id'])
                    )
                else:
                    # Loser
                    loss = -bet['amount']
                    cursor.execute(
                        "UPDATE onchain_bets SET status = 'lost', profit = %s WHERE id = %s",
                        (loss, bet['id'])
                    )

        conn.commit()
        print(f"[ONCHAIN] Resolved {len(all_bets)} bets for round #{round_id}")


def run_onchain_rounds():
    """Create and resolve on-chain prediction rounds daily"""
    from dune_client import PREDICTION_CATEGORIES

    while True:
        try:
            now = datetime.utcnow()

            # Create new rounds at midnight UTC
            if now.hour == 0 and now.minute == 0:
                print("[ONCHAIN] Creating new daily rounds...")
                for category in PREDICTION_CATEGORIES.keys():
                    create_onchain_round(category)

                # Wait a minute to avoid duplicate creation
                time.sleep(60)

            # Check for rounds to resolve
            with get_db_cursor() as (cursor, _):
                cursor.execute(
                    """
                    SELECT id FROM onchain_rounds
                    WHERE result IS NULL AND end_time <= %s
                    """,
                    (int(time.time()),)
                )
                rounds_to_resolve = cursor.fetchall()

            for round_row in rounds_to_resolve:
                resolve_onchain_round(round_row['id'])

            time.sleep(30)  # Check every 30 seconds

        except Exception as e:
            print(f"[ONCHAIN] Error in round manager: {e}")
            time.sleep(60)


# ===== CUSTOM BET RESOLUTION =====

def resolve_custom_bet_round(round_id):
    """Resolve a custom bet round with 20% creator fee"""
    try:
        from dexscreener_client import DexScreenerClient

        with get_db_cursor() as (cursor, conn):
            cursor.execute("SELECT * FROM custom_bet_rounds WHERE id = %s", (round_id,))
            round_data = cursor.fetchone()

            if not round_data or round_data['status'] != 'active':
                return

            # Fetch current price from DexScreener
            dex_client = DexScreenerClient()
            token_data = dex_client.get_token_info(round_data['token_ca'])

            if not token_data:
                print(f"[CUSTOM BET] Could not fetch price for round #{round_id}")
                # Mark as error
                cursor.execute(
                    "UPDATE custom_bet_rounds SET status = 'error' WHERE id = %s",
                    (round_id,)
                )
                conn.commit()
                return

            end_price = token_data['price_usd']
            start_price = round_data['start_price']

            # Determine result
            if end_price > start_price:
                result = "higher"
            elif end_price < start_price:
                result = "lower"
            else:
                result = "same"

            # Update round with end price and result
            cursor.execute(
                """
                UPDATE custom_bet_rounds
                SET end_price = %s, result = %s, status = 'resolved'
                WHERE id = %s
                """,
                (end_price, result, round_id)
            )

            print(f"[CUSTOM BET] Round #{round_id} ({round_data['token_symbol']}): ${start_price} -> ${end_price} = {result.upper()}")

            # Resolve bets with 20% creator fee
            cursor.execute("SELECT * FROM custom_bets WHERE round_id = %s", (round_id,))
            all_bets = cursor.fetchall()

            if len(all_bets) == 0:
                conn.commit()
                print(f"[CUSTOM BET] No bets placed on round #{round_id}")
                return

            total_pool = round_data['total_pool']
            creator_fee = int(total_pool * 0.20)  # 20% to creator
            winner_pool = total_pool - creator_fee  # 80% to winners

            if result == "same":
                # Refund all bets (no creator fee on refunds)
                for bet in all_bets:
                    cursor.execute(
                        "UPDATE users SET credits = credits + %s WHERE id = %s",
                        (bet['amount'], bet['user_id'])
                    )
                    cursor.execute(
                        "UPDATE custom_bets SET status = 'refunded', profit = 0 WHERE id = %s",
                        (bet['id'],)
                    )
                print(f"[CUSTOM BET] Refunded {len(all_bets)} bets (price stayed same)")
            else:
                # Calculate winners and losers
                winners = [bet for bet in all_bets if bet['prediction'] == result]
                losers = [bet for bet in all_bets if bet['prediction'] != result]

                if len(winners) == 0:
                    # No winners, creator gets 100% of pool
                    cursor.execute(
                        "UPDATE users SET credits = credits + %s WHERE id = %s",
                        (total_pool, round_data['creator_id'])
                    )
                    cursor.execute(
                        "UPDATE custom_bet_rounds SET creator_earnings = %s WHERE id = %s",
                        (total_pool, round_id)
                    )
                    print(f"[CUSTOM BET] No winners - Creator gets full pool: {total_pool}")
                else:
                    # Pay creator fee
                    cursor.execute(
                        "UPDATE users SET credits = credits + %s WHERE id = %s",
                        (creator_fee, round_data['creator_id'])
                    )
                    cursor.execute(
                        "UPDATE custom_bet_rounds SET creator_earnings = %s WHERE id = %s",
                        (creator_fee, round_id)
                    )

                    # Calculate winner payouts
                    total_winner_bets = sum(bet['amount'] for bet in winners)

                    for bet in winners:
                        # Winner gets their share of the 80% pool
                        share = bet['amount'] / total_winner_bets
                        payout = int(winner_pool * share)
                        profit = payout - bet['amount']

                        cursor.execute(
                            "UPDATE users SET credits = credits + %s WHERE id = %s",
                            (payout, bet['user_id'])
                        )
                        cursor.execute(
                            "UPDATE custom_bets SET status = 'won', profit = %s WHERE id = %s",
                            (profit, bet['id'])
                        )

                    # Mark losers
                    for bet in losers:
                        loss = -bet['amount']
                        cursor.execute(
                            "UPDATE custom_bets SET status = 'lost', profit = %s WHERE id = %s",
                            (loss, bet['id'])
                        )

                    print(f"[CUSTOM BET] Resolved: {len(winners)} winners, {len(losers)} losers, Creator fee: {creator_fee}")

            conn.commit()

    except Exception as e:
        print(f"[CUSTOM BET] Error resolving round #{round_id}: {e}")


def run_custom_bet_resolver():
    """Background task to resolve expired custom bets"""
    from dexscreener_client import DexScreenerClient

    while True:
        try:
            now = int(time.time())

            # Find expired rounds
            with get_db_cursor() as (cursor, _):
                cursor.execute(
                    """
                    SELECT id FROM custom_bet_rounds
                    WHERE status = 'active' AND end_time <= %s
                    """,
                    (now,)
                )
                rounds_to_resolve = cursor.fetchall()

            for round_row in rounds_to_resolve:
                resolve_custom_bet_round(round_row['id'])

            time.sleep(30)  # Check every 30 seconds

        except Exception as e:
            print(f"[CUSTOM BET] Error in resolver: {e}")
            time.sleep(60)


@socketio.on("join")
def handle_join(data):
    crypto = data.get("crypto")
    if crypto:
        room = f"{crypto.upper()}-room"
        join_room(room)
        print(f"? User joined {room}")


@socketio.on("join_user")
def handle_user_join(data):
    user_id = data.get("user_id")
    if user_id:
        room = f"user-{user_id}"
        join_room(room)
        print(f"? User joined {room}")


@socketio.on("leave")
def handle_leave(data):
    crypto = data.get("crypto")
    if crypto:
        room = f"{crypto.upper()}-room"
        leave_room(room)
        print(f"?? User left {room}")


@socketio.on("leave_user")
def handle_user_leave(data):
    user_id = data.get("user_id")
    if user_id:
        room = f"user-{user_id}"
        leave_room(room)
        print(f"?? User left {room}")


if __name__ == "__main__":
    init_db()
    threading.Thread(target=run_rounds_forever, daemon=True).start()
    threading.Thread(target=schedule_stock_tasks, daemon=True).start()
    threading.Thread(target=run_onchain_rounds, daemon=True).start()
    threading.Thread(target=run_custom_bet_resolver, daemon=True).start()
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    socketio.run(app, host="0.0.0.0", port=8080, debug=debug_mode)

