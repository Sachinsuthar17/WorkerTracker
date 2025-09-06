import os
import threading
from datetime import datetime, timezone
from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
import psycopg2
from psycopg2.pool import SimpleConnectionPool

# -------------------------
# Config
# -------------------------
DEVICE_SECRET = os.getenv("DEVICE_SECRET", "u38fh39fh28fh92hf928hfh92hF9H2hf92h3f9h2F")
DATABASE_URL  = os.getenv("DATABASE_URL")  # Render Postgres URL
RATE_PER_PIECE = float(os.getenv("RATE_PER_PIECE", "1.0"))  # INR earned per piece

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
    Create/upgrade schema safely. No nested 'with conn:' here.
    """
    cur = conn.cursor()
    try:
        # workers
        cur.execute("""
            CREATE TABLE IF NOT EXISTS workers (
                id SERIAL PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                department TEXT DEFAULT ''
            );
        """)

        # scans (generic)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS scans (
                id SERIAL PRIMARY KEY,
                worker_id INTEGER NOT NULL REFERENCES workers(id) ON DELETE CASCADE,
                barcode TEXT,
                operation_code TEXT
            );
        """)

        # created_at column (add if missing)
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

        # Backfill from legacy scanned_at if present
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

        # Indexes
        cur.execute("CREATE INDEX IF NOT EXISTS idx_scans_created_at ON scans (created_at DESC);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_scans_worker ON scans (worker_id, created_at DESC);")
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
    # Make sure schema exists before handling any request
    init_once()


def today_bounds_utc():
    now = datetime.now(timezone.utc)
    start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    end = datetime(now.year, now.month, now.day, 23, 59, 59, 999999, tzinfo=timezone.utc)
    return start, end


# -------------------------
# Pages
# -------------------------
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


# -------------------------
# APIs for dashboard widgets
# -------------------------
@app.route("/api/stats")
def api_stats():
    pool = get_pool()
    start, end = today_bounds_utc()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        try:
            # total workers
            cur.execute("SELECT COUNT(*) FROM workers;")
            total_workers = cur.fetchone()[0]

            # active today
            cur.execute("""
                SELECT COUNT(DISTINCT worker_id)
                  FROM scans
                 WHERE created_at >= %s AND created_at <= %s;
            """, (start, end))
            active_today = cur.fetchone()[0]

            # scans today
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
                    w.name       AS worker,
                    NULLIF(w.department,'') AS line,
                    s.operation_code,
                    s.barcode
                FROM scans s
                JOIN workers w ON w.id = s.worker_id
                ORDER BY s.created_at DESC
                LIMIT 100;
            """)
            rows = cur.fetchall()
            data = []
            for ts, worker, line, op, bc in rows:
                data.append({
                    "ts": ts.isoformat(),
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


# -------------------------
# Unified device endpoint (matches your ESP32 sketch)
# -------------------------
@app.route("/scan", methods=["POST"])
def scan():
    """
    ESP32 JSON body:
    {
      "secret": "<DEVICE_SECRET>",
      "worker_name": "Sachin",
      "barcode": "B:XYZ123",       # optional
      "operation_code": "OP10"     # optional
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

            # record a scan if barcode/operation provided
            if barcode or operation_code:
                cur.execute("""
                    INSERT INTO scans (worker_id, barcode, operation_code, created_at)
                    VALUES (%s, NULLIF(%s,''), NULLIF(%s,''), NOW());
                """, (worker_id, barcode, operation_code))

            # today's totals for this worker
            cur.execute("""
                SELECT COUNT(*)
                  FROM scans
                 WHERE worker_id = %s
                   AND created_at >= %s
                   AND created_at <= %s;
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


# -------------------------
# Jinja globals
# -------------------------
@app.context_processor
def inject_globals():
    return dict(app_name="Banswara Scanner")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
