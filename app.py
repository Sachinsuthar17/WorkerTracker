import os
import threading
from datetime import datetime, timezone
from typing import Optional

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
import psycopg2
from psycopg2.pool import SimpleConnectionPool

# =========================
# Config
# =========================
DEVICE_SECRET = os.getenv("DEVICE_SECRET", "u38fh39fh28fh92hf928hfh92hF9H2hf92h3f9h2F")
DATABASE_URL  = os.getenv("DATABASE_URL")  # Render Postgres URL
RATE_PER_PIECE = float(os.getenv("RATE_PER_PIECE", "1.0"))  # INR per piece

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required")

app = Flask(__name__)
CORS(app)

_pool: Optional[SimpleConnectionPool] = None
_inited = False
_init_lock = threading.Lock()


def get_pool() -> SimpleConnectionPool:
    global _pool
    if _pool is None:
        _pool = SimpleConnectionPool(minconn=1, maxconn=12, dsn=DATABASE_URL, sslmode="require")
    return _pool


def ensure_schema(conn: psycopg2.extensions.connection) -> None:
    """
    Idempotent, legacy-safe schema bootstrap.
    Creates/patches:
      - workers(id, name, department, token_id UNIQUE)
      - scans(id, worker_id, barcode, operation_code, created_at TIMESTAMPTZ)
    Adds FK and useful indexes if missing.
    """
    cur = conn.cursor()
    try:
        # workers
        cur.execute("""
            CREATE TABLE IF NOT EXISTS workers (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                department TEXT NOT NULL DEFAULT '',
                token_id TEXT UNIQUE
            );
        """)

        # scans (create minimal if missing)
        cur.execute("CREATE TABLE IF NOT EXISTS scans (id SERIAL PRIMARY KEY);")

        # ---- add/patch columns on scans
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

        # backfill from legacy column if present
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

        # FK for worker_id
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

        # indexes
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
# Pages (templates must exist in /templates)
# =========================
@app.route("/")
def dashboard():
    return render_template("dashboard.html", rate_per_piece=RATE_PER_PIECE)

@app.route("/workers")
def workers_page():
    return render_template("workers.html", rate_per_piece=RATE_PER_PIECE)

@app.route("/operations")
def operations_page():
    return render_template("operations.html", rate_per_piece=RATE_PER_PIECE)

@app.route("/reports")
def reports_page():
    return render_template("reports.html", rate_per_piece=RATE_PER_PIECE)

@app.route("/settings")
def settings_page():
    # Fix for earlier 'rate_per_piece is undefined'
    return render_template("settings.html", rate_per_piece=RATE_PER_PIECE)

@app.route("/assign_operation")
def assign_operation_page():
    return render_template("assign_operation.html", rate_per_piece=RATE_PER_PIECE)


# =========================
# API: Dashboard data
# =========================
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
            cur.execute(f"""
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
# Device endpoints (match your ESP32 sketch)
# =========================
def _normalize_worker_token(raw: str) -> str:
    raw = (raw or "").strip()
    if raw.startswith("W:"):
        return raw[2:]
    return raw

def _normalize_barcode(raw: str) -> str:
    raw = (raw or "").strip()
    # keep "B:" if present; store raw to preserve bundle code as-is
    return raw

def _lookup_or_create_worker_by_token(cur, token_raw: str) -> int:
    # If worker with this token exists -> id
    cur.execute("SELECT id FROM workers WHERE token_id = %s;", (token_raw,))
    row = cur.fetchone()
    if row:
        return row[0]
    # else create a placeholder worker with this token
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


@app.route("/scan", methods=["POST"])
def scan_login_or_ping():
    """
    Matches ESP32 'handleLoginScan':
    Body: {"token_id":"W:<token>", "secret":"<DEVICE_SECRET>"}
    Response: {"status":"success","name":..,"department":..,"scans_today":<int>,"earnings":<float>}
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
    Matches ESP32 bundle scan:
    Body: {"token_id":"W:<token>","barcode":"B:...","secret":"<DEVICE_SECRET>"}
    Response: {"status":"success","scans_today":<int>,"earnings":<float>}
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

            # Operation code (optional): try to parse from barcode "B:OP10-XXXX" -> "OP10"
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
    We keep this endpoint for compatibility (no-op) so device gets 200.
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
    return dict(
        app_name="Banswara Scanner",
        rate_per_piece=RATE_PER_PIECE
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
