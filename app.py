import os
import io
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional

from flask import (
    Flask, request, jsonify, render_template, redirect, url_for, flash, send_file
)
from flask_cors import CORS
import psycopg2
import psycopg2.extras
import psycopg2.errors
import segno

# -----------------------------------------------------------------------------
# App config
# -----------------------------------------------------------------------------
APP_BRAND = os.getenv("APP_BRAND", "Banswara Scanner")
DEVICE_SECRET = os.getenv("DEVICE_SECRET", "u38fh39fh28fh92hf928hfh92hF9H2hf92h3f9h2F")
RATE_PER_PIECE = float(os.getenv("RATE_PER_PIECE", "2.00"))

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required.")

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "dev-secret")
CORS(app)

# -----------------------------------------------------------------------------
# DB helpers
# -----------------------------------------------------------------------------
def db_connect():
    # Render Postgres URL is already in the correct format
    return psycopg2.connect(
        DATABASE_URL,
        sslmode="require",
        cursor_factory=psycopg2.extras.RealDictCursor
    )

def ensure_schema() -> None:
    """Create/upgrade schema. Opens its own connection (no nesting)."""
    conn = db_connect()
    try:
        with conn:
            with conn.cursor() as cur:
                # Workers
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS workers (
                        id SERIAL PRIMARY KEY,
                        name TEXT NOT NULL,
                        token_id TEXT UNIQUE NOT NULL,
                        department TEXT DEFAULT '',
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                """)
                # Scans (each scanned piece)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS scans (
                        id SERIAL PRIMARY KEY,
                        worker_id INTEGER NOT NULL REFERENCES workers(id) ON DELETE CASCADE,
                        barcode TEXT,
                        scanned_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                """)
                # Global app state (single row, id=1) to remember the currently active worker
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS app_state (
                        id INTEGER PRIMARY KEY,
                        current_worker_id INTEGER NULL REFERENCES workers(id) ON DELETE SET NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                """)
                # Seed single row if missing
                cur.execute("INSERT INTO app_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING;")

                # Indexes
                cur.execute("CREATE INDEX IF NOT EXISTS idx_scans_scanned_at ON scans (scanned_at DESC);")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_scans_worker_scanned ON scans (worker_id, scanned_at DESC);")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_workers_token ON workers (token_id);")
    finally:
        conn.close()

def today_bounds_utc() -> Tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start, end

# Small helpers for current session
def get_active_worker(conn) -> Optional[dict]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT w.id, w.name, w.token_id, w.department
            FROM app_state a
            LEFT JOIN workers w ON w.id = a.current_worker_id
            WHERE a.id = 1
        """)
        return cur.fetchone()

def set_active_worker(conn, worker_id: Optional[int]) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE app_state
            SET current_worker_id = %s, updated_at = NOW()
            WHERE id = 1
        """, (worker_id,))

# -----------------------------------------------------------------------------
# First-request guard
# -----------------------------------------------------------------------------
_initialized = False

@app.before_request
def _guard_init():
    global _initialized
    if _initialized:
        return
    ensure_schema()
    _initialized = True

# -----------------------------------------------------------------------------
# Template globals
# -----------------------------------------------------------------------------
@app.context_processor
def inject_globals():
    # Provide brand, rate and a small now() helper so your template footer works.
    return dict(
        brand=APP_BRAND,
        rate_per_piece=RATE_PER_PIECE,
        now=lambda: datetime.now()
    )

# -----------------------------------------------------------------------------
# Pages
# -----------------------------------------------------------------------------
@app.get("/")
def dashboard():
    return render_template("dashboard.html")

@app.get("/operations")
def operations_page():
    return render_template("operations.html")

@app.get("/assign_operation")
def assign_operation_page():
    return render_template("assign_operation.html")

@app.get("/reports")
def reports_page():
    return render_template("reports.html")

@app.get("/settings")
def settings_page():
    return render_template("settings.html")

# -----------------------------------------------------------------------------
# Workers CRUD + QR
# -----------------------------------------------------------------------------
@app.get("/workers")
def workers_page():
    q = (request.args.get("q") or "").strip()
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

        # Also show which worker is currently active (if any)
        active = get_active_worker(conn)

    return render_template("workers.html", workers=workers, search=q, active_worker=active)

@app.post("/workers/create")
def worker_create():
    name = (request.form.get("name") or "").strip()
    token = (request.form.get("token_id") or "").strip()
    dept  = (request.form.get("department") or "").strip()
    if not name or not token:
        flash("Name and Token are required.", "error")
        return redirect(url_for("workers_page"))
    if token.upper().startswith("W:"):
        token = token[2:]

    try:
        with db_connect() as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO workers (name, token_id, department)
                VALUES (%s,%s,%s)
                RETURNING id
            """, (name, token, dept))
    except psycopg2.Error:
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

    try:
        with db_connect() as conn, conn.cursor() as cur:
            cur.execute("""
                UPDATE workers
                SET name=%s, token_id=%s, department=%s
                WHERE id=%s
            """, (name, token, dept, wid))
    except psycopg2.Error:
        flash("Token already used by another worker.", "error")
        return redirect(url_for("workers_page"))

    flash("Worker updated.", "success")
    return redirect(url_for("workers_page"))

@app.post("/workers/<int:wid>/delete")
def worker_delete(wid: int):
    try:
        with db_connect() as conn, conn.cursor() as cur:
            # If deleting the active worker, clear the session first
            active = get_active_worker(conn)
            if active and active.get("id") == wid:
                set_active_worker(conn, None)

            cur.execute("DELETE FROM workers WHERE id=%s", (wid,))
    except psycopg2.errors.ForeignKeyViolation:
        # Friendly message when other tables still reference this worker
        flash("Cannot delete: this worker has production/scans linked. Delete those first.", "error")
        return redirect(url_for("workers_page"))
    except psycopg2.Error:
        flash("Delete failed due to a database error.", "error")
        return redirect(url_for("workers_page"))

    flash("Worker deleted.", "success")
    return redirect(url_for("workers_page"))

@app.get("/workers/<int:wid>/qr.png")
def worker_qr_png(wid: int):
    with db_connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT token_id FROM workers WHERE id=%s", (wid,))
        row = cur.fetchone()
    if not row:
        return "Not found", 404

    payload = f"W:{row['token_id']}"
    qr = segno.make(payload, error="M")
    buf = io.BytesIO()
    qr.save(buf, kind="png", scale=8, border=2)
    buf.seek(0)
    return send_file(buf, mimetype="image/png", download_name=f"worker_{wid}_qr.png")

@app.get("/workers/<int:wid>/print")
def worker_print(wid: int):
    with db_connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, name, token_id, department FROM workers WHERE id=%s", (wid,))
        row = cur.fetchone()
    if not row:
        return "Not found", 404
    # NOTE: use print_qr.html (new template)
    return render_template("print_qr.html", worker=row)

# -----------------------------------------------------------------------------
# Public API used by dashboard cards
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

        # Add active worker name for the dashboard badge if you want it
        active = get_active_worker(conn)

    earnings = float(pieces_today) * RATE_PER_PIECE
    return jsonify({
        "pieces_today": int(pieces_today),
        "workers_today": int(workers_today),
        "earnings_today": round(earnings, 2),
        "active_worker": active["name"] if active else None
    })

@app.get("/api/activities")
def api_activities():
    limit = max(1, min(int(request.args.get("limit", "100")), 500))
    with db_connect() as conn, conn.cursor() as cur:
        cur.execute("""
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
    items = [{
        "ts": r["ts"].isoformat(),
        "worker": r["worker"],
        "line": r["line"],
        "info": r["info"] or ""
    } for r in rows]
    return jsonify({"items": items})

# -----------------------------------------------------------------------------
# ESP32 unified endpoint (/scan) — handles login toggle AND piece save
# -----------------------------------------------------------------------------
def _require_secret(payload: dict) -> bool:
    return payload.get("secret") == DEVICE_SECRET

def _normalize_token_or_name(payload: dict) -> Tuple[Optional[str], Optional[str]]:
    """
    Returns (token_id, worker_name_guess)
    Accepts new 'token_id' (may be 'W:XYZ') OR legacy 'worker_name'.
    """
    token = (payload.get("token_id") or "").strip()
    name  = (payload.get("worker_name") or "").strip()
    if token.upper().startswith("W:"):
        token = token[2:]
    return (token or None), (name or None)

def _find_worker_by_token_or_name(cur, token_id: Optional[str], name_guess: Optional[str]) -> Optional[dict]:
    worker_row = None
    if token_id:
        cur.execute("SELECT id, name, token_id, department FROM workers WHERE token_id=%s", (token_id,))
        worker_row = cur.fetchone()
    if not worker_row and name_guess:
        # Some old devices sent token in worker_name
        cur.execute("SELECT id, name, token_id, department FROM workers WHERE token_id=%s", (name_guess,))
        worker_row = cur.fetchone()
        if not worker_row:
            cur.execute("SELECT id, name, token_id, department FROM workers WHERE name=%s", (name_guess,))
            worker_row = cur.fetchone()
    return worker_row

@app.post("/scan")
def scan_unified():
    """
    Body:
      {
        secret: "...",
        token_id: "W:ABC123" OR "ABC123"   # preferred for worker QR
        # or legacy:
        worker_name: "ABC123" or actual name

        # optional for saving a piece:
        barcode: "B:..." or raw "...",
      }

    Behavior:
      - If 'barcode' is absent: treat as worker QR scan -> toggle global active worker
        (logout if same, switch if different).
      - If 'barcode' is present: save a piece for the active worker if one is set; else
        resolve worker from token/name and save.
      - Always returns today's totals for the effective worker (if any).
    """
    payload = request.get_json(force=True, silent=True) or {}
    if not _require_secret(payload):
        return jsonify({"ok": False, "error": "forbidden"}), 403

    token_id, name_guess = _normalize_token_or_name(payload)
    barcode = (payload.get("barcode") or "").strip()
    if barcode.upper().startswith("B:"):
        barcode = barcode[2:]

    with db_connect() as conn:
        with conn.cursor() as cur:
            active = get_active_worker(conn)

            # CASE 1: worker QR (toggle)
            if not barcode:
                # Need to find which worker QR was scanned
                scanned_worker = _find_worker_by_token_or_name(cur, token_id, name_guess)
                if not scanned_worker:
                    return jsonify({"ok": False, "status": "error", "message": "Worker not found"}), 200

                if active and active["id"] == scanned_worker["id"]:
                    # Same worker -> logout
                    set_active_worker(conn, None)
                    effective = None
                    state = "logged_out"
                else:
                    # Switch to new worker
                    set_active_worker(conn, scanned_worker["id"])
                    effective = scanned_worker
                    state = "logged_in"

                # Compute today's totals for the effective worker (if any)
                start, end = today_bounds_utc()
                cnt = 0
                if effective:
                    cur.execute("""
                        SELECT COUNT(*) AS cnt
                        FROM scans
                        WHERE worker_id=%s AND scanned_at >= %s AND scanned_at < %s
                    """, (effective["id"], start, end))
                    cnt = (cur.fetchone() or {}).get("cnt", 0)

                return jsonify({
                    "ok": True,
                    "status": state,
                    "active_worker": (effective or {}),
                    "today_pieces": int(cnt),
                    "today_earn": round(float(cnt) * RATE_PER_PIECE, 2)
                })

            # CASE 2: piece scan (barcode provided)
            # Prefer the globally active worker, else resolve from request
            effective = active
            if not effective:
                effective = _find_worker_by_token_or_name(cur, token_id, name_guess)
                if not effective:
                    return jsonify({"ok": False, "status": "error", "message": "No active worker and none resolved"}), 200

            # Save the piece
            cur.execute("INSERT INTO scans (worker_id, barcode) VALUES (%s,%s)", (effective["id"], barcode or None))

            # Compute today's totals for this worker
            start, end = today_bounds_utc()
            cur.execute("""
                SELECT COUNT(*) AS cnt
                FROM scans
                WHERE worker_id=%s AND scanned_at >= %s AND scanned_at < %s
            """, (effective["id"], start, end))
            cnt = (cur.fetchone() or {}).get("cnt", 0)

            return jsonify({
                "ok": True,
                "status": "saved",
                "active_worker": effective,
                "today_pieces": int(cnt),
                "today_earn": round(float(cnt) * RATE_PER_PIECE, 2)
            })

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
