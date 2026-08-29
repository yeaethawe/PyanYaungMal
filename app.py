import os
import secrets
import sqlite3
import string
from datetime import datetime, timezone
from functools import wraps

from authlib.integrations.base_client import OAuthError
from authlib.integrations.flask_client import OAuth
from flask import (
    Flask,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from translations import LANGUAGES, t

app = Flask(__name__, instance_relative_config=True)
app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY", "dev-only-change-me-in-production"
)
app.config["DATABASE"] = os.path.join(app.instance_path, "users.db")
app.config["ADMIN_KEY_COUNT"] = 5
app.config["ADMIN_KEY_LENGTH"] = 16
app.config["MAX_CONTENT_LENGTH"] = 48 * 1024 * 1024
app.config["AVATAR_FOLDER"] = os.path.join(app.instance_path, "avatars")
app.config["PRODUCT_FOLDER"] = os.path.join(app.instance_path, "products")
app.config["QR_FOLDER"] = os.path.join(app.instance_path, "qrs")
app.config["PAYMENT_FOLDER"] = os.path.join(app.instance_path, "payments")
app.config["MAX_PRODUCT_PHOTOS"] = 6
app.config["GOOGLE_CLIENT_ID"] = os.environ.get("GOOGLE_CLIENT_ID", "")
app.config["GOOGLE_CLIENT_SECRET"] = os.environ.get("GOOGLE_CLIENT_SECRET", "")
FOUNDER_ADMIN_EMAIL = "yeaethawe@gmail.com"

os.makedirs(app.instance_path, exist_ok=True)
os.makedirs(app.config["AVATAR_FOLDER"], exist_ok=True)
os.makedirs(app.config["PRODUCT_FOLDER"], exist_ok=True)
os.makedirs(app.config["QR_FOLDER"], exist_ok=True)
os.makedirs(app.config["PAYMENT_FOLDER"], exist_ok=True)

oauth = OAuth(app)
oauth.register(
    name="google",
    client_id=app.config["GOOGLE_CLIENT_ID"],
    client_secret=app.config["GOOGLE_CLIENT_SECRET"],
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

KEY_ALPHABET = string.ascii_uppercase + string.digits


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


def table_columns(table_name):
    return {
        row["name"]
        for row in get_db().execute(f"PRAGMA table_info({table_name})").fetchall()
    }


def generate_admin_key():
    return "".join(
        secrets.choice(KEY_ALPHABET) for _ in range(app.config["ADMIN_KEY_LENGTH"])
    )


def normalize_admin_key(raw):
    return "".join(ch for ch in (raw or "") if ch.isalnum()).upper()


def format_admin_key(key_code):
    return "-".join(key_code[i : i + 4] for i in range(0, len(key_code), 4))


def display_name(email):
    local = (email or "").split("@")[0]
    parts = [part for part in local.replace("_", ".").replace("-", ".").split(".") if part]
    if not parts:
        return email
    return " ".join(part.capitalize() for part in parts)


def format_short_date(value):
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(value).strftime("%b %d, %Y")
    except ValueError:
        return value[:10]


def format_message_time(value):
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value).strftime("%H:%M")
    except ValueError:
        return ""


def format_chat_day(value):
    if not value:
        return ""
    try:
        day = datetime.fromisoformat(value).date()
    except ValueError:
        return value[:10]
    today = datetime.now(timezone.utc).date()
    if day == today:
        return t("today")
    if (today - day).days == 1:
        return t("yesterday")
    return day.strftime("%b %d, %Y")


def seed_admin_keys():
    db = get_db()
    count = db.execute("SELECT COUNT(*) AS n FROM admin_keys").fetchone()["n"]
    if count:
        return
    keys = [generate_admin_key() for _ in range(app.config["ADMIN_KEY_COUNT"])]
    for key_code in keys:
        db.execute(
            "INSERT INTO admin_keys (key_code, created_at) VALUES (?, ?)",
            (key_code, utc_now()),
        )
    key_path = os.path.join(app.instance_path, "admin_keys.txt")
    with open(key_path, "w", encoding="utf-8") as handle:
        handle.write("Reusable 16-character admin keys\n")
        handle.write("These keys can be used by more than one person.\n\n")
        for key_code in keys:
            handle.write(f"{format_admin_key(key_code)}\n")
    db.commit()


def init_db():
    db = get_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            locked INTEGER NOT NULL DEFAULT 0,
            avatar_filename TEXT,
            auth_provider TEXT NOT NULL DEFAULT 'password',
            payment_qr_filename TEXT,
            language TEXT NOT NULL DEFAULT 'en'
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key_code TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL,
            read INTEGER NOT NULL DEFAULT 0,
            link TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            seller_id INTEGER NOT NULL,
            photo_filename TEXT NOT NULL,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'available',
            created_at TEXT NOT NULL,
            FOREIGN KEY (seller_id) REFERENCES users(id)
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS product_photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (product_id) REFERENCES products(id)
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            buyer_id INTEGER NOT NULL,
            seller_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            ended_at TEXT,
            UNIQUE (product_id, buyer_id),
            FOREIGN KEY (product_id) REFERENCES products(id),
            FOREIGN KEY (buyer_id) REFERENCES users(id),
            FOREIGN KEY (seller_id) REFERENCES users(id)
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            sender_id INTEGER NOT NULL,
            body TEXT,
            screenshot_filename TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id),
            FOREIGN KEY (sender_id) REFERENCES users(id)
        )
        """
    )
    columns = table_columns("users")
    if "role" not in columns:
        db.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")
    if "locked" not in columns:
        db.execute("ALTER TABLE users ADD COLUMN locked INTEGER NOT NULL DEFAULT 0")
    if "avatar_filename" not in columns:
        db.execute("ALTER TABLE users ADD COLUMN avatar_filename TEXT")
    if "auth_provider" not in columns:
        db.execute(
            "ALTER TABLE users ADD COLUMN auth_provider TEXT NOT NULL DEFAULT 'password'"
        )
    if "payment_qr_filename" not in columns:
        db.execute("ALTER TABLE users ADD COLUMN payment_qr_filename TEXT")
    if "language" not in columns:
        db.execute("ALTER TABLE users ADD COLUMN language TEXT NOT NULL DEFAULT 'en'")
    notify_columns = table_columns("notifications")
    if "link" not in notify_columns:
        db.execute("ALTER TABLE notifications ADD COLUMN link TEXT")
    conversation_columns = table_columns("conversations")
    if "ended_at" not in conversation_columns:
        db.execute("ALTER TABLE conversations ADD COLUMN ended_at TEXT")
    seed_product_photos()
    db.commit()
    seed_admin_keys()


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def get_user_by_id(user_id):
    return get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def get_user_by_email(email):
    return get_db().execute(
        "SELECT * FROM users WHERE email = ?",
        (email,),
    ).fetchone()


def is_founder_admin_email(email):
    return (email or "").strip().lower() == FOUNDER_ADMIN_EMAIL


def ensure_founder_admin(user):
    if user is None or not is_founder_admin_email(user["email"]):
        return user
    if user["role"] != "admin":
        set_user_role(user["id"], "admin")
        return get_user_by_id(user["id"])
    return user


def create_user(email, password_hash, auth_provider="password"):
    db = get_db()
    role = "admin" if is_founder_admin_email(email) else "user"
    cursor = db.execute(
        """
        INSERT INTO users (email, password_hash, created_at, role, locked, auth_provider)
        VALUES (?, ?, ?, ?, 0, ?)
        """,
        (email, password_hash, utc_now(), role, auth_provider),
    )
    db.commit()
    return cursor.lastrowid


def session_account_ids():
    raw_ids = session.get("account_ids") or []
    ids = []
    for value in raw_ids:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    current = session.get("user_id")
    if current is not None:
        try:
            current = int(current)
        except (TypeError, ValueError):
            current = None
    if current is not None and current not in ids:
        ids.append(current)
    return ids


def start_user_session(user_id):
    adding = bool(session.get("adding_account"))
    ids = session_account_ids() if adding else []
    if user_id not in ids:
        ids.append(user_id)
    lang = session.get("language")
    session.clear()
    session["account_ids"] = ids
    session["user_id"] = user_id
    if lang in LANGUAGES:
        session["language"] = lang
    user = ensure_founder_admin(get_user_by_id(user_id))
    if user is not None and "language" in user.keys() and user["language"] in LANGUAGES:
        session["language"] = user["language"]


def set_user_language(user_id, language):
    db = get_db()
    db.execute("UPDATE users SET language = ? WHERE id = ?", (language, user_id))
    db.commit()


def load_session_accounts():
    accounts = []
    valid_ids = []
    for user_id in session_account_ids():
        user = get_user_by_id(user_id)
        if user is None or user["locked"]:
            continue
        valid_ids.append(user["id"])
        accounts.append(user)
    session["account_ids"] = valid_ids
    return accounts


def google_sign_in_ready():
    return bool(app.config["GOOGLE_CLIENT_ID"] and app.config["GOOGLE_CLIENT_SECRET"])


def list_users():
    return get_db().execute(
        """
        SELECT id, email, role, locked, created_at, avatar_filename
        FROM users
        ORDER BY created_at ASC
        """
    ).fetchall()


def list_admin_keys():
    return get_db().execute(
        "SELECT id, key_code, created_at FROM admin_keys ORDER BY id ASC"
    ).fetchall()


def find_admin_key(key_code):
    return get_db().execute(
        "SELECT id FROM admin_keys WHERE key_code = ?",
        (key_code,),
    ).fetchone()


def set_user_role(user_id, role):
    db = get_db()
    db.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
    db.commit()


def set_user_locked(user_id, locked):
    db = get_db()
    db.execute("UPDATE users SET locked = ? WHERE id = ?", (1 if locked else 0, user_id))
    db.commit()


def user_avatar_url(user):
    if user is None:
        return None
    filename = user["avatar_filename"] if "avatar_filename" in user.keys() else None
    if not filename:
        return None
    return url_for("avatar_file", filename=filename)


def remove_stored_file(folder, filename):
    if not filename:
        return
    path = os.path.join(folder, filename)
    if os.path.isfile(path):
        os.remove(path)


def remove_avatar_file(filename):
    remove_stored_file(app.config["AVATAR_FOLDER"], filename)


def save_uploaded_image(file_storage, folder, prefix):
    if file_storage is None or not file_storage.filename:
        return None
    extension = detect_image_extension(file_storage)
    if extension is None:
        return None
    filename = f"{prefix}_{secrets.token_hex(8)}{extension}"
    file_storage.save(os.path.join(folder, filename))
    return filename


def product_photo_url(filename):
    if not filename:
        return None
    return url_for("product_photo", filename=filename)


def seed_product_photos():
    db = get_db()
    missing = db.execute(
        """
        SELECT products.id, products.photo_filename
        FROM products
        LEFT JOIN product_photos ON product_photos.product_id = products.id
        WHERE product_photos.id IS NULL AND products.photo_filename IS NOT NULL
        """
    ).fetchall()
    for row in missing:
        db.execute(
            """
            INSERT INTO product_photos (product_id, filename, sort_order)
            VALUES (?, ?, 0)
            """,
            (row["id"], row["photo_filename"]),
        )


def list_product_photos(product_id, cover_filename=None):
    rows = get_db().execute(
        """
        SELECT id, product_id, filename, sort_order
        FROM product_photos
        WHERE product_id = ?
        ORDER BY sort_order, id
        """,
        (product_id,),
    ).fetchall()
    if rows:
        return rows
    if cover_filename:
        return [
            {
                "id": None,
                "product_id": product_id,
                "filename": cover_filename,
                "sort_order": 0,
            }
        ]
    return []


def photos_grouped(products):
    mapping = {}
    if not products:
        return mapping
    ids = [product["id"] for product in products]
    placeholders = ",".join("?" * len(ids))
    rows = get_db().execute(
        f"""
        SELECT id, product_id, filename, sort_order
        FROM product_photos
        WHERE product_id IN ({placeholders})
        ORDER BY sort_order, id
        """,
        ids,
    ).fetchall()
    for row in rows:
        mapping.setdefault(row["product_id"], []).append(row)
    for product in products:
        if product["id"] not in mapping and product["photo_filename"]:
            mapping[product["id"]] = list_product_photos(
                product["id"], product["photo_filename"]
            )
    return mapping


def add_product_photos(product_id, filenames):
    if not filenames:
        return
    db = get_db()
    start = db.execute(
        "SELECT COALESCE(MAX(sort_order), -1) AS n FROM product_photos WHERE product_id = ?",
        (product_id,),
    ).fetchone()["n"]
    for index, filename in enumerate(filenames, start=start + 1):
        db.execute(
            """
            INSERT INTO product_photos (product_id, filename, sort_order)
            VALUES (?, ?, ?)
            """,
            (product_id, filename, index),
        )
    db.commit()
    refresh_cover_photo(product_id)


def refresh_cover_photo(product_id):
    db = get_db()
    first = db.execute(
        """
        SELECT filename FROM product_photos
        WHERE product_id = ?
        ORDER BY sort_order, id
        LIMIT 1
        """,
        (product_id,),
    ).fetchone()
    if first is not None:
        db.execute(
            "UPDATE products SET photo_filename = ? WHERE id = ?",
            (first["filename"], product_id),
        )
        db.commit()


def delete_product_photo_row(photo):
    db = get_db()
    db.execute("DELETE FROM product_photos WHERE id = ?", (photo["id"],))
    db.commit()
    remove_stored_file(app.config["PRODUCT_FOLDER"], photo["filename"])


def payment_qr_url(user):
    if user is None:
        return None
    filename = user["payment_qr_filename"] if "payment_qr_filename" in user.keys() else None
    if not filename:
        return None
    return url_for("qr_file", filename=filename)


def format_price(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if number.is_integer():
        return f"{int(number):,} MMK"
    return f"{number:,.2f} MMK"


def set_user_password(user_id, password_hash):
    db = get_db()
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))
    db.commit()


def set_user_avatar(user_id, filename):
    db = get_db()
    db.execute("UPDATE users SET avatar_filename = ? WHERE id = ?", (filename, user_id))
    db.commit()


def detect_image_extension(file_storage):
    header = file_storage.stream.read(16)
    file_storage.stream.seek(0)
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if header.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if header[:6] in {b"GIF87a", b"GIF89a"}:
        return ".gif"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return ".webp"
    return None


def delete_user(user_id):
    db = get_db()
    row = db.execute(
        "SELECT avatar_filename FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if row is not None:
        remove_avatar_file(row["avatar_filename"])
    db.execute("DELETE FROM notifications WHERE user_id = ?", (user_id,))
    db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.commit()


def create_notification(user_id, message, link=None):
    db = get_db()
    db.execute(
        """
        INSERT INTO notifications (user_id, message, created_at, read, link)
        VALUES (?, ?, ?, 0, ?)
        """,
        (user_id, message, utc_now(), link),
    )
    db.commit()


def list_notifications(user_id):
    return get_db().execute(
        """
        SELECT id, message, created_at, read, link
        FROM notifications
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        (user_id,),
    ).fetchall()


def list_products(query=None):
    sql = """
        SELECT products.*, users.email AS seller_email
        FROM products
        JOIN users ON users.id = products.seller_id
        WHERE products.status = 'available'
    """
    params = []
    if query:
        sql += " AND (products.name LIKE ? OR products.description LIKE ?)"
        like = f"%{query}%"
        params.extend([like, like])
    sql += " ORDER BY products.id DESC"
    return get_db().execute(sql, params).fetchall()


def list_seller_products(seller_id):
    return get_db().execute(
        """
        SELECT * FROM products
        WHERE seller_id = ?
        ORDER BY id DESC
        """,
        (seller_id,),
    ).fetchall()


def get_product(product_id):
    return get_db().execute(
        """
        SELECT products.*, users.email AS seller_email,
               users.payment_qr_filename AS seller_qr
        FROM products
        JOIN users ON users.id = products.seller_id
        WHERE products.id = ?
        """,
        (product_id,),
    ).fetchone()


def create_product(seller_id, photo_filename, name, price, description):
    db = get_db()
    cursor = db.execute(
        """
        INSERT INTO products (seller_id, photo_filename, name, price, description, status, created_at)
        VALUES (?, ?, ?, ?, ?, 'available', ?)
        """,
        (seller_id, photo_filename, name, price, description, utc_now()),
    )
    db.commit()
    return cursor.lastrowid


def update_product(product_id, name, price, description, photo_filename=None):
    db = get_db()
    if photo_filename:
        db.execute(
            """
            UPDATE products
            SET name = ?, price = ?, description = ?, photo_filename = ?
            WHERE id = ?
            """,
            (name, price, description, photo_filename, product_id),
        )
    else:
        db.execute(
            """
            UPDATE products
            SET name = ?, price = ?, description = ?
            WHERE id = ?
            """,
            (name, price, description, product_id),
        )
    db.commit()


def close_product(product):
    db = get_db()
    db.execute(
        "UPDATE products SET status = 'sold' WHERE id = ?",
        (product["id"],),
    )
    now = utc_now()
    db.execute(
        """
        UPDATE conversations
        SET ended_at = COALESCE(ended_at, ?)
        WHERE product_id = ?
        """,
        (now, product["id"]),
    )
    conversations = db.execute(
        "SELECT id, buyer_id FROM conversations WHERE product_id = ?",
        (product["id"],),
    ).fetchall()
    db.commit()
    for conversation in conversations:
        create_notification(
            conversation["buyer_id"],
            f"{product['name']} was marked sold out and removed from Explore.",
            url_for("chat_detail", conversation_id=conversation["id"]),
        )


def conversation_is_ended(conversation):
    if conversation is None:
        return True
    ended = conversation["ended_at"] if "ended_at" in conversation.keys() else None
    return bool(ended) or conversation["product_status"] == "sold"


def buyer_sent_payment_screenshot(conversation):
    row = get_db().execute(
        """
        SELECT 1
        FROM messages
        WHERE conversation_id = ?
          AND sender_id = ?
          AND screenshot_filename IS NOT NULL
        LIMIT 1
        """,
        (conversation["id"], conversation["buyer_id"]),
    ).fetchone()
    return row is not None


def delete_product(product):
    db = get_db()
    shots = db.execute(
        """
        SELECT messages.screenshot_filename
        FROM messages
        JOIN conversations ON conversations.id = messages.conversation_id
        WHERE conversations.product_id = ? AND messages.screenshot_filename IS NOT NULL
        """,
        (product["id"],),
    ).fetchall()
    for shot in shots:
        remove_stored_file(app.config["PAYMENT_FOLDER"], shot["screenshot_filename"])
    db.execute(
        """
        DELETE FROM messages
        WHERE conversation_id IN (
            SELECT id FROM conversations WHERE product_id = ?
        )
        """,
        (product["id"],),
    )
    db.execute("DELETE FROM conversations WHERE product_id = ?", (product["id"],))
    photos = list_product_photos(product["id"], product["photo_filename"])
    db.execute("DELETE FROM product_photos WHERE product_id = ?", (product["id"],))
    db.execute("DELETE FROM products WHERE id = ?", (product["id"],))
    db.commit()
    seen = set()
    for photo in photos:
        filename = photo["filename"]
        if filename and filename not in seen:
            seen.add(filename)
            remove_stored_file(app.config["PRODUCT_FOLDER"], filename)


def seller_owns_product(product, user_id):
    return product is not None and product["seller_id"] == user_id


def parse_product_form(require_photo=False):
    name = (request.form.get("name") or "").strip()
    price_raw = (request.form.get("price") or "").strip()
    description = (request.form.get("description") or "").strip()
    uploads = request.files.getlist("photos")
    if not uploads:
        uploads = request.files.getlist("photo")
    try:
        price = float(price_raw)
    except ValueError:
        price = None
    photo_filenames = []
    for item in uploads:
        if len(photo_filenames) >= app.config["MAX_PRODUCT_PHOTOS"]:
            break
        saved = save_uploaded_image(
            item, app.config["PRODUCT_FOLDER"], f"p{g.user['id']}"
        )
        if saved:
            photo_filenames.append(saved)
    if require_photo and not photo_filenames:
        return None, "Upload at least one product photo."
    if not name:
        return None, "Enter the name of the thing."
    if price is None or price <= 0:
        return None, "Enter a price greater than 0."
    if not description:
        return None, "Write a description."
    return {
        "name": name,
        "price": price,
        "description": description,
        "photo_filename": photo_filenames[0] if photo_filenames else None,
        "photo_filenames": photo_filenames,
    }, None


def get_or_create_conversation(product, buyer_id):
    db = get_db()
    existing = db.execute(
        """
        SELECT * FROM conversations
        WHERE product_id = ? AND buyer_id = ?
        """,
        (product["id"], buyer_id),
    ).fetchone()
    if existing is not None:
        return existing
    cursor = db.execute(
        """
        INSERT INTO conversations (product_id, buyer_id, seller_id, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (product["id"], buyer_id, product["seller_id"], utc_now()),
    )
    db.commit()
    return db.execute(
        "SELECT * FROM conversations WHERE id = ?",
        (cursor.lastrowid,),
    ).fetchone()


def get_conversation(conversation_id):
    return get_db().execute(
        """
        SELECT conversations.*, products.name AS product_name,
               products.photo_filename AS product_photo,
               products.price AS product_price,
               products.description AS product_description,
               products.status AS product_status,
               buyer.email AS buyer_email,
               seller.email AS seller_email,
               seller.payment_qr_filename AS seller_qr
        FROM conversations
        JOIN products ON products.id = conversations.product_id
        JOIN users AS buyer ON buyer.id = conversations.buyer_id
        JOIN users AS seller ON seller.id = conversations.seller_id
        WHERE conversations.id = ?
        """,
        (conversation_id,),
    ).fetchone()


def list_user_conversations(user_id):
    return get_db().execute(
        """
        SELECT conversations.*, products.name AS product_name,
               products.photo_filename AS product_photo,
               products.price AS product_price,
               products.status AS product_status,
               buyer.email AS buyer_email,
               seller.email AS seller_email,
               (
                   SELECT body FROM messages
                   WHERE messages.conversation_id = conversations.id
                   ORDER BY messages.id DESC LIMIT 1
               ) AS last_body
        FROM conversations
        JOIN products ON products.id = conversations.product_id
        JOIN users AS buyer ON buyer.id = conversations.buyer_id
        JOIN users AS seller ON seller.id = conversations.seller_id
        WHERE conversations.buyer_id = ? OR conversations.seller_id = ?
        ORDER BY conversations.id DESC
        """,
        (user_id, user_id),
    ).fetchall()


def list_messages(conversation_id):
    return get_db().execute(
        """
        SELECT messages.*, users.email AS sender_email
        FROM messages
        JOIN users ON users.id = messages.sender_id
        WHERE messages.conversation_id = ?
        ORDER BY messages.id ASC
        """,
        (conversation_id,),
    ).fetchall()


def list_messages_after(conversation_id, after_id):
    return get_db().execute(
        """
        SELECT messages.*, users.email AS sender_email
        FROM messages
        JOIN users ON users.id = messages.sender_id
        WHERE messages.conversation_id = ? AND messages.id > ?
        ORDER BY messages.id ASC
        """,
        (conversation_id, after_id),
    ).fetchall()


def get_message(message_id):
    return get_db().execute(
        """
        SELECT messages.*, users.email AS sender_email
        FROM messages
        JOIN users ON users.id = messages.sender_id
        WHERE messages.id = ?
        """,
        (message_id,),
    ).fetchone()


def serialize_message(item, user_id):
    filename = item["screenshot_filename"]
    return {
        "id": item["id"],
        "sender_id": item["sender_id"],
        "mine": item["sender_id"] == user_id,
        "body": item["body"] or "",
        "day": format_chat_day(item["created_at"]),
        "time": format_message_time(item["created_at"]),
        "photo_url": url_for("payment_file", filename=filename) if filename else None,
        "photo_alt": t("chat.photo"),
    }


def chat_state(conversation):
    ended = conversation_is_ended(conversation)
    is_seller = g.user["id"] == conversation["seller_id"]
    return {
        "ended": ended,
        "can_end_sale": (
            is_seller
            and not ended
            and conversation["product_status"] == "available"
            and buyer_sent_payment_screenshot(conversation)
        ),
    }


def wants_json():
    accept = request.headers.get("Accept") or ""
    return "application/json" in accept


def add_message(conversation_id, sender_id, body, screenshot_filename=None):
    db = get_db()
    cursor = db.execute(
        """
        INSERT INTO messages (conversation_id, sender_id, body, screenshot_filename, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (conversation_id, sender_id, body, screenshot_filename, utc_now()),
    )
    db.commit()
    return cursor.lastrowid


def user_in_conversation(conversation, user_id):
    return conversation is not None and user_id in {
        conversation["buyer_id"],
        conversation["seller_id"],
    }


def dismiss_notification(notification_id, user_id):
    db = get_db()
    db.execute(
        "UPDATE notifications SET read = 1 WHERE id = ? AND user_id = ?",
        (notification_id, user_id),
    )
    db.commit()


def dismiss_all_notifications(user_id):
    db = get_db()
    db.execute(
        "UPDATE notifications SET read = 1 WHERE user_id = ?",
        (user_id,),
    )
    db.commit()


def is_valid_email(email):
    return bool(email) and "@" in email and " " not in email


def is_admin(user):
    return user is not None and user["role"] == "admin"


@app.context_processor
def inject_template_helpers():
    return {
        "display_name": display_name,
        "user_avatar_url": user_avatar_url,
        "google_sign_in_ready": google_sign_in_ready(),
        "product_photo_url": product_photo_url,
        "payment_qr_url": payment_qr_url,
        "format_price": format_price,
        "format_short_date": format_short_date,
        "format_message_time": format_message_time,
        "format_chat_day": format_chat_day,
        "t": t,
    }


@app.before_request
def load_logged_in_user():
    init_db()
    g.accounts = load_session_accounts()
    g.adding_account = bool(session.get("adding_account"))
    user_id = session.get("user_id")
    try:
        user_id = int(user_id) if user_id is not None else None
    except (TypeError, ValueError):
        user_id = None

    current = next((account for account in g.accounts if account["id"] == user_id), None)
    if current is None and user_id is not None:
        gone = get_user_by_id(user_id)
        if gone is not None and gone["locked"] and request.endpoint not in {"static", "service_worker"}:
            flash("Your account has been locked.", "error")
        current = g.accounts[0] if g.accounts else None

    g.user = current
    if g.user is not None:
        g.user = ensure_founder_admin(g.user)
        g.accounts = [
            g.user if account["id"] == g.user["id"] else account
            for account in g.accounts
        ]
        session["user_id"] = g.user["id"]
        stored = g.user["language"] if "language" in g.user.keys() else None
        if stored in LANGUAGES:
            session["language"] = stored
    else:
        session.pop("user_id", None)
        if not g.adding_account:
            session.pop("account_ids", None)
    g.language = session.get("language") if session.get("language") in LANGUAGES else "en"
    g.notifications = list_notifications(g.user["id"]) if g.user is not None else []
    g.unread_count = sum(1 for item in g.notifications if not item["read"])


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            flash("Please log in first, or continue with Google.", "error")
            return redirect(url_for("index"))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            flash("Please log in first, or continue with Google.", "error")
            return redirect(url_for("index"))
        if not is_admin(g.user):
            flash("Admin access is required.", "error")
            return redirect(url_for("home"))
        return view(*args, **kwargs)

    return wrapped


def redirect_if_logged_in(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is not None and not session.get("adding_account"):
            return redirect(url_for("home"))
        return view(*args, **kwargs)

    return wrapped


def admin_target_or_redirect(user_id):
    target = get_user_by_id(user_id)
    if target is None:
        flash("That account was not found.", "error")
        return None
    if target["id"] == g.user["id"]:
        flash("You cannot change your own account from this list.", "error")
        return None
    return target


@app.route("/")
def index():
    return render_template("home.html")


@app.route("/signup", methods=["GET", "POST"])
@redirect_if_logged_in
def signup():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        confirm_password = request.form.get("confirm_password") or ""
        error = None

        if not is_valid_email(email):
            error = "Enter a valid email address."
        elif len(password) < 8:
            error = "Password must be at least 8 characters."
        elif password != confirm_password:
            error = "Passwords do not match."
        elif get_user_by_email(email) is not None:
            error = "An account with that email already exists."

        if error is None:
            user_id = create_user(email, generate_password_hash(password))
            start_user_session(user_id)
            flash("Your account was created.", "success")
            return redirect(url_for("home"))

        flash(error, "error")

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
@redirect_if_logged_in
def login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = get_user_by_email(email)

        if user is None:
            flash("Invalid email or password.", "error")
        elif user["auth_provider"] == "google" if "auth_provider" in user.keys() else False:
            flash("This account uses Google. Please continue with Google.", "error")
        elif not check_password_hash(user["password_hash"], password):
            flash("Invalid email or password.", "error")
        elif user["locked"]:
            flash("This account is locked.", "error")
        else:
            start_user_session(user["id"])
            flash(f"Signed in as {user['email']}.", "success")
            return redirect(url_for("home"))

    return render_template("login.html")


@app.route("/accounts/add", methods=["POST"])
@login_required
def add_account():
    session["adding_account"] = True
    return redirect(url_for("login"))


@app.route("/accounts/cancel", methods=["POST"])
def cancel_add_account():
    session["adding_account"] = False
    if session.get("user_id"):
        return redirect(url_for("home"))
    return redirect(url_for("login"))


@app.route("/accounts/switch/<int:user_id>", methods=["POST"])
@login_required
def switch_account(user_id):
    if user_id not in session_account_ids():
        flash("That account is not signed in on this device.", "error")
        return redirect(request.referrer or url_for("home"))
    user = get_user_by_id(user_id)
    if user is None or user["locked"]:
        flash("That account is not available.", "error")
        return redirect(request.referrer or url_for("home"))
    session["user_id"] = user["id"]
    flash(f"Switched to {user['email']}.", "success")
    return redirect(url_for("home"))


@app.route("/auth/google")
def google_login():
    if g.user is not None and not session.get("adding_account"):
        return redirect(url_for("home"))
    if not google_sign_in_ready():
        flash("Google sign-in is not set up yet. Please log in with email first.", "error")
        return redirect(url_for("login"))
    return oauth.google.authorize_redirect(url_for("google_callback", _external=True))


@app.route("/auth/google/callback")
def google_callback():
    if not google_sign_in_ready():
        flash("Google sign-in is not set up yet. Please log in with email first.", "error")
        return redirect(url_for("login"))
    try:
        token = oauth.google.authorize_access_token()
    except OAuthError:
        flash("Google sign-in was cancelled or failed.", "error")
        return redirect(url_for("login"))
    profile = token.get("userinfo") or {}
    email = (profile.get("email") or "").strip().lower()
    if not is_valid_email(email):
        flash("Google did not share a usable email address.", "error")
        return redirect(url_for("login"))

    user = get_user_by_email(email)
    if user is None:
        user_id = create_user(
            email,
            generate_password_hash(secrets.token_urlsafe(32)),
            auth_provider="google",
        )
        start_user_session(user_id)
        flash("Signed in with Google.", "success")
        return redirect(url_for("home"))
    if user["locked"]:
        flash("This account is locked.", "error")
        return redirect(url_for("login"))
    start_user_session(user["id"])
    flash("Signed in with Google.", "success")
    return redirect(url_for("home"))


@app.route("/home")
def home():
    return render_template("home.html")


@app.route("/upgrade", methods=["POST"])
@login_required
def upgrade():
    if is_admin(g.user):
        return redirect(url_for("settings"))

    key_code = normalize_admin_key(request.form.get("admin_key"))
    if len(key_code) != app.config["ADMIN_KEY_LENGTH"]:
        flash("Enter a 16-character admin key.", "error")
        return redirect(url_for("settings"))
    if find_admin_key(key_code) is None:
        flash("That admin key is not valid.", "error")
        return redirect(url_for("settings"))

    set_user_role(g.user["id"], "admin")
    flash("Your account is now an admin account.", "success")
    return redirect(url_for("settings"))


@app.route("/settings")
@login_required
def settings():
    return render_template("settings.html")


@app.route("/settings/language", methods=["POST"])
@login_required
def settings_language():
    language = (request.form.get("language") or "").strip()
    if language not in LANGUAGES:
        flash(t("error"), "error")
        return redirect(url_for("settings"))
    set_user_language(g.user["id"], language)
    session["language"] = language
    g.language = language
    flash(t("language.saved"), "success")
    return redirect(url_for("settings"))


@app.route("/settings/password", methods=["POST"])
@login_required
def settings_password():
    current_password = request.form.get("current_password") or ""
    new_password = request.form.get("new_password") or ""
    confirm_password = request.form.get("confirm_password") or ""
    google_only = g.user["auth_provider"] == "google"

    if not google_only and not check_password_hash(g.user["password_hash"], current_password):
        flash("Current password is not correct.", "error")
    elif len(new_password) < 8:
        flash("New password must be at least 8 characters.", "error")
    elif new_password != confirm_password:
        flash("New passwords do not match.", "error")
    else:
        set_user_password(g.user["id"], generate_password_hash(new_password))
        if google_only:
            get_db().execute(
                "UPDATE users SET auth_provider = ? WHERE id = ?",
                ("password", g.user["id"]),
            )
            get_db().commit()
        flash("Your password was updated.", "success")
    return redirect(url_for("settings"))


@app.route("/settings/avatar", methods=["POST"])
@login_required
def settings_avatar():
    uploaded = request.files.get("avatar")
    if uploaded is None or not uploaded.filename:
        flash("Choose a profile picture to upload.", "error")
        return redirect(url_for("settings"))

    extension = detect_image_extension(uploaded)
    if extension is None:
        flash("Use a JPG, PNG, WEBP, or GIF image.", "error")
        return redirect(url_for("settings"))

    filename = f"{g.user['id']}_{secrets.token_hex(8)}{extension}"
    destination = os.path.join(app.config["AVATAR_FOLDER"], filename)
    uploaded.save(destination)
    remove_avatar_file(g.user["avatar_filename"])
    set_user_avatar(g.user["id"], filename)
    flash("Your profile picture was updated.", "success")
    return redirect(url_for("settings"))


@app.route("/settings/qr", methods=["POST"])
@login_required
def settings_qr():
    uploaded = request.files.get("payment_qr")
    filename = save_uploaded_image(uploaded, app.config["QR_FOLDER"], f"qr{g.user['id']}")
    if filename is None:
        flash("Upload a JPG, PNG, WEBP, or GIF payment QR code.", "error")
        return redirect(url_for("settings"))
    old_name = g.user["payment_qr_filename"] if "payment_qr_filename" in g.user.keys() else None
    remove_stored_file(app.config["QR_FOLDER"], old_name)
    db = get_db()
    db.execute(
        "UPDATE users SET payment_qr_filename = ? WHERE id = ?",
        (filename, g.user["id"]),
    )
    db.commit()
    flash("Your payment QR code was saved.", "success")
    return redirect(url_for("settings"))


@app.route("/avatars/<filename>")
@login_required
def avatar_file(filename):
    if not filename or "/" in filename or "\\" in filename:
        abort(404)
    return send_from_directory(app.config["AVATAR_FOLDER"], filename)


@app.route("/media/products/<filename>")
def product_photo(filename):
    if not filename or "/" in filename or "\\" in filename:
        abort(404)
    return send_from_directory(app.config["PRODUCT_FOLDER"], filename)


@app.route("/media/qrs/<filename>")
@login_required
def qr_file(filename):
    if not filename or "/" in filename or "\\" in filename:
        abort(404)
    return send_from_directory(app.config["QR_FOLDER"], filename)


@app.route("/media/payments/<filename>")
@login_required
def payment_file(filename):
    if not filename or "/" in filename or "\\" in filename:
        abort(404)
    row = get_db().execute(
        """
        SELECT conversations.buyer_id, conversations.seller_id
        FROM messages
        JOIN conversations ON conversations.id = messages.conversation_id
        WHERE messages.screenshot_filename = ?
        """,
        (filename,),
    ).fetchone()
    if row is None or g.user["id"] not in {row["buyer_id"], row["seller_id"]}:
        abort(404)
    return send_from_directory(app.config["PAYMENT_FOLDER"], filename)


@app.route("/explore")
@login_required
def explore():
    query = (request.args.get("q") or "").strip()
    products = list_products(query or None)
    return render_template(
        "explore.html",
        products=products,
        photos_by_id=photos_grouped(products),
        query=query,
    )


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    if request.method == "POST":
        data, error = parse_product_form(require_photo=True)
        if error:
            flash(error, "error")
        else:
            product_id = create_product(
                g.user["id"],
                data["photo_filename"],
                data["name"],
                data["price"],
                data["description"],
            )
            add_product_photos(product_id, data["photo_filenames"])
            flash("Your used product is now listed in Explore.", "success")
            return redirect(url_for("manage_products"))

    return render_template(
        "sell.html",
        listings=list_seller_products(g.user["id"]),
    )


@app.route("/products/manage")
@login_required
def manage_products():
    listings = list_seller_products(g.user["id"])
    return render_template(
        "manage_products.html",
        listings=listings,
        photos_by_id=photos_grouped(listings),
    )


@app.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@login_required
def edit_product(product_id):
    product = get_product(product_id)
    if not seller_owns_product(product, g.user["id"]):
        flash("You can only edit your own products.", "error")
        return redirect(url_for("manage_products"))

    if request.method == "POST":
        data, error = parse_product_form(require_photo=False)
        if error:
            flash(error, "error")
        else:
            existing = list_product_photos(product["id"], product["photo_filename"])
            remove_ids = {value for value in request.form.getlist("remove_photo") if value}
            kept = [
                photo
                for photo in existing
                if photo["id"] is None or str(photo["id"]) not in remove_ids
            ]
            new_files = data["photo_filenames"]
            if len(kept) + len(new_files) > app.config["MAX_PRODUCT_PHOTOS"]:
                for filename in new_files:
                    remove_stored_file(app.config["PRODUCT_FOLDER"], filename)
                flash("You can add up to 6 photos.", "error")
            elif not kept and not new_files:
                flash("Keep at least one product photo.", "error")
            else:
                for photo in existing:
                    if photo["id"] is not None and str(photo["id"]) in remove_ids:
                        delete_product_photo_row(photo)
                add_product_photos(product["id"], new_files)
                update_product(
                    product["id"],
                    data["name"],
                    data["price"],
                    data["description"],
                )
                refresh_cover_photo(product["id"])
                flash("Your product was updated.", "success")
                return redirect(url_for("manage_products"))

    return render_template(
        "edit_product.html",
        product=product,
        photos=list_product_photos(product["id"], product["photo_filename"]),
    )


@app.route("/products/<int:product_id>/close", methods=["POST"])
@login_required
def close_product_route(product_id):
    product = get_product(product_id)
    if not seller_owns_product(product, g.user["id"]):
        flash("You can only close your own products.", "error")
        return redirect(url_for("manage_products"))
    if product["status"] != "available":
        flash("That listing is already closed.", "error")
        return redirect(url_for("manage_products"))
    close_product(product)
    flash(f"{product['name']} is closed. It is hidden from Explore and kept in Your products.", "success")
    return redirect(url_for("manage_products"))


@app.route("/products/<int:product_id>/delete", methods=["POST"])
@login_required
def delete_product_route(product_id):
    product = get_product(product_id)
    if not seller_owns_product(product, g.user["id"]):
        flash("You can only delete your own products.", "error")
        return redirect(url_for("manage_products"))
    delete_product(product)
    flash(f"{product['name']} was deleted.", "success")
    return redirect(url_for("manage_products"))


@app.route("/products/<int:product_id>/buy", methods=["POST"])
@login_required
def buy_product(product_id):
    product = get_product(product_id)
    if product is None or product["status"] != "available":
        flash("That product is not available.", "error")
        return redirect(url_for("explore"))
    if product["seller_id"] == g.user["id"]:
        flash("You cannot buy your own product.", "error")
        return redirect(url_for("explore"))

    conversation = get_or_create_conversation(product, g.user["id"])
    chat_url = url_for("chat_detail", conversation_id=conversation["id"])
    create_notification(
        product["seller_id"],
        f"{g.user['email']} is going to buy your {product['name']}. Open the chat to talk about price and payment.",
        chat_url,
    )
    add_message(
        conversation["id"],
        g.user["id"],
        f"I want to buy {product['name']}. Let's talk about the price and payment.",
    )
    flash("The seller was notified. You can now chat about price and payment.", "success")
    return redirect(chat_url)


@app.route("/chats")
@login_required
def chats():
    return render_template("chats.html", conversations=list_user_conversations(g.user["id"]))


@app.route("/chats/<int:conversation_id>", methods=["GET", "POST"])
@login_required
def chat_detail(conversation_id):
    conversation = get_conversation(conversation_id)
    if not user_in_conversation(conversation, g.user["id"]):
        flash("That chat was not found.", "error")
        return redirect(url_for("chats"))

    if request.method == "POST":
        if conversation_is_ended(conversation):
            if wants_json():
                return jsonify({"ok": False, "error": t("chat.ended"), "ended": True}), 400
            flash(t("chat.ended"), "error")
            return redirect(url_for("chat_detail", conversation_id=conversation_id))
        body = (request.form.get("body") or "").strip()
        screenshot = request.files.get("screenshot")
        screenshot_filename = None
        if screenshot and screenshot.filename:
            screenshot_filename = save_uploaded_image(
                screenshot,
                app.config["PAYMENT_FOLDER"],
                f"pay{conversation_id}",
            )
            if screenshot_filename is None:
                if wants_json():
                    return jsonify({"ok": False, "error": "Use a JPG, PNG, WEBP, or GIF image."}), 400
                flash("Use a JPG, PNG, WEBP, or GIF image.", "error")
                return redirect(url_for("chat_detail", conversation_id=conversation_id))
            if not body:
                if g.user["id"] == conversation["buyer_id"]:
                    body = "I uploaded my payment screenshot."
                else:
                    body = "I uploaded a photo."
        if not body and not screenshot_filename:
            if wants_json():
                return jsonify({"ok": False, "error": "Write a message or attach an image."}), 400
            flash("Write a message or attach an image.", "error")
            return redirect(url_for("chat_detail", conversation_id=conversation_id))
        message_id = add_message(conversation["id"], g.user["id"], body, screenshot_filename)
        if screenshot_filename:
            if g.user["id"] == conversation["buyer_id"]:
                create_notification(
                    conversation["seller_id"],
                    f"{g.user['email']} sent a payment screenshot for {conversation['product_name']}. Confirm the sale to mark it sold out.",
                    url_for("chat_detail", conversation_id=conversation_id),
                )
            else:
                create_notification(
                    conversation["buyer_id"],
                    f"{g.user['email']} sent a photo for {conversation['product_name']}.",
                    url_for("chat_detail", conversation_id=conversation_id),
                )
        if wants_json():
            row = get_message(message_id)
            payload = chat_state(get_conversation(conversation_id))
            payload["ok"] = True
            payload["message"] = serialize_message(row, g.user["id"])
            return jsonify(payload)
        return redirect(url_for("chat_detail", conversation_id=conversation_id))

    ended = conversation_is_ended(conversation)
    is_seller = g.user["id"] == conversation["seller_id"]
    return render_template(
        "chat.html",
        conversation=conversation,
        messages=list_messages(conversation_id),
        is_buyer=g.user["id"] == conversation["buyer_id"],
        is_seller=is_seller,
        chat_ended=ended,
        can_end_sale=(
            is_seller
            and not ended
            and conversation["product_status"] == "available"
            and buyer_sent_payment_screenshot(conversation)
        ),
    )


@app.route("/chats/<int:conversation_id>/live")
@login_required
def chat_live(conversation_id):
    conversation = get_conversation(conversation_id)
    if not user_in_conversation(conversation, g.user["id"]):
        abort(404)
    after_id = request.args.get("after", default=0, type=int) or 0
    payload = chat_state(conversation)
    payload["messages"] = [
        serialize_message(item, g.user["id"])
        for item in list_messages_after(conversation_id, after_id)
    ]
    return jsonify(payload)


@app.route("/chats/<int:conversation_id>/end", methods=["POST"])
@login_required
def end_conversation(conversation_id):
    conversation = get_conversation(conversation_id)
    if not user_in_conversation(conversation, g.user["id"]):
        flash("That chat was not found.", "error")
        return redirect(url_for("chats"))
    if g.user["id"] != conversation["seller_id"]:
        flash(t("chat.end_seller_only"), "error")
        return redirect(url_for("chat_detail", conversation_id=conversation_id))
    if conversation_is_ended(conversation):
        flash(t("chat.ended"), "error")
        return redirect(url_for("chat_detail", conversation_id=conversation_id))

    product = get_product(conversation["product_id"])
    if product is None:
        flash("That product was not found.", "error")
        return redirect(url_for("chats"))

    paid = buyer_sent_payment_screenshot(conversation)
    if paid:
        add_message(
            conversation["id"],
            g.user["id"],
            "Payment received. This product is now sold out and was removed from Explore.",
        )
        close_product(product)
        flash(t("chat.end_done"), "success")
    else:
        now = utc_now()
        db = get_db()
        db.execute(
            "UPDATE conversations SET ended_at = COALESCE(ended_at, ?) WHERE id = ?",
            (now, conversation["id"]),
        )
        db.commit()
        add_message(
            conversation["id"],
            g.user["id"],
            "This chat was ended.",
        )
        create_notification(
            conversation["buyer_id"],
            f"The seller ended the chat for {conversation['product_name']}.",
            url_for("chat_detail", conversation_id=conversation_id),
        )
        flash(t("chat.end_chat_done"), "success")
    return redirect(url_for("chat_detail", conversation_id=conversation_id))


@app.route("/admin")
@admin_required
def admin():
    users = list_users()
    return render_template(
        "admin.html",
        users=users,
        active_users=[user for user in users if not user["locked"]],
        locked_users=[user for user in users if user["locked"]],
        admin_keys=list_admin_keys(),
        format_admin_key=format_admin_key,
        display_name=display_name,
        format_short_date=format_short_date,
    )


@app.route("/admin/users/<int:user_id>/lock", methods=["POST"])
@admin_required
def admin_lock_user(user_id):
    target = admin_target_or_redirect(user_id)
    if target is None:
        return redirect(url_for("admin"))
    set_user_locked(target["id"], True)
    flash(f"{target['email']} is locked.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/users/<int:user_id>/unlock", methods=["POST"])
@admin_required
def admin_unlock_user(user_id):
    target = admin_target_or_redirect(user_id)
    if target is None:
        return redirect(url_for("admin"))
    set_user_locked(target["id"], False)
    flash(f"{target['email']} is unlocked.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def admin_delete_user(user_id):
    target = admin_target_or_redirect(user_id)
    if target is None:
        return redirect(url_for("admin"))
    delete_user(target["id"])
    flash(f"{target['email']} was deleted.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/warn", methods=["POST"])
@admin_required
def admin_warn():
    user_id = request.form.get("user_id", type=int)
    if user_id is None:
        flash("Choose an account to warn.", "error")
        return redirect(url_for("admin"))
    return admin_warn_user(user_id)


@app.route("/admin/users/<int:user_id>/warn", methods=["POST"])
@admin_required
def admin_warn_user(user_id):
    target = admin_target_or_redirect(user_id)
    if target is None:
        return redirect(url_for("admin"))
    message = (request.form.get("message") or "").strip()
    if not message:
        flash("Write a warning before sending it.", "error")
        return redirect(url_for("admin"))
    create_notification(target["id"], message)
    flash(f"Warning sent to {target['email']}.", "success")
    return redirect(url_for("admin"))


@app.route("/notifications")
@login_required
def notifications():
    return render_template("notifications.html")


@app.route("/notifications/<int:notification_id>/dismiss", methods=["POST"])
@login_required
def dismiss_user_notification(notification_id):
    dismiss_notification(notification_id, g.user["id"])
    return redirect(request.referrer or url_for("notifications"))


@app.route("/notifications/dismiss-all", methods=["POST"])
@login_required
def dismiss_all_user_notifications():
    dismiss_all_notifications(g.user["id"])
    return redirect(url_for("notifications"))


@app.route("/logout", methods=["POST"])
def logout():
    try:
        current_id = int(session.get("user_id"))
    except (TypeError, ValueError):
        current_id = None
    ids = [user_id for user_id in session_account_ids() if user_id != current_id]
    if ids:
        session["account_ids"] = ids
        session["user_id"] = ids[-1]
        session["adding_account"] = False
        next_user = get_user_by_id(ids[-1])
        if next_user is not None:
            flash(f"Logged out. Switched to {next_user['email']}.", "success")
        return redirect(url_for("home"))
    lang = session.get("language")
    session.clear()
    if lang in LANGUAGES:
        session["language"] = lang
    return redirect(url_for("login"))


@app.route("/logout-all", methods=["POST"])
def logout_all():
    lang = session.get("language")
    session.clear()
    if lang in LANGUAGES:
        session["language"] = lang
    return redirect(url_for("login"))


@app.route("/offline")
def offline():
    return render_template("offline.html")


@app.route("/sw.js")
def service_worker():
    response = send_from_directory(app.static_folder, "sw.js")
    response.headers["Content-Type"] = "application/javascript"
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.errorhandler(413)
def file_too_large(_error):
    flash("That file is too large. Use an image under 8 MB.", "error")
    return redirect(request.referrer or url_for("settings"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80, debug=True)
