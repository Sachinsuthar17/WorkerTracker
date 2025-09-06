import os
import io
import math
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from flask import (
    Flask, request, jsonify, render_template, redirect, url_for, flash, send_file
)
from flask_cors import CORS
import psycopg2
import psycopg2.extras
import segno

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
APP_BRAND = os.getenv("APP_BRAND", "Banswara Scanner")
DEVICE_SECRET = os.getenv("DEVICE_SECRET", "u38fh39fh28fh92hf928hfh92hF9H2hf92h3f9h2F")
RATE_PER_PIECE = float(os.getenv("RATE_PER_PIECE", "2.00"))

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required (Render Postgres).")

# Flask 2.3 (no before_first_request decorator)
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "dev-secret")
CORS(app)

# -----------------------------------------------------------------------------
# DB utilities
# -----------------------------------------------------------------------------
def db_connect():
    # psycopg2 expects a standard URL; Render provides it already
    return psycopg2.connect(DATABASE_URL, sslmode="require", cursor_factory=psycopg2.extras.RealDictCursor)

def ensure_schema(conn):
    """Idempotent schema creation/upgrade."""
    with conn, conn.cursor() as cur:
        # workers
        cur.execute("""
            CREATE TABLE IF NOT EXISTS workers (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                token_id TEXT UNIQUE NOT NULL,
                department TEXT DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
        # scans
        cur.execute("""
            CREATE TABLE IF NOT EXISTS scans (
                id SERIAL PRIMARY KEY,
                worker_id INTEGER NOT NULL REFERENCES workers(id) ON DELETE CASCADE,
                barcode TEXT,
                scanned_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
        # helpful indexes (safe if columns exist)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_scans_scanned_at ON scans (scanned_at DESC);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_scans_worker_scanned ON scans (worker_id, scanned_at DESC);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_workers_token ON workers (token_id);")

def today_bounds_utc():
    """Return (start, end) of today in UTC."""
    now = datetime.now(timezone.utc)
    start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start, end

# -----------------------------------------------------------------------------
# Request guard: make sure schema exists
# -----------------------------------------------------------------------------
_initialized = False
@app.before_request
def _guard_init():
    global _initialized
    if _initialized:
        return
    with db_connect() as conn:
        ensure_schema(conn)
    _initialized = True

# -----------------------------------------------------------------------------
# UI PAGES
# -----------------------------------------------------------------------------
@app.context_processor
def inject_globals():
    # jinja utils and brand
    return dict(brand=APP_BRAND, rate_per_piece=RATE_PER_PIECE)

@app.route("/")
def dashboard():
    return render_template("dashboard.html")

@app.route("/workers", methods=["GET"])
def workers_page():
    q = request.args.get("q", "").strip()
    with db_connect() as conn, conn.cursor() as cur:
        if q:
            cur.execute("""
                SELECT id, name, token_id, department, created_at
                FROM workers
                WHERE name ILIKE %s OR token_id ILIKE %s OR department ILIKE %s
                ORDER BY created_at DESC
            """, (f"%{q}%", f"%{q}%", f"%{q}%"))
        else:
            cur.execute("""
                SELECT id, name, token_id, department, created_at
                FROM workers
                ORDER BY created_at DESC
            """)
        workers = cur.fetchall()
    return render_template("workers.html", workers=workers, search=q)

@app.post("/workers/create")
def worker_create():
    name = (request.form.get("name") or "").strip()
    token = (request.form.get("token_id") or "").strip()
    dept  = (request.form.get("department") or "").strip()
    if not name or not token:
        flash("Name and Token are required.", "error")
        return redirect(url_for("workers_page"))
    # Normalize: token should be bare (no W:)
    if token.upper().startswith("W:"):
        token = token[2:]

    with db_connect() as conn, conn.cursor() as cur:
        try:
            cur.execute("""
                INSERT INTO workers (name, token_id, department) VALUES (%s,%s,%s)
                RETURNING id
            """, (name, token, dept))
            _ = cur.fetchone()
        except psycopg2.Error as e:
            flash("Token already exists or invalid input.", "error")
            return redirect(url_for("workers_page"))

    flash("Worker created.", "success")
    return redirect(url_for("workers_page"))

@app.post("/workers/<int:wid>/edit")
def worker_edit(wid: int):
    name = (request.form.get("name") or "").strip()
    token = (request.form.get("token_id") or "").strip()
    dept  = (request.form.get("department") or "").strip()
    if not name or not token:
        flash("Name and Token are required.", "error")
        return redirect(url_for("workers_page"))
    if token.upper().startswith("W:"):
        token = token[2:]
    with db_connect() as conn, conn.cursor() as cur:
        try:
            cur.execute("""
                UPDATE workers SET name=%s, token_id=%s, department=%s
                WHERE id=%s
            """, (name, token, dept, wid))
        except psycopg2.Error:
            flash("Token already used by another worker.", "error")
            return redirect(url_for("workers_page"))

    flash("Worker updated.", "success")
    return redirect(url_for("workers_page"))

@app.post("/workers/<int:wid>/delete")
def worker_delete(wid: int):
    with db_connect() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM workers WHERE id=%s", (wid,))
    flash("Worker deleted.", "success")
    return redirect(url_for("workers_page"))

@app.get("/workers/<int:wid>/qr.png")
def worker_qr_png(wid: int):
    """Return a PNG QR with content 'W:<TOKEN>' used by ESP32."""
    with db_connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT token_id FROM workers WHERE id=%s", (wid,))
        row = cur.fetchone()
        if not row:
            return "Not found", 404
        token = row["token_id"]

    payload = f"W:{token}"
    qr = segno.make(payload, error="M")  # medium ECC
    buf = io.BytesIO()
    # Nice-looking print quality
    qr.save(buf, kind="png", scale=8, border=2, dark="black", light="white")
    buf.seek(0)
    return send_file(buf, mimetype="image/png", download_name=f"worker_{wid}_qr.png")

@app.get("/workers/<int:wid>/print")
def worker_print(wid: int):
    with db_connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, name, token_id, department FROM workers WHERE id=%s", (wid,))
        row = cur.fetchone()
        if not row:
            return "Not found", 404
    # The <img> will load /workers/<id>/qr.png
    return render_template("worker_print.html", worker=row)

# -----------------------------------------------------------------------------
# API for dashboard cards
# -----------------------------------------------------------------------------
@app.get("/api/stats")
def api_stats():
    start, end = today_bounds_utc()
    with db_connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS pieces_today FROM scans WHERE scanned_at >= %s AND scanned_at < %s", (start, end))
        pieces_today = (cur.fetchone() or {}).get("pieces_today", 0)

        cur.execute("""
            SELECT COUNT(DISTINCT worker_id) AS workers_today
            FROM scans
            WHERE scanned_at >= %s AND scanned_at < %s
        """, (start, end))
        workers_today = (cur.fetchone() or {}).get("workers_today", 0)

    earnings = float(pieces_today) * RATE_PER_PIECE
    return jsonify({
        "pieces_today": pieces_today,
        "workers_today": workers_today,
        "earnings_today": round(earnings, 2)
    })

@app.get("/api/activities")
def api_activities():
    """Last N activities join workers."""
    limit = max(1, min(int(request.args.get("limit", "100")), 500))
    with db_connect() as conn, conn.cursor() as cur:
        cur.execute(f"""
            SELECT s.scanned_at AS ts,
                   w.name AS worker,
                   w.department AS line,
                   s.barcode AS info
            FROM scans s
            JOIN workers w ON w.id = s.worker_id
            ORDER BY s.scanned_at DESC
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
    # Massage for UI
    data = [{
        "ts": r["ts"].isoformat(),
        "worker": r["worker"],
        "line": r["line"],
        "info": r["info"] or ""
    } for r in rows]
    return jsonify({"items": data})

# -----------------------------------------------------------------------------
# ESP32 endpoints
# -----------------------------------------------------------------------------
def require_secret(payload: dict):
    if payload.get("secret") != DEVICE_SECRET:
        return False
    return True

@app.post("/scan")
def scan_login():
    """
    Body: { secret, token_id: 'W:<TOKEN>' }
    Returns: {status:'success', name, department, scans_today, earnings}
    """
    payload = request.get_json(force=True, silent=True) or {}
    if not require_secret(payload):
        return jsonify({"ok": False, "error": "forbidden"}), 403

    token_id = (payload.get("token_id") or "").strip()
    if token_id.upper().startswith("W:"):
        token_id = token_id[2:]
    if not token_id:
        return jsonify({"ok": False, "error": "missing token"}), 400

    with db_connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, name, department FROM workers WHERE token_id=%s", (token_id,))
        w = cur.fetchone()
        if not w:
            return jsonify({"ok": False, "status": "error", "message": "Worker not found"}), 200

        start, end = today_bounds_utc()
        cur.execute("""
            SELECT COUNT(*) AS cnt
            FROM scans
            WHERE worker_id=%s AND scanned_at >= %s AND scanned_at < %s
        """, (w["id"], start, end))
        cnt = (cur.fetchone() or {}).get("cnt", 0)

    return jsonify({
        "ok": True,
        "status": "success",
        "name": w["name"],
        "department": w["department"],
        "scans_today": int(cnt),
        "earnings": round(float(cnt) * RATE_PER_PIECE, 2)
    })

@app.post("/scan_operation")
def scan_operation():
    """
    Body: { secret, token_id: 'W:<TOKEN>', barcode: 'B:<...>' or raw }
    Stores one piece and returns updated totals for today.
    """
    payload = request.get_json(force=True, silent=True) or {}
    if not require_secret(payload):
        return jsonify({"status": "error", "message": "forbidden"}), 403

    token_id = (payload.get("token_id") or "").strip()
    barcode = (payload.get("barcode") or "").strip()

    if token_id.upper().startswith("W:"):
        token_id = token_id[2:]
    if barcode.upper().startswith("B:"):
        barcode = barcode[2:]

    if not token_id:
        return jsonify({"status": "error", "message": "missing token"}), 400

    with db_connect() as conn, conn.cursor() as cur:
        # find worker
        cur.execute("SELECT id, name FROM workers WHERE token_id=%s", (token_id,))
        w = cur.fetchone()
        if not w:
            return jsonify({"status": "error", "message": "Worker not found"}), 200

        # store piece
        cur.execute("INSERT INTO scans (worker_id, barcode) VALUES (%s,%s)", (w["id"], barcode or None))

        # compute today's totals
        start, end = today_bounds_utc()
        cur.execute("""
            SELECT COUNT(*) AS cnt
            FROM scans
            WHERE worker_id=%s AND scanned_at >= %s AND scanned_at < %s
        """, (w["id"], start, end))
        cnt = (cur.fetchone() or {}).get("cnt", 0)

    return jsonify({
        "status": "success",
        "worker": w["name"],
        "scans_today": int(cnt),
        "earnings": round(float(cnt) * RATE_PER_PIECE, 2)
    })

# -----------------------------------------------------------------------------
# Simple pages for other nav items (optional stubs)
# -----------------------------------------------------------------------------
@app.route("/operations")
def operations_page():
    return render_template("operations.html")

@app.route("/assign_operation")
def assign_operation_page():
    return render_template("assign_operation.html")

@app.route("/reports")
def reports_page():
    return render_template("reports.html")

@app.route("/settings")
def settings_page():
    return render_template("settings.html")

# -----------------------------------------------------------------------------
# Entry
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    # For local testing only (Render uses Gunicorn)
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
