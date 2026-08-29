import os
import secrets
import sqlite3
import string
from datetime import datetime, timezone
from functools import wraps

from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__, instance_relative_config=True)
app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY", "dev-only-change-me-in-production"
)
app.config["DATABASE"] = os.path.join(app.instance_path, "users.db")
app.config["ADMIN_KEY_COUNT"] = 5
app.config["ADMIN_KEY_LENGTH"] = 16
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
app.config["AVATAR_FOLDER"] = os.path.join(app.instance_path, "avatars")

os.makedirs(app.instance_path, exist_ok=True)
os.makedirs(app.config["AVATAR_FOLDER"], exist_ok=True)

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
            avatar_filename TEXT
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
            FOREIGN KEY (user_id) REFERENCES users(id)
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


def create_user(email, password_hash):
    db = get_db()
    cursor = db.execute(
        """
        INSERT INTO users (email, password_hash, created_at, role, locked)
        VALUES (?, ?, ?, 'user', 0)
        """,
        (email, password_hash, utc_now()),
    )
    db.commit()
    return cursor.lastrowid


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


def remove_avatar_file(filename):
    if not filename:
        return
    path = os.path.join(app.config["AVATAR_FOLDER"], filename)
    if os.path.isfile(path):
        os.remove(path)


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


def create_notification(user_id, message):
    db = get_db()
    db.execute(
        "INSERT INTO notifications (user_id, message, created_at, read) VALUES (?, ?, ?, 0)",
        (user_id, message, utc_now()),
    )
    db.commit()


def list_notifications(user_id):
    return get_db().execute(
        """
        SELECT id, message, created_at, read
        FROM notifications
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        (user_id,),
    ).fetchall()


def dismiss_notification(notification_id, user_id):
    db = get_db()
    db.execute(
        "UPDATE notifications SET read = 1 WHERE id = ? AND user_id = ?",
        (notification_id, user_id),
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
    }


@app.before_request
def load_logged_in_user():
    init_db()
    user_id = session.get("user_id")
    g.user = get_user_by_id(user_id) if user_id is not None else None
    if g.user is not None and g.user["locked"]:
        session.clear()
        g.user = None
        if request.endpoint not in {"static", "service_worker"}:
            flash("Your account has been locked.", "error")
    g.notifications = list_notifications(g.user["id"]) if g.user is not None else []
    g.unread_count = sum(1 for item in g.notifications if not item["read"])


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("login"))
        if not is_admin(g.user):
            flash("Admin access is required.", "error")
            return redirect(url_for("home"))
        return view(*args, **kwargs)

    return wrapped


def redirect_if_logged_in(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is not None:
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
    if g.user is not None:
        return redirect(url_for("home"))
    return redirect(url_for("login"))


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
            session.clear()
            session["user_id"] = user_id
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

        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Invalid email or password.", "error")
        elif user["locked"]:
            flash("This account is locked.", "error")
        else:
            session.clear()
            session["user_id"] = user["id"]
            return redirect(url_for("home"))

    return render_template("login.html")


@app.route("/home")
@login_required
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


@app.route("/settings/password", methods=["POST"])
@login_required
def settings_password():
    current_password = request.form.get("current_password") or ""
    new_password = request.form.get("new_password") or ""
    confirm_password = request.form.get("confirm_password") or ""

    if not check_password_hash(g.user["password_hash"], current_password):
        flash("Current password is not correct.", "error")
    elif len(new_password) < 8:
        flash("New password must be at least 8 characters.", "error")
    elif new_password != confirm_password:
        flash("New passwords do not match.", "error")
    else:
        set_user_password(g.user["id"], generate_password_hash(new_password))
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


@app.route("/avatars/<filename>")
@login_required
def avatar_file(filename):
    if not filename or "/" in filename or "\\" in filename:
        abort(404)
    return send_from_directory(app.config["AVATAR_FOLDER"], filename)


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


@app.route("/notifications/<int:notification_id>/dismiss", methods=["POST"])
@login_required
def dismiss_user_notification(notification_id):
    dismiss_notification(notification_id, g.user["id"])
    return redirect(request.referrer or url_for("home"))


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
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
    flash("That file is too large. Use an image under 2 MB.", "error")
    return redirect(url_for("settings"))


if __name__ == "__main__":
    app.run(debug=True)
