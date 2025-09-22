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
from authlib.integrations.flask_client import OAuth
from authlib.common.encoding import json_loads, json_dumps
from flask_session import Session
from flask import session, redirect, url_for
from flask import send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix
import redis
from authlib.integrations.base_client.errors import MismatchingStateError
from dotenv import load_dotenv
load_dotenv()
from psycopg2.pool import ThreadedConnectionPool
from contextlib import contextmanager
from flask_socketio import join_room
from flask_socketio import leave_room

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.config['SESSION_TYPE'] = 'redis'
app.config['SESSION_REDIS'] = redis.from_url(os.environ['REDIS_URL'])
app.config['SESSION_COOKIE_NAME'] = 'bet_session'
app.config['SESSION_PERMANENT'] = False
app.config['SESSION_USE_SIGNER'] = True
app.config['SESSION_KEY_PREFIX'] = 'sess:'
app.config['SESSION_COOKIE_SAMESITE'] = "Lax"
app.config['SESSION_COOKIE_SECURE'] = False



app.config['SECRET_KEY'] = os.environ['SECRET_KEY']  # You can change this

Session(app)
CORS(app, supports_credentials=True)

class RedisStateStorage:

    def __init__(self, redis_client):
        self.r = redis_client

    def set(self, key, value, ttl=300):
        self.r.setex(key, ttl, value)

    def get(self, key):
        value = self.r.get(key)
        if value:
            self.r.delete(key)
            return value
        return None


class CustomOAuth(OAuth):

    def create_client(self, name):
        client = super().create_client(name)
        client.state_storage = RedisStateStorage(redis.from_url(os.environ['REDIS_URL']))

        return client


oauth = CustomOAuth(app)

google = oauth.register(
    name='google',
    client_id=os.environ['GOOGLE_CLIENT_ID'],
    client_secret=os.environ['GOOGLE_CLIENT_SECRET'],
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={'scope': 'openid email profile'},
    authorize_params={
        'access_type': 'offline',
        'prompt': 'consent'
    }
)


# Symbol to CoinGecko ID mapping
CRYPTO_MAP = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
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


def init_db():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            credits INTEGER DEFAULT 1000
        );
    ''')
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
            credits INTEGER DEFAULT 1000,
            name TEXT,
            username TEXT,
            picture TEXT,
            joined_at TIMESTAMP DEFAULT NOW()
        );
    """)

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
            username TEXT,
            email TEXT,
            picture TEXT,
            joined_at TIMESTAMP,
            credits INTEGER DEFAULT 1000
        )
    """)
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
        picture = data.get("picture")

        cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()

        if not user:
            cursor.execute(
                """
                INSERT INTO users (id, name, username, picture, joined_at, credits)
                VALUES (%s, %s, %s, %s, NOW(), %s)
                """, (user_id, name, username, picture, 1000))
            cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()

    return jsonify({
        "user_id": user["id"],
        "name": user.get("name"),
        "username": user.get("username"),
        "picture": user.get("picture"),
        "joined_at": user.get("joined_at"),
        "credits": user.get("credits")
    })

@app.route("/login")
def login():
    redirect_uri = url_for('authorize', _external=True)
    return google.authorize_redirect(redirect_uri)

# or redirect to frontend

@app.route("/authorize")
def authorize():
    try:
        token = google.authorize_access_token()
    except MismatchingStateError:
        return redirect("/")  # ✅ simple internal path

    resp = google.get("https://www.googleapis.com/oauth2/v2/userinfo", token=token)
    user_info = resp.json()

    user_id = f"google-{user_info['id']}"
    name = user_info.get("name")
    email = user_info.get("email")
    picture = user_info.get("picture")
    joined_at = datetime.utcnow()
    username = (email.split("@")[0] if email else f"user{user_info['id'][-4:]}")

    session['user'] = {
        "user_id": user_id,
        "name": name,
        "email": email,
        "picture": picture,
        "username": username,
        "joined_at": str(joined_at.date())
    }

    with get_db_cursor() as (cursor, conn):
        cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()

        if not user:
            cursor.execute(
                """
                INSERT INTO users (id, name, username, email, picture, joined_at, credits)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (user_id, name, username, email, picture, joined_at, 1000)
            )

    return redirect("http://localhost:5173/")  # ✅ ✅ ✅ internal home redirect

# or wherever you want after login


@app.route("/api/profile")
def get_profile():
    if 'user' not in session:
        return jsonify({"error": "Not logged in"}), 401

    user_id = session['user']['user_id']

    with get_db_cursor() as (cursor, conn):
        cursor.execute(
            """
            SELECT id, name, username, email, picture, joined_at, credits
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

    try:
        amount = int(data.get("amount"))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid amount format"}), 400

    if not all([user_id, round_id, crypto, direction]) or direction not in ("up", "down") or amount <= 0:
        return jsonify({"error": "Invalid request"}), 400

    with get_db_cursor() as (cursor, conn):
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
        return jsonify({"message": "No round found"}), 404

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
    # At 8:59 AM UTC → create stock rounds
    schedule.every().day.at("13:30").do(run_stock_open_rounds)

    # At 20:01 UTC (4:01 PM EST) → resolve stock rounds
    schedule.every().day.at("20:16").do(run_stock_close_resolution)

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
    symbols = {
        "BTC": "BTCUSDT",
        "ETH": "ETHUSDT",
        "SOL": "SOLUSDT",
        "BNB": "BNBUSDT",
        "XRP": "XRPUSDT",
        "ADA": "ADAUSDT",
        "DOGE": "DOGEUSDT",
        "DOT": "DOTUSDT",
        "AVAX": "AVAXUSDT"
    }

    prices = {}
    try:
        for symbol, pair in symbols.items():
            url = f"https://api.binance.com/api/v3/ticker/price?symbol={pair}"
            res = requests.get(url)
            data = res.json()
            prices[symbol] = {"usd": float(data["price"])}
            #print(prices)
        return prices
    except Exception as e:
        #print("❌ Error fetching prices from Binance:", e)
        return {}



def resolve_round(round_id, result):
    with get_db_cursor() as (cursor, conn):
        # ✅ First, fetch round info (needed for room and emit)
        cursor.execute("SELECT end_price, crypto FROM rounds WHERE id = %s", (round_id,))
        round_info = cursor.fetchone()
        room = f"{round_info['crypto']}-room"

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
                else:
                    loss = -bet['amount']
                    cursor.execute(
                        "UPDATE bets SET status = 'lost', profit = %s WHERE id = %s",
                        (loss, bet['id']))
                    socketio.emit("credits_update", {
                        "user_id": bet['user_id'],
                        "change": 0
                    }, room=room)

        # ✅ Emit final round resolution
        socketio.emit("round_resolved", {
            "round_id": round_id,
            "result": result,
            "crypto": round_info["crypto"],
            "end_price": round_info["end_price"]
        }, room=room)

        conn.commit()


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

            print(f"✅ New round for {symbol}: {start_time} → {end_time}")




def run_rounds_forever():
    interval = 150  # 120s round + 30s pause
    round_duration = 120
    pause_duration = 30

    # Align the first round to the nearest interval
    while True:
        now = int(time.time())
        aligned = now - (now % interval) + interval  # next round's start time
        sleep_time = aligned - now
        print(f"⏳ Sleeping {sleep_time}s until next global round at {datetime.utcfromtimestamp(aligned)}")
        time.sleep(sleep_time)

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
                    "INSERT INTO rounds (crypto, start_price, start_time, end_time) VALUES (%s, %s, %s, %s)",
                    (symbol, price, round_start, round_end)
                )

                room = f"{symbol}-room"
                socketio.emit("round_update", {
                    "crypto": symbol,
                    "start_price": price,
                    "start_time": round_start,
                    "end_time": round_end
                }, room=room)

        print(f"🚀 Round started at {round_start} and will end at {round_end}")
        time.sleep(round_duration)

        # At round end, fetch current price and resolve
        prices = get_all_prices()
        for symbol in CRYPTO_MAP.keys():
            with get_db_cursor() as (cursor, conn):
                cursor.execute("SELECT * FROM rounds WHERE crypto = %s ORDER BY id DESC LIMIT 1", (symbol,))
                round_data = cursor.fetchone()

                if not round_data or round_data["result"] is not None:
                    continue

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
                resolve_round(round_data["id"], result)

        print(f"✅ Round resolved. Pausing {pause_duration}s before next.")
        time.sleep(pause_duration)




@socketio.on("join")
def handle_join(data):
    crypto = data.get("crypto")
    if crypto:
        room = f"{crypto.upper()}-room"
        join_room(room)
        print(f"✅ User joined {room}")




@socketio.on("leave")
def handle_leave(data):
    crypto = data.get("crypto")
    if crypto:
        room = f"{crypto.upper()}-room"
        leave_room(room)
        print(f"👋 User left {room}")



if __name__ == "__main__":
    reset_and_init_db()
    reset_users_table()
    #init_db()
    threading.Thread(target=run_rounds_forever, daemon=True).start()
    threading.Thread(target=schedule_stock_tasks, daemon=True).start()
    #reset_and_init_db()
    #app.run(host="0.0.0.0", port=8080, debug=True)
    socketio.run(app, host="0.0.0.0", port=8080, debug=True) 

