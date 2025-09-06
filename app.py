import os
import io
import uuid
import threading
from datetime import datetime, timezone
from typing import Optional

from flask import (
    Flask, jsonify, render_template, request,
    redirect, url_for, send_file, abort
)
from flask_cors import CORS
import psycopg2
from psycopg2.pool import SimpleConnectionPool

# Optional QR libs (both are in your requirements)
# We'll prefer segno (SVG/PNG, no PIL dependency).
import segno

# =========================
# Config
# =========================
DEVICE_SECRET   = os.getenv("DEVICE_SECRET", "u38fh39fh28fh92hf928hfh92hF9H2hf92h3f9h2F")
DATABASE_URL    = os.getenv("DATABASE_URL")  # Render Postgres URL
RATE_PER_PIECE  = float(os.getenv("RATE_PER_PIECE", "1.0"))  # INR per piece

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required")

app = Flask(__name__)
CORS(app)

_pool: Optional[SimpleConnectionPool] = None
_inited = False
_init_lock = threading.Lock()


def get_pool() -> SimpleConnectionPool:
    """Create / return a shared connection pool."""
    global _pool
    if _pool is None:
        _pool = SimpleConnectionPool(minconn=1, maxconn=12, dsn=DATABASE_URL, sslmode="require")
    return _pool


def ensure_schema(conn: psycopg2.extensions.connection) -> None:
    """
    Idempotent, legacy-safe schema bootstrap.
    Creates/patches:
      - workers (id, name, department, token_id UNIQUE)
      - scans   (id, worker_id, barcode, operation_code, created_at TIMESTAMPTZ)
    Adds FK + indexes if missing.
    """
    cur = conn.cursor()
    try:
        # --- workers (basic master)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS workers (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                department TEXT NOT NULL DEFAULT '',
                token_id TEXT UNIQUE
            );
        """)

        # --- scans (start minimal, expand safely)
        cur.execute("CREATE TABLE IF NOT EXISTS scans (id SERIAL PRIMARY KEY);")

        cur.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='scans' AND column_name='worker_id') THEN
                ALTER TABLE scans ADD COLUMN worker_id INTEGER;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='scans' AND column_name='barcode') THEN
                ALTER TABLE scans ADD COLUMN barcode TEXT;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='scans' AND column_name='operation_code') THEN
                ALTER TABLE scans ADD COLUMN operation_code TEXT;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='scans' AND column_name='created_at') THEN
                ALTER TABLE scans ADD COLUMN created_at TIMESTAMPTZ DEFAULT NOW();
            END IF;
        END $$;
        """)

        # Backfill from any legacy 'scanned_at'
        cur.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name='scans' AND column_name='scanned_at') THEN
                UPDATE scans SET created_at = COALESCE(created_at, scanned_at)
                WHERE created_at IS NULL;
            END IF;
        END $$;
        """)

        # FK only once
        cur.execute("""
        DO $$
        DECLARE fk_exists BOOLEAN;
        BEGIN
            SELECT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname='scans_worker_id_fkey'
            ) INTO fk_exists;
            IF NOT fk_exists THEN
                ALTER TABLE scans
                ADD CONSTRAINT scans_worker_id_fkey
                FOREIGN KEY (worker_id) REFERENCES workers(id)
                ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED;
            END IF;
        END $$;
        """)

        # Indexes
        cur.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name='scans' AND column_name='created_at') THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_scans_created_at ON scans (created_at DESC)';
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name='scans' AND column_name='worker_id')
               AND EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='scans' AND column_name='created_at') THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_scans_worker ON scans (worker_id, created_at DESC)';
            END IF;
        END $$;
        """)
    finally:
        cur.close()
        conn.commit()


def init_once() -> None:
    """Run schema bootstrap exactly once per process."""
    global _inited
    if _inited:
        return
    with _init_lock:
        if _inited:
            return
        pool = get_pool()
        conn = pool.getconn()
        try:
            ensure_schema(conn)
            _inited = True
        finally:
            pool.putconn(conn)


@app.before_request
def _guard_init():
    init_once()


def today_bounds_utc():
    now = datetime.now(timezone.utc)
    start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    end = datetime(now.year, now.month, now.day, 23, 59, 59, 999999, tzinfo=timezone.utc)
    return start, end


# =========================
# Pages
# =========================
@app.route("/")
def dashboard():
    return render_template("dashboard.html", rate_per_piece=RATE_PER_PIECE)

@app.route("/workers", methods=["GET"])
def workers_page():
    """
    List workers + inline "Add Worker" form.
    """
    pool = get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT id, COALESCE(NULLIF(name,''),'(no name)') AS name,
                       COALESCE(NULLIF(department,''),'') AS department,
                       COALESCE(NULLIF(token_id,''),'') AS token_id
                  FROM workers
                 ORDER BY id DESC;
            """)
            workers = [
                {"id": rid, "name": nm, "department": dept, "token_id": tok or ""}
                for (rid, nm, dept, tok) in cur.fetchall()
            ]
        finally:
            cur.close()
    finally:
        pool.putconn(conn)
    return render_template("workers.html", rate_per_piece=RATE_PER_PIECE, workers=workers)

@app.route("/operations")
def operations_page():
    return render_template("operations.html", rate_per_piece=RATE_PER_PIECE)

@app.route("/reports")
def reports_page():
    return render_template("reports.html", rate_per_piece=RATE_PER_PIECE)

@app.route("/settings")
def settings_page():
    # Render with explicit rate to avoid "undefined" issues in template
    return render_template("settings.html", rate_per_piece=RATE_PER_PIECE)

@app.route("/assign_operation")
def assign_operation_page():
    return render_template("assign_operation.html", rate_per_piece=RATE_PER_PIECE)


# =========================
# Worker Management (New)
# =========================
def _new_token() -> str:
    # short stable token: first 12 hex chars of uuid4
    return uuid.uuid4().hex[:12].upper()

@app.route("/workers/add", methods=["POST"])
def workers_add():
    """
    Create a worker with a fresh unique token_id.
    Form fields: name, department (both optional but recommended).
    """
    name = (request.form.get("name") or "").strip()
    department = (request.form.get("department") or "").strip()
    token_id = _new_token()

    pool = get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO workers (name, department, token_id)
                VALUES (%s, %s, %s)
                RETURNING id;
            """, (name, department, token_id))
            worker_id = cur.fetchone()[0]
        finally:
            cur.close()
        conn.commit()
    finally:
        pool.putconn(conn)

    return redirect(url_for("workers_page") + f"#w{worker_id}")

@app.route("/workers/<int:worker_id>/qr.png")
def worker_qr_png(worker_id: int):
    """
    Serve a PNG QR code for "W:<token>" (used by the ESP32 to login).
    """
    pool = get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        try:
            cur.execute("SELECT token_id FROM workers WHERE id=%s;", (worker_id,))
            row = cur.fetchone()
        finally:
            cur.close()
    finally:
        pool.putconn(conn)

    if not row or not row[0]:
        abort(404)

    qr = segno.make(f"W:{row[0]}")
    buf = io.BytesIO()
    # quiet_zone=2 keeps codes compact but still scannable
    qr.save(buf, kind="png", scale=6, border=2)  # scale ~ size, border ~ quiet zone
    buf.seek(0)
    return send_file(buf, mimetype="image/png", download_name=f"worker_{worker_id}.png")

@app.route("/workers/<int:worker_id>/qr.svg")
def worker_qr_svg(worker_id: int):
    """
    Serve an SVG QR code (vector).
    """
    pool = get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        try:
            cur.execute("SELECT token_id FROM workers WHERE id=%s;", (worker_id,))
            row = cur.fetchone()
        finally:
            cur.close()
    finally:
        pool.putconn(conn)

    if not row or not row[0]:
        abort(404)

    qr = segno.make(f"W:{row[0]}")
    buf = io.BytesIO()
    qr.save(buf, kind="svg", border=2)
    buf.seek(0)
    return send_file(buf, mimetype="image/svg+xml", download_name=f"worker_{worker_id}.svg")

@app.route("/api/workers")
def api_workers():
    """
    JSON list of workers (useful for any future front-end).
    """
    pool = get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT id, name, department, token_id
                  FROM workers
                 ORDER BY id DESC;
            """)
            data = [
                {"id": rid, "name": nm or "", "department": dp or "", "token_id": tk or ""}
                for (rid, nm, dp, tk) in cur.fetchall()
            ]
        finally:
            cur.close()
    finally:
        pool.putconn(conn)
    return jsonify(data)


# =========================
# Dashboard / Activities APIs (unchanged behavior)
# =========================
def _normalize_worker_token(raw: str) -> str:
    raw = (raw or "").strip()
    if raw.startswith("W:"):
        return raw[2:]
    return raw

def _normalize_barcode(raw: str) -> str:
    return (raw or "").strip()

def _lookup_or_create_worker_by_token(cur, token_raw: str) -> int:
    cur.execute("SELECT id FROM workers WHERE token_id = %s;", (token_raw,))
    row = cur.fetchone()
    if row:
        return row[0]
    placeholder_name = f"Worker {token_raw[:6]}" if token_raw else "Worker"
    cur.execute("""
        INSERT INTO workers (name, token_id)
        VALUES (%s, %s)
        ON CONFLICT (token_id) DO UPDATE SET token_id = EXCLUDED.token_id
        RETURNING id;
    """, (placeholder_name, token_raw))
    return cur.fetchone()[0]

def _fetch_worker_profile(cur, worker_id: int):
    cur.execute("SELECT name, COALESCE(NULLIF(department,''),'N/A') FROM workers WHERE id=%s;", (worker_id,))
    row = cur.fetchone() or ("Unknown", "N/A")
    return row[0], row[1]

def _today_pieces_for(cur, worker_id: int, start, end) -> int:
    cur.execute("""
        SELECT COUNT(*) FROM scans
         WHERE worker_id=%s AND created_at >= %s AND created_at <= %s;
    """, (worker_id, start, end))
    return cur.fetchone()[0]


@app.route("/api/stats")
def api_stats():
    pool = get_pool()
    start, end = today_bounds_utc()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        try:
            cur.execute("SELECT COUNT(*) FROM workers;")
            total_workers = cur.fetchone()[0]

            cur.execute("""
                SELECT COUNT(DISTINCT worker_id)
                  FROM scans
                 WHERE created_at >= %s AND created_at <= %s
                   AND worker_id IS NOT NULL;
            """, (start, end))
            active_today = cur.fetchone()[0]

            cur.execute("""
                SELECT COUNT(*)
                  FROM scans
                 WHERE created_at >= %s AND created_at <= %s;
            """, (start, end))
            scans_today = cur.fetchone()[0]
        finally:
            cur.close()
        return jsonify({
            "total_workers": total_workers,
            "active_today": active_today,
            "scans_today": scans_today
        })
    finally:
        pool.putconn(conn)


@app.route("/api/activities")
def api_activities():
    limit = max(1, min(int(request.args.get("limit", 100)), 500))
    pool = get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT
                    s.created_at AS ts,
                    COALESCE(w.name, '(unknown)') AS worker,
                    NULLIF(w.department,'') AS line,
                    NULLIF(s.operation_code,'') AS operation_code,
                    NULLIF(s.barcode,'') AS barcode
                FROM scans s
                LEFT JOIN workers w ON w.id = s.worker_id
                ORDER BY s.created_at DESC NULLS LAST
                LIMIT %s;
            """, (limit,))
            rows = cur.fetchall()
            data = []
            for ts, worker, line, op, bc in rows:
                ts_iso = ts.isoformat() if ts else None
                data.append({
                    "ts": ts_iso,
                    "worker": worker,
                    "line": line or "",
                    "operation_code": op or "",
                    "barcode": bc or ""
                })
        finally:
            cur.close()
        return jsonify(data)
    finally:
        pool.putconn(conn)


# =========================
# Device endpoints (match ESP32 sketch)
# =========================
@app.route("/scan", methods=["POST"])
def scan_login_or_ping():
    """
    Body: {"token_id":"W:<token>", "secret":"<DEVICE_SECRET>"}
    """
    payload = request.get_json(silent=True) or {}
    if (payload.get("secret") or "").strip() != DEVICE_SECRET:
        return jsonify({"status": "error", "message": "forbidden"}), 403

    token_raw = _normalize_worker_token(payload.get("token_id", ""))
    if not token_raw:
        return jsonify({"status":"error","message":"token_id required"}), 400

    start, end = today_bounds_utc()
    pool = get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        try:
            worker_id = _lookup_or_create_worker_by_token(cur, token_raw)
            name, department = _fetch_worker_profile(cur, worker_id)
            scans_today = _today_pieces_for(cur, worker_id, start, end)
        finally:
            cur.close()
        conn.commit()
    finally:
        pool.putconn(conn)

    return jsonify({
        "status": "success",
        "name": name,
        "department": department,
        "scans_today": scans_today,
        "earnings": scans_today * RATE_PER_PIECE
    })


@app.route("/scan_operation", methods=["POST"])
def scan_operation():
    """
    Body: {"token_id":"W:<token>","barcode":"B:...","secret":"<DEVICE_SECRET>"}
    """
    payload = request.get_json(silent=True) or {}
    if (payload.get("secret") or "").strip() != DEVICE_SECRET:
        return jsonify({"status": "error", "message": "forbidden"}), 403

    token_raw = _normalize_worker_token(payload.get("token_id", ""))
    barcode = _normalize_barcode(payload.get("barcode", ""))

    if not token_raw:
        return jsonify({"status":"error","message":"token_id required"}), 400
    if not barcode:
        return jsonify({"status":"error","message":"barcode required"}), 400

    start, end = today_bounds_utc()
    pool = get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        try:
            worker_id = _lookup_or_create_worker_by_token(cur, token_raw)

            # Try to parse operation code from barcode (e.g., "B:OP10-XYZ" -> "OP10")
            op_code = ""
            try:
                b = barcode[2:] if barcode.startswith("B:") else barcode
                op_code = b.split("-", 1)[0].strip() if b else ""
            except Exception:
                op_code = ""

            cur.execute("""
                INSERT INTO scans (worker_id, barcode, operation_code, created_at)
                VALUES (%s, %s, NULLIF(%s,''), NOW());
            """, (worker_id, barcode, op_code))

            scans_today = _today_pieces_for(cur, worker_id, start, end)
        finally:
            cur.close()
        conn.commit()
    finally:
        pool.putconn(conn)

    return jsonify({
        "status": "success",
        "scans_today": scans_today,
        "earnings": scans_today * RATE_PER_PIECE
    })


@app.route("/logout", methods=["POST"])
def logout():
    """
    ESP32 logs out locally when the same card is scanned again.
    No-op here: just return success for device compatibility.
    """
    payload = request.get_json(silent=True) or {}
    if (payload.get("secret") or "").strip() != DEVICE_SECRET:
        return jsonify({"status": "error", "message": "forbidden"}), 403
    return jsonify({"status": "success"})


# =========================
# Template globals
# =========================
@app.context_processor
def inject_globals():
    # Avoid using jinja `now()` filter (not always available); inject year here if you need it in templates.
    return dict(
        app_name="Banswara Scanner",
        brand="Banswara Scanner",
        rate_per_piece=RATE_PER_PIECE,
        current_year=datetime.now().year
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
