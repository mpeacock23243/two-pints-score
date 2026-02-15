from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime
from functools import wraps
from typing import Optional

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

# -----------------------------
# App config
# -----------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

DB_PATH = os.environ.get("DB_PATH", "guinness.db")
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "uploads")

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}
MAX_UPLOAD_MB = 12
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024


# -----------------------------
# DB helpers
# -----------------------------
def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _column_exists(conn: sqlite3.Connection, table: str, col: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table});").fetchall()
    return any(r["name"] == col for r in rows)


def init_db() -> None:
    """Create tables if they don't exist; do small migrations safely."""
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    with get_db() as conn:
        # Users table
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              username TEXT NOT NULL UNIQUE,
              password_hash TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            """
        )

        # Ratings table (includes user_id + photo_path)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ratings (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id INTEGER,
              created_at TEXT NOT NULL,
              pub_name TEXT,
              city TEXT,
              person TEXT NOT NULL,
              presentation INTEGER NOT NULL,
              coldness INTEGER NOT NULL,
              head INTEGER NOT NULL,
              taste INTEGER NOT NULL,
              notes TEXT,
              score REAL NOT NULL,
              photo_path TEXT,
              FOREIGN KEY (user_id) REFERENCES users(id)
            );
            """
        )

        # Migrations for older DBs
        if not _column_exists(conn, "ratings", "user_id"):
            conn.execute("ALTER TABLE ratings ADD COLUMN user_id INTEGER;")
        if not _column_exists(conn, "ratings", "photo_path"):
            conn.execute("ALTER TABLE ratings ADD COLUMN photo_path TEXT;")

        conn.commit()


# -----------------------------
# Auth helpers
# -----------------------------
def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)

    return wrapper


def current_user_id() -> int:
    uid = session.get("user_id")
    if not uid:
        raise RuntimeError("Not logged in")
    return int(uid)


# -----------------------------
# Business logic helpers
# -----------------------------
def clamp_int(value: str, lo: int = 0, hi: int = 10) -> int:
    try:
        n = int(value)
    except Exception:
        return lo
    return max(lo, min(hi, n))


def compute_score(p: int, c: int, h: int, t: int) -> float:
    """
    Score 0-10 using an easy weighted formula:
      Taste 45%, Head 25%, Cold 20%, Presentation 10%
    Plus two simple "guardrails" that feel Guinness-real:
      - If taste <= 4, cap to 5.0 (bad pint can't score high)
      - If head <= 3, small penalty
    """
    score = 0.45 * t + 0.25 * h + 0.20 * c + 0.10 * p
    if t <= 4:
        score = min(score, 5.0)
    if h <= 3:
        score -= 0.7
    score = max(0.0, min(10.0, score))
    return round(score, 1)


def allowed_file(filename: str) -> bool:
    if not filename or "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_EXTENSIONS


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# -----------------------------
# Static uploads
# -----------------------------
@app.get("/uploads/<path:filename>")
@login_required
def uploads(filename: str):
    return send_from_directory(UPLOAD_DIR, filename)


# -----------------------------
# Auth routes
# -----------------------------
@app.get("/register")
def register():
    init_db()
    if session.get("user_id"):
        return redirect(url_for("index"))
    return render_template("register.html")


@app.post("/register")
def register_post():
    init_db()

    username = (request.form.get("username") or "").strip().lower()
    password = request.form.get("password") or ""

    if len(username) < 3:
        flash("Username must be at least 3 characters.", "error")
        return redirect(url_for("register"))
    if len(password) < 6:
        flash("Password must be at least 6 characters.", "error")
        return redirect(url_for("register"))

    pw_hash = generate_password_hash(password)

    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                (username, pw_hash, now_iso()),
            )
            conn.commit()
    except sqlite3.IntegrityError:
        flash("That username is taken.", "error")
        return redirect(url_for("register"))

    flash("Account created. Please log in.", "success")
    return redirect(url_for("login"))


@app.get("/login")
def login():
    init_db()
    if session.get("user_id"):
        return redirect(url_for("index"))
    return render_template("login.html")


@app.post("/login")
def login_post():
    init_db()

    username = (request.form.get("username") or "").strip().lower()
    password = request.form.get("password") or ""

    with get_db() as conn:
        user = conn.execute(
            "SELECT id, username, password_hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()

    if not user or not check_password_hash(user["password_hash"], password):
        flash("Invalid username or password.", "error")
        return redirect(url_for("login"))

    session["user_id"] = int(user["id"])
    session["username"] = user["username"]
    return redirect(url_for("index"))


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# -----------------------------
# Main app pages
# -----------------------------
@app.get("/")
@login_required
def index():
    init_db()
    uid = current_user_id()

    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM ratings
            WHERE user_id = ?
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT 200
            """,
            (uid,),
        ).fetchall()

    return render_template("index.html", rows=rows, username=session.get("username"))


@app.post("/add")
@login_required
def add():
    init_db()
    uid = current_user_id()

    # Basic fields
    person = (request.form.get("person") or "").strip() or (session.get("username") or "Unknown")
    pub_name = (request.form.get("pub_name") or "").strip()
    city = (request.form.get("city") or "").strip()
    notes = (request.form.get("notes") or "").strip()

    # Ratings
    p = clamp_int(request.form.get("presentation", "0"))
    c = clamp_int(request.form.get("coldness", "0"))
    h = clamp_int(request.form.get("head", "0"))
    t = clamp_int(request.form.get("taste", "0"))

    score = compute_score(p, c, h, t)

    # Photo upload
    photo_path: Optional[str] = None
    file = request.files.get("photo")
    if file and file.filename:
        if not allowed_file(file.filename):
            flash("Photo must be png/jpg/jpeg/webp/gif.", "error")
            return redirect(url_for("index"))

        original = secure_filename(file.filename)
        ext = original.rsplit(".", 1)[1].lower()
        unique_name = f"{uuid.uuid4().hex}.{ext}"
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        file.save(os.path.join(UPLOAD_DIR, unique_name))
        photo_path = unique_name

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO ratings (
              user_id, created_at, pub_name, city, person,
              presentation, coldness, head, taste,
              notes, score, photo_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (uid, now_iso(), pub_name, city, person, p, c, h, t, notes, score, photo_path),
        )
        conn.commit()

    flash(f"Saved! Score: {score}", "success")
    return redirect(url_for("index"))


@app.post("/delete/<int:rating_id>")
@login_required
def delete(rating_id: int):
    init_db()
    uid = current_user_id()

    with get_db() as conn:
        row = conn.execute(
            "SELECT photo_path FROM ratings WHERE id = ? AND user_id = ?",
            (rating_id, uid),
        ).fetchone()

        conn.execute("DELETE FROM ratings WHERE id = ? AND user_id = ?", (rating_id, uid))
        conn.commit()

    # Delete photo file if it exists
    if row and row["photo_path"]:
        try:
            os.remove(os.path.join(UPLOAD_DIR, row["photo_path"]))
        except FileNotFoundError:
            pass

    flash("Deleted entry.", "info")
    return redirect(url_for("index"))


@app.get("/edit/<int:rating_id>")
@login_required
def edit(rating_id: int):
    init_db()
    uid = current_user_id()

    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM ratings WHERE id = ? AND user_id = ?",
            (rating_id, uid),
        ).fetchone()

    if not row:
        flash("Entry not found.", "error")
        return redirect(url_for("index"))

    return render_template("edit.html", row=row, username=session.get("username"))


@app.post("/edit/<int:rating_id>")
@login_required
def edit_save(rating_id: int):
    init_db()
    uid = current_user_id()

    person = (request.form.get("person") or "").strip() or (session.get("username") or "Unknown")
    pub_name = (request.form.get("pub_name") or "").strip()
    city = (request.form.get("city") or "").strip()
    notes = (request.form.get("notes") or "").strip()

    p = clamp_int(request.form.get("presentation", "0"))
    c = clamp_int(request.form.get("coldness", "0"))
    h = clamp_int(request.form.get("head", "0"))
    t = clamp_int(request.form.get("taste", "0"))

    score = compute_score(p, c, h, t)

    new_photo_path: Optional[str] = None
    file = request.files.get("photo")
    if file and file.filename:
        if not allowed_file(file.filename):
            flash("Photo must be png/jpg/jpeg/webp/gif.", "error")
            return redirect(url_for("edit", rating_id=rating_id))

        original = secure_filename(file.filename)
        ext = original.rsplit(".", 1)[1].lower()
        unique_name = f"{uuid.uuid4().hex}.{ext}"
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        file.save(os.path.join(UPLOAD_DIR, unique_name))
        new_photo_path = unique_name

    with get_db() as conn:
        if new_photo_path is not None:
            old = conn.execute(
                "SELECT photo_path FROM ratings WHERE id = ? AND user_id = ?",
                (rating_id, uid),
            ).fetchone()

            conn.execute(
                """
                UPDATE ratings
                SET pub_name = ?, city = ?, person = ?,
                    presentation = ?, coldness = ?, head = ?, taste = ?,
                    notes = ?, score = ?, photo_path = ?
                WHERE id = ? AND user_id = ?
                """,
                (pub_name, city, person, p, c, h, t, notes, score, new_photo_path, rating_id, uid),
            )

            # remove old file
            if old and old["photo_path"]:
                try:
                    os.remove(os.path.join(UPLOAD_DIR, old["photo_path"]))
                except FileNotFoundError:
                    pass
        else:
            conn.execute(
                """
                UPDATE ratings
                SET pub_name = ?, city = ?, person = ?,
                    presentation = ?, coldness = ?, head = ?, taste = ?,
                    notes = ?, score = ?
                WHERE id = ? AND user_id = ?
                """,
                (pub_name, city, person, p, c, h, t, notes, score, rating_id, uid),
            )

        conn.commit()

    flash(f"Updated! Score: {score}", "success")
    return redirect(url_for("index"))


# -----------------------------
# Leaderboard
# -----------------------------
@app.get("/leaderboard")
@login_required
def leaderboard():
    init_db()

    q = (request.args.get("q") or "").strip()
    city = (request.args.get("city") or "").strip()

    try:
        min_ratings = int(request.args.get("min") or "1")
    except ValueError:
        min_ratings = 1
    min_ratings = max(1, min(999, min_ratings))

    where = []
    params = []

    if q:
        where.append("LOWER(COALESCE(pub_name,'')) LIKE ?")
        params.append(f"%{q.lower()}%")

    if city:
        where.append("LOWER(COALESCE(city,'')) = ?")
        params.append(city.lower())

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    with get_db() as conn:
        pubs = conn.execute(
            f"""
            SELECT
              COALESCE(pub_name, '') AS pub_name,
              COALESCE(city, '') AS city,
              ROUND(AVG(score), 2) AS avg_score,
              MAX(score) AS best_score,
              COUNT(*) AS ratings
            FROM ratings
            {where_sql}
            GROUP BY COALESCE(pub_name, ''), COALESCE(city, '')
            HAVING COUNT(*) >= ?
            ORDER BY avg_score DESC, best_score DESC, ratings DESC
            LIMIT 50
            """,
            (*params, min_ratings),
        ).fetchall()

    return render_template(
        "leaderboard.html",
        pubs=pubs,
        username=session.get("username"),
        q=q,
        city=city,
        min_ratings=min_ratings,
    )


# -----------------------------
# Run local
# -----------------------------
if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="127.0.0.1", port=5000)
