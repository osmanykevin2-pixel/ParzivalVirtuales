import sqlite3
from datetime import datetime, timedelta
from config import DB_NAME

REFERRAL_REWARD_USDT = 0.30


def connect():
    return sqlite3.connect(DB_NAME)


def column_exists(cur, table, column):
    cur.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())


def add_column_if_missing(cur, table, column, definition):
    if not column_exists(cur, table, column):
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db():
    conn = connect()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        balance REAL DEFAULT 0,
        held_balance REAL DEFAULT 0,
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS deposits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        method TEXT,
        status TEXT DEFAULT 'pending',
        usdt_amount REAL DEFAULT 0,
        created_at TEXT,
        updated_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        service_name TEXT,
        country_name TEXT,
        public_price REAL,
        smspool_service TEXT,
        smspool_country TEXT,
        active INTEGER DEFAULT 1
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        product_id INTEGER,
        service_name TEXT,
        country_name TEXT,
        public_price REAL,
        phone_number TEXT,
        external_order_id TEXT,
        code TEXT,
        status TEXT,
        created_at TEXT,
        updated_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS support_tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        message_type TEXT,
        text_body TEXT,
        status TEXT DEFAULT 'open',
        created_at TEXT,
        updated_at TEXT
    )
    """)

    # Migraciones seguras para bases existentes.
    add_column_if_missing(cur, "users", "referred_by", "INTEGER")
    add_column_if_missing(cur, "users", "referral_rewarded", "INTEGER DEFAULT 0")
    add_column_if_missing(cur, "users", "referral_earnings", "REAL DEFAULT 0")

    add_column_if_missing(cur, "deposits", "proof_type", "TEXT")
    add_column_if_missing(cur, "deposits", "proof_file_id", "TEXT")
    add_column_if_missing(cur, "deposits", "proof_text", "TEXT")

    conn.commit()
    conn.close()
    seed_products()


def seed_products():
    conn = connect()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM products")
    count = cur.fetchone()[0]

    if count == 0:
        products = [
            ("WhatsApp", "Estados Unidos", 4.00, "whatsapp", "US", 1),
            ("WhatsApp", "Colombia", 3.00, "whatsapp", "CO", 1),
            ("Telegram", "Estados Unidos", 4.00, "telegram", "US", 1),
            ("Telegram", "Colombia", 3.00, "telegram", "CO", 1),
        ]

        cur.executemany("""
        INSERT INTO products (
            service_name, country_name, public_price,
            smspool_service, smspool_country, active
        ) VALUES (?, ?, ?, ?, ?, ?)
        """, products)

    conn.commit()
    conn.close()


def register_user(user, referred_by=None):
    conn = connect()
    cur = conn.cursor()

    cur.execute("SELECT user_id, referred_by FROM users WHERE user_id = ?", (user.id,))
    exists = cur.fetchone()

    now = datetime.now().isoformat()

    if not exists:
        valid_referrer = None

        if referred_by and int(referred_by) != int(user.id):
            cur.execute("SELECT user_id FROM users WHERE user_id = ?", (int(referred_by),))
            if cur.fetchone():
                valid_referrer = int(referred_by)

        cur.execute("""
        INSERT INTO users (
            user_id, username, first_name, balance, held_balance,
            created_at, referred_by, referral_rewarded, referral_earnings
        ) VALUES (?, ?, ?, 0, 0, ?, ?, 0, 0)
        """, (
            user.id,
            user.username or "",
            user.first_name or "",
            now,
            valid_referrer
        ))
    else:
        cur.execute("""
        UPDATE users SET username = ?, first_name = ? WHERE user_id = ?
        """, (user.username or "", user.first_name or "", user.id))

    conn.commit()
    conn.close()


def get_user(user_id):
    conn = connect()
    cur = conn.cursor()

    cur.execute("""
    SELECT user_id, username, first_name, balance, held_balance,
           referred_by, referral_rewarded, referral_earnings
    FROM users WHERE user_id = ?
    """, (user_id,))

    row = cur.fetchone()
    conn.close()
    return row


def get_balance(user_id):
    user = get_user(user_id)
    if not user:
        return 0.0, 0.0
    return float(user[3]), float(user[4])


def add_balance(user_id, amount):
    conn = connect()
    cur = conn.cursor()

    cur.execute("""
    UPDATE users SET balance = balance + ? WHERE user_id = ?
    """, (float(amount), user_id))

    conn.commit()
    conn.close()


def hold_balance(user_id, amount):
    balance, held = get_balance(user_id)
    amount = float(amount)

    if balance < amount:
        return False

    conn = connect()
    cur = conn.cursor()

    cur.execute("""
    UPDATE users
    SET balance = balance - ?, held_balance = held_balance + ?
    WHERE user_id = ?
    """, (amount, amount, user_id))

    conn.commit()
    conn.close()
    return True


def confirm_held_balance(user_id, amount):
    amount = float(amount)
    conn = connect()
    cur = conn.cursor()

    cur.execute("""
    UPDATE users
    SET held_balance = CASE
        WHEN held_balance >= ? THEN held_balance - ?
        ELSE 0
    END
    WHERE user_id = ?
    """, (amount, amount, user_id))

    conn.commit()
    conn.close()


def release_held_balance(user_id, amount):
    amount = float(amount)
    conn = connect()
    cur = conn.cursor()

    cur.execute("""
    UPDATE users
    SET balance = balance + ?,
        held_balance = CASE
            WHEN held_balance >= ? THEN held_balance - ?
            ELSE 0
        END
    WHERE user_id = ?
    """, (amount, amount, amount, user_id))

    conn.commit()
    conn.close()


def create_deposit(user_id, username, method):
    conn = connect()
    cur = conn.cursor()

    now = datetime.now().isoformat()

    cur.execute("""
    INSERT INTO deposits (user_id, username, method, status, created_at, updated_at)
    VALUES (?, ?, ?, 'waiting_proof', ?, ?)
    """, (user_id, username or "", method, now, now))

    deposit_id = cur.lastrowid
    conn.commit()
    conn.close()
    return deposit_id


def save_deposit_proof(deposit_id, proof_type=None, file_id=None, text=None):
    conn = connect()
    cur = conn.cursor()

    cur.execute("""
    UPDATE deposits
    SET proof_type = ?, proof_file_id = ?, proof_text = ?, status = 'pending', updated_at = ?
    WHERE id = ? AND status IN ('waiting_proof', 'pending')
    """, (proof_type, file_id, text or "", datetime.now().isoformat(), deposit_id))

    conn.commit()
    conn.close()


def get_deposit(deposit_id):
    conn = connect()
    cur = conn.cursor()

    cur.execute("""
    SELECT id, user_id, username, method, status, usdt_amount, created_at, updated_at,
           proof_type, proof_file_id, proof_text
    FROM deposits
    WHERE id = ?
    """, (deposit_id,))

    row = cur.fetchone()
    conn.close()
    return row


def get_pending_deposits():
    conn = connect()
    cur = conn.cursor()

    cur.execute("""
    SELECT id, user_id, username, method, status, created_at, proof_type
    FROM deposits
    WHERE status IN ('waiting_proof', 'pending')
    ORDER BY id DESC
    """)

    rows = cur.fetchall()
    conn.close()
    return rows


def approve_deposit(deposit_id, usdt_amount):
    conn = connect()
    cur = conn.cursor()

    cur.execute("""
    SELECT user_id FROM deposits WHERE id = ? AND status IN ('waiting_proof', 'pending')
    """, (deposit_id,))
    row = cur.fetchone()

    if not row:
        conn.close()
        return False

    user_id = row[0]
    now = datetime.now().isoformat()
    amount = float(usdt_amount)

    cur.execute("""
    UPDATE deposits
    SET status = 'approved', usdt_amount = ?, updated_at = ?
    WHERE id = ?
    """, (amount, now, deposit_id))

    cur.execute("""
    UPDATE users SET balance = balance + ? WHERE user_id = ?
    """, (amount, user_id))

    result = {
        "user_id": user_id,
        "referrer_id": None,
        "reward": 0.0
    }

    cur.execute("""
    SELECT referred_by, referral_rewarded
    FROM users
    WHERE user_id = ?
    """, (user_id,))
    user_row = cur.fetchone()

    if user_row:
        referrer_id, referral_rewarded = user_row
        if referrer_id and int(referrer_id) != int(user_id) and int(referral_rewarded or 0) == 0:
            reward = REFERRAL_REWARD_USDT

            cur.execute("""
            UPDATE users
            SET balance = balance + ?,
                referral_earnings = referral_earnings + ?
            WHERE user_id = ?
            """, (reward, reward, referrer_id))

            cur.execute("""
            UPDATE users
            SET referral_rewarded = 1
            WHERE user_id = ?
            """, (user_id,))

            result["referrer_id"] = referrer_id
            result["reward"] = reward

    conn.commit()
    conn.close()
    return result


def reject_deposit(deposit_id):
    conn = connect()
    cur = conn.cursor()

    cur.execute("""
    SELECT user_id FROM deposits WHERE id = ? AND status IN ('waiting_proof', 'pending')
    """, (deposit_id,))
    row = cur.fetchone()

    if not row:
        conn.close()
        return False

    user_id = row[0]
    now = datetime.now().isoformat()

    cur.execute("""
    UPDATE deposits
    SET status = 'rejected', updated_at = ?
    WHERE id = ?
    """, (now, deposit_id))

    conn.commit()
    conn.close()
    return {"user_id": user_id}


def get_active_products():
    conn = connect()
    cur = conn.cursor()

    cur.execute("""
    SELECT id, service_name, country_name, public_price
    FROM products
    WHERE active = 1
    ORDER BY service_name, country_name
    """)

    rows = cur.fetchall()
    conn.close()
    return rows


def get_product(product_id):
    conn = connect()
    cur = conn.cursor()

    cur.execute("""
    SELECT id, service_name, country_name, public_price, smspool_service, smspool_country, active
    FROM products
    WHERE id = ?
    """, (product_id,))

    row = cur.fetchone()
    conn.close()
    return row


def update_product_price(product_id, new_price):
    conn = connect()
    cur = conn.cursor()

    cur.execute("""
    UPDATE products SET public_price = ? WHERE id = ?
    """, (float(new_price), product_id))

    conn.commit()
    conn.close()


def create_order(user_id, username, product, status="created"):
    conn = connect()
    cur = conn.cursor()

    now = datetime.now().isoformat()

    cur.execute("""
    INSERT INTO orders (
        user_id, username, product_id, service_name, country_name,
        public_price, status, created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        username or "",
        product[0],
        product[1],
        product[2],
        float(product[3]),
        status,
        now,
        now
    ))

    order_id = cur.lastrowid
    conn.commit()
    conn.close()
    return order_id


def update_order_external(order_id, external_order_id=None, phone_number=None, status=None):
    conn = connect()
    cur = conn.cursor()

    fields = []
    values = []

    if external_order_id is not None:
        fields.append("external_order_id = ?")
        values.append(external_order_id)

    if phone_number is not None:
        fields.append("phone_number = ?")
        values.append(phone_number)

    if status is not None:
        fields.append("status = ?")
        values.append(status)

    fields.append("updated_at = ?")
    values.append(datetime.now().isoformat())

    values.append(order_id)
    sql = f"UPDATE orders SET {', '.join(fields)} WHERE id = ?"
    cur.execute(sql, values)

    conn.commit()
    conn.close()


def complete_order(order_id, code):
    conn = connect()
    cur = conn.cursor()

    cur.execute("""
    UPDATE orders
    SET code = ?, status = 'completed', updated_at = ?
    WHERE id = ? AND status IN ('waiting_code', 'processing')
    """, (code, datetime.now().isoformat(), order_id))

    conn.commit()
    conn.close()


def cancel_order(order_id):
    conn = connect()
    cur = conn.cursor()

    cur.execute("""
    UPDATE orders
    SET status = 'cancelled', updated_at = ?
    WHERE id = ?
    """, (datetime.now().isoformat(), order_id))

    conn.commit()
    conn.close()


def get_order(order_id):
    conn = connect()
    cur = conn.cursor()

    cur.execute("""
    SELECT id, user_id, username, product_id, service_name, country_name,
           public_price, phone_number, external_order_id, code, status
    FROM orders
    WHERE id = ?
    """, (order_id,))

    row = cur.fetchone()
    conn.close()
    return row


def get_user_active_orders(user_id):
    conn = connect()
    cur = conn.cursor()

    cur.execute("""
    SELECT id, service_name, country_name, public_price, phone_number, status, created_at
    FROM orders
    WHERE user_id = ?
    AND status IN ('waiting_code', 'processing')
    ORDER BY id DESC
    """, (user_id,))

    rows = cur.fetchall()
    conn.close()
    return rows


def get_user_orders(user_id, limit=10):
    conn = connect()
    cur = conn.cursor()

    cur.execute("""
    SELECT id, service_name, country_name, public_price, phone_number, code, status, created_at
    FROM orders
    WHERE user_id = ?
    ORDER BY id DESC
    LIMIT ?
    """, (user_id, int(limit)))

    rows = cur.fetchall()
    conn.close()
    return rows


def get_waiting_orders():
    conn = connect()
    cur = conn.cursor()

    cur.execute("""
    SELECT id, user_id, service_name, country_name, public_price,
           phone_number, external_order_id, created_at
    FROM orders
    WHERE status = 'waiting_code'
    AND external_order_id IS NOT NULL
    ORDER BY id ASC
    """)

    rows = cur.fetchall()
    conn.close()
    return rows


def order_is_expired(created_at, max_wait_minutes):
    try:
        created = datetime.fromisoformat(created_at)
    except Exception:
        return False

    return datetime.now() >= created + timedelta(minutes=int(max_wait_minutes))


def mark_order_refunded(order_id):
    conn = connect()
    cur = conn.cursor()

    cur.execute("""
    UPDATE orders
    SET status = 'refunded', updated_at = ?
    WHERE id = ? AND status IN ('waiting_code', 'processing')
    """, (datetime.now().isoformat(), order_id))

    conn.commit()
    conn.close()


def create_support_ticket(user_id, username, message_type, text):
    conn = connect()
    cur = conn.cursor()

    now = datetime.now().isoformat()

    cur.execute("""
    INSERT INTO support_tickets (user_id, username, message_type, text_body, status, created_at, updated_at)
    VALUES (?, ?, ?, ?, 'open', ?, ?)
    """, (user_id, username or "", message_type or "", text or "", now, now))

    ticket_id = cur.lastrowid
    conn.commit()
    conn.close()
    return ticket_id


def get_support_tickets(limit=10):
    conn = connect()
    cur = conn.cursor()

    cur.execute("""
    SELECT id, user_id, username, message_type, text_body, status, created_at
    FROM support_tickets
    ORDER BY id DESC
    LIMIT ?
    """, (int(limit),))

    rows = cur.fetchall()
    conn.close()
    return rows


def close_user_support_tickets(user_id):
    conn = connect()
    cur = conn.cursor()

    cur.execute("""
    UPDATE support_tickets
    SET status = 'closed', updated_at = ?
    WHERE user_id = ? AND status = 'open'
    """, (datetime.now().isoformat(), user_id))

    conn.commit()
    conn.close()


def get_referral_summary(user_id):
    conn = connect()
    cur = conn.cursor()

    cur.execute("""
    SELECT COUNT(*)
    FROM users
    WHERE referred_by = ?
    """, (user_id,))
    total = cur.fetchone()[0]

    cur.execute("""
    SELECT COUNT(*)
    FROM users
    WHERE referred_by = ? AND referral_rewarded = 1
    """, (user_id,))
    valid = cur.fetchone()[0]

    pending = total - valid

    cur.execute("""
    SELECT referral_earnings
    FROM users
    WHERE user_id = ?
    """, (user_id,))
    row = cur.fetchone()
    earnings = float(row[0]) if row and row[0] is not None else 0.0

    conn.close()

    return {
        "total": total,
        "pending": pending,
        "valid": valid,
        "earnings": earnings
    }
