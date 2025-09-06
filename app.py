import os
import threading
from datetime import datetime, timezone
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

_pool: SimpleConnectionPool | None = None
_inited = False
_init_lock = threading.Lock()


def get_pool() -> SimpleConnectionPool:
    global _pool
    if _pool is None:
        _pool = SimpleConnectionPool(1, 12, dsn=DATABASE_URL, sslmode="require")
    return _pool


def ensure_schema(conn: psycopg2.extensions.connection) -> None:
    """
    Idempotent, legacy-safe schema bootstrap.
    It:
      - Creates workers/scans tables if missing
      - Adds missing columns (worker_id, barcode, operation_code, created_at)
      - Adds FK only if worker_id exists
      - Creates indexes only when required columns exist
    """
    cur = conn.cursor()
    try:
        # ---- workers table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS workers (
                id SERIAL PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                department TEXT DEFAULT ''
            );
        """)

        # ---- scans table (create minimal if missing)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS scans (
                id SERIAL PRIMARY KEY
            );
        """)

        # ---- add missing columns to scans
        # worker_id
        cur.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                 WHERE table_name='scans' AND column_name='worker_id'
            ) THEN
                ALTER TABLE scans ADD COLUMN worker_id INTEGER;
            END IF;
        END
        $$;
        """)

        # barcode
        cur.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                 WHERE table_name='scans' AND column_name='barcode'
            ) THEN
                ALTER TABLE scans ADD COLUMN barcode TEXT;
            END IF;
        END
        $$;
        """)

        # operation_code
        cur.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                 WHERE table_name='scans' AND column_name='operation_code'
            ) THEN
                ALTER TABLE scans ADD COLUMN operation_code TEXT;
            END IF;
        END
        $$;
        """)

        # created_at with default
        cur.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                 WHERE table_name='scans' AND column_name='created_at'
            ) THEN
                ALTER TABLE scans ADD COLUMN created_at TIMESTAMPTZ DEFAULT NOW();
            END IF;
        END
        $$;
        """)

        # If a legacy column 'scanned_at' exists, use it to backfill created_at where null
        cur.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                 WHERE table_name='scans' AND column_name='scanned_at'
            ) THEN
                UPDATE scans
                   SET created_at = COALESCE(created_at, scanned_at)
                 WHERE created_at IS NULL;
            END IF;
        END
        $$;
        """)

        # ---- add FK only if not present and both tables/column exist
        cur.execute("""
        DO $$
        DECLARE
            fk_exists BOOLEAN;
            col_exists BOOLEAN;
        BEGIN
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                 WHERE table_name='scans' AND column_name='worker_id'
            ) INTO col_exists;

            SELECT EXISTS (
                SELECT 1 FROM pg_constraint
                 WHERE conname = 'scans_worker_id_fkey'
            ) INTO fk_exists;

            IF col_exists AND NOT fk_exists THEN
                -- Make sure any orphan values don't block FK add
                -- (You can delete/clean later if needed.)
                ALTER TABLE scans
                ADD CONSTRAINT scans_worker_id_fkey
                FOREIGN KEY (worker_id) REFERENCES workers(id)
                ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED;
            END IF;
        END
        $$;
        """)

        # ---- indexes (only when columns exist)
        # created_at index
        cur.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                 WHERE table_name='scans' AND column_name='created_at'
            ) THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_scans_created_at ON scans (created_at DESC)';
            END IF;
        END
        $$;
        """)

        # (worker_id, created_at) index
        cur.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                 WHERE table_name='scans' AND column_name='worker_id'
            ) AND EXISTS (
                SELECT 1 FROM information_schema.columns
                 WHERE table_name='scans' AND column_name='created_at'
            ) THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_scans_worker ON scans (worker_id, created_at DESC)';
            END IF;
        END
        $$;
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
# Pages
# =========================
@app.route("/")
def dashboard():
    return render_template("dashboard.html")

@app.route("/workers")
def workers_page():
    return render_template("workers.html")

@app.route("/operations")
def operations_page():
    return render_template("operations.html")

@app.route("/reports")
def reports_page():
    return render_template("reports.html")

@app.route("/settings")
def settings_page():
    return render_template("settings.html")

@app.route("/assign_operation")
def assign_operation_page():
    return render_template("assign_operation.html")


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
                    s.operation_code,
                    s.barcode
                FROM scans s
                LEFT JOIN workers w ON w.id = s.worker_id
                ORDER BY s.created_at DESC NULLS LAST
                LIMIT 100;
            """)
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
# Unified device endpoint
# (aligns with the revised ESP32 sketch I gave you:
#   sends secret + worker_name + optional barcode/operation_code)
# =========================
@app.route("/scan", methods=["POST"])
def scan():
    """
    JSON body:
    {
      "secret": "<DEVICE_SECRET>",
      "worker_name": "Sachin",
      "barcode": "B:XYZ123",         # optional
      "operation_code": "OP10"       # optional
    }
    """
    payload = request.get_json(silent=True) or {}
    secret = (payload.get("secret") or "").strip()
    worker_name = (payload.get("worker_name") or "").strip()
    barcode = (payload.get("barcode") or "").strip()
    operation_code = (payload.get("operation_code") or "").strip()

    if secret != DEVICE_SECRET:
        return jsonify({"ok": False, "error": "forbidden"}), 403
    if not worker_name:
        return jsonify({"ok": False, "error": "worker_name required"}), 400

    start, end = today_bounds_utc()
    pool = get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        try:
            # upsert worker
            cur.execute("""
                INSERT INTO workers (name)
                VALUES (%s)
                ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
                RETURNING id;
            """, (worker_name,))
            worker_id = cur.fetchone()[0]

            # record a scan if any detail provided
            if barcode or operation_code:
                cur.execute("""
                    INSERT INTO scans (worker_id, barcode, operation_code, created_at)
                    VALUES (%s, NULLIF(%s,''), NULLIF(%s,''), NOW());
                """, (worker_id, barcode, operation_code))

            # today's totals
            cur.execute("""
                SELECT COUNT(*)
                  FROM scans
                 WHERE worker_id = %s
                   AND created_at >= %s AND created_at <= %s;
            """, (worker_id, start, end))
            today_pieces = cur.fetchone()[0]
        finally:
            cur.close()

        conn.commit()
        return jsonify({
            "ok": True,
            "today_pieces": today_pieces,
            "today_earn": today_pieces * RATE_PER_PIECE
        })
    finally:
        pool.putconn(conn)


@app.context_processor
def inject_globals():
    return dict(app_name="Banswara Scanner")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
