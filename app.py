from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime
from typing import Optional

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "dev-secret-change-me"

# --- Storage paths ---
# For Render persistence later, you can set DB_PATH and UPLOAD_DIR as env vars.
DB_PATH = os.environ.get("DB_PATH", "guinness.db")
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "uploads")

# --- Upload settings ---
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}
MAX_UPLOAD_MB = 12
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ratings (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
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
              photo_path TEXT
            );
            """
        )

        # If DB existed before, ensure column exists (simple migration)
        try:
            conn.execute("ALTER TABLE ratings ADD COLUMN photo_path TEXT;")
        except sqlite3.OperationalError:
            pass

        conn.commit()


def clamp_int(value: str, lo: int = 0, hi: int = 10) -> int:
    try:
        n = int(value)
    except Exception:
        return lo
    return max(lo, min(hi, n))


def compute_score(p: int, c: int, h: int, t: int) -> float:
    # weights: Taste 45%, Head 25%, Cold 20%, Presentation 10%
    score = 0.45 * t + 0.25 * h + 0.20 * c + 0.10 * p

    # Optional penalty rules
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


@app.get("/uploads/<path:filename>")
def uploads(filename: str):
    """Serve uploaded images."""
    return send_from_directory(UPLOAD_DIR, filename)


@app.get("/")
def index():
    init_db()
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM ratings
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT 200
            """
        ).fetchall()
    return render_template("index.html", rows=rows)


@app.post("/add")
def add():
    init_db()

    person = (request.form.get("person") or "").strip() or "Unknown"
    pub_name = (request.form.get("pub_name") or "").strip()
    city = (request.form.get("city") or "").strip()
    notes = (request.form.get("notes") or "").strip()

    p = clamp_int(request.form.get("presentation", "0"))
    c = clamp_int(request.form.get("coldness", "0"))
    h = clamp_int(request.form.get("head", "0"))
    t = clamp_int(request.form.get("taste", "0"))

    score = compute_score(p, c, h, t)
    created_at = datetime.now().isoformat(timespec="seconds")

    # --- handle optional photo upload ---
    photo_path: Optional[str] = None
    file = request.files.get("photo")
    if file and file.filename:
        if not allowed_file(file.filename):
            flash("Photo must be png/jpg/jpeg/webp/gif.", "error")
            return redirect(url_for("index"))

        original = secure_filename(file.filename)
        ext = original.rsplit(".", 1)[1].lower()
        unique_name = f"{uuid.uuid4().hex}.{ext}"
        save_path = os.path.join(UPLOAD_DIR, unique_name)
        file.save(save_path)
        photo_path = unique_name

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO ratings (
              created_at, pub_name, city, person,
              presentation, coldness, head, taste,
              notes, score, photo_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (created_at, pub_name, city, person, p, c, h, t, notes, score, photo_path),
        )
        conn.commit()

    flash(f"Saved! Score: {score}", "success")
    return redirect(url_for("index"))


@app.post("/delete/<int:rating_id>")
def delete(rating_id: int):
    init_db()

    with get_db() as conn:
        row = conn.execute(
            "SELECT photo_path FROM ratings WHERE id = ?",
            (rating_id,),
        ).fetchone()

        conn.execute("DELETE FROM ratings WHERE id = ?", (rating_id,))
        conn.commit()

    # delete the file too
    if row and row["photo_path"]:
        try:
            os.remove(os.path.join(UPLOAD_DIR, row["photo_path"]))
        except FileNotFoundError:
            pass

    flash("Deleted entry.", "info")
    return redirect(url_for("index"))


@app.get("/edit/<int:rating_id>")
def edit(rating_id: int):
    init_db()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM ratings WHERE id = ?", (rating_id,)).fetchone()
    if not row:
        flash("Entry not found.", "error")
        return redirect(url_for("index"))
    return render_template("edit.html", row=row)


@app.post("/edit/<int:rating_id>")
def edit_save(rating_id: int):
    init_db()

    person = (request.form.get("person") or "").strip() or "Unknown"
    pub_name = (request.form.get("pub_name") or "").strip()
    city = (request.form.get("city") or "").strip()
    notes = (request.form.get("notes") or "").strip()

    p = clamp_int(request.form.get("presentation", "0"))
    c = clamp_int(request.form.get("coldness", "0"))
    h = clamp_int(request.form.get("head", "0"))
    t = clamp_int(request.form.get("taste", "0"))

    score = compute_score(p, c, h, t)

    # Optional: allow replacing photo on edit
    new_photo_path: Optional[str] = None
    file = request.files.get("photo")
    if file and file.filename:
        if not allowed_file(file.filename):
            flash("Photo must be png/jpg/jpeg/webp/gif.", "error")
            return redirect(url_for("edit", rating_id=rating_id))

        original = secure_filename(file.filename)
        ext = original.rsplit(".", 1)[1].lower()
        unique_name = f"{uuid.uuid4().hex}.{ext}"
        save_path = os.path.join(UPLOAD_DIR, unique_name)
        file.save(save_path)
        new_photo_path = unique_name

    with get_db() as conn:
        # If new image uploaded, remove old one
        if new_photo_path is not None:
            old = conn.execute(
                "SELECT photo_path FROM ratings WHERE id = ?",
                (rating_id,),
            ).fetchone()
            if old and old["photo_path"]:
                try:
                    os.remove(os.path.join(UPLOAD_DIR, old["photo_path"]))
                except FileNotFoundError:
                    pass

            conn.execute(
                """
                UPDATE ratings
                SET pub_name = ?, city = ?, person = ?,
                    presentation = ?, coldness = ?, head = ?, taste = ?,
                    notes = ?, score = ?, photo_path = ?
                WHERE id = ?
                """,
                (pub_name, city, person, p, c, h, t, notes, score, new_photo_path, rating_id),
            )
        else:
            conn.execute(
                """
                UPDATE ratings
                SET pub_name = ?, city = ?, person = ?,
                    presentation = ?, coldness = ?, head = ?, taste = ?,
                    notes = ?, score = ?
                WHERE id = ?
                """,
                (pub_name, city, person, p, c, h, t, notes, score, rating_id),
            )

        conn.commit()

    flash(f"Updated! Score: {score}", "success")
    return redirect(url_for("index"))


if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="127.0.0.1", port=5000)
    