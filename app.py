import os
from datetime import datetime, timezone, date
from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
import psycopg2
from psycopg2.pool import SimpleConnectionPool

# -------------------------
# Config
# -------------------------
DEVICE_SECRET = os.getenv("DEVICE_SECRET", "u38fh39fh28fh92hf928hfh92hF9H2hf92h3f9h2F")
DATABASE_URL  = os.getenv("DATABASE_URL")
RATE_PER_PIECE = float(os.getenv("RATE_PER_PIECE", "1.0"))  # used for 'earnings'

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required (Render Postgres connection string)")

app = Flask(__name__)
CORS(app)

_pool = None
_inited = False


def get_pool() -> SimpleConnectionPool:
    global _pool
    if _pool is None:
        _pool = SimpleConnectionPool(
            1, 10, dsn=DATABASE_URL, sslmode="require"
        )
    return _pool


def ensure_schema(conn):
    """
    Create/upgrade schema safely.
    Compatible with legacy tables that may have 'scanned_at' instead of 'created_at'.
    """
    with conn, conn.cursor() as cur:
        # workers
        cur.execute("""
        CREATE TABLE IF NOT EXISTS workers (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            department TEXT DEFAULT ''
        );
        """)

        # scans (use minimal, generic columns; server unifies all scan types)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS scans (
            id SERIAL PRIMARY KEY,
            worker_id INTEGER NOT NULL REFERENCES workers(id) ON DELETE CASCADE,
            barcode TEXT,
            operation_code TEXT
        );
        """)

        # Add created_at if missing
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

        # If legacy 'scanned_at' exists, backfill created_at from it
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


def init_once():
    global _inited
    if _inited:
        return
    pool = get_pool()
    with pool.getconn() as conn:
        try:
            ensure_schema(conn)
        finally:
            pool.putconn(conn)
    _inited = True


@app.before_request
def _guard_init():
    # Flask 2/3 compatible: ensure we init once before handling requests
    init_once()


def today_bounds_utc():
    """Return (start, end) of 'today' in UTC for simple daily rollups."""
    # You can replace with local timezone if you prefer.
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
    with pool.getconn() as conn:
        try:
            with conn.cursor() as cur:
                # total workers
                cur.execute("SELECT COUNT(*) FROM workers;")
                total_workers = cur.fetchone()[0]

                # active today (distinct workers who scanned today)
                cur.execute("""
                    SELECT COUNT(DISTINCT s.worker_id)
                      FROM scans s
                     WHERE COALESCE(s.created_at, NOW()) >= %s
                       AND COALESCE(s.created_at, NOW()) <= %s;
                """, (start, end))
                active_today = cur.fetchone()[0]

                # scans today
                cur.execute("""
                    SELECT COUNT(*)
                      FROM scans s
                     WHERE COALESCE(s.created_at, NOW()) >= %s
                       AND COALESCE(s.created_at, NOW()) <= %s;
                """, (start, end))
                scans_today = cur.fetchone()[0]

                return jsonify({
                    "total_workers": total_workers,
                    "active_today": active_today,
                    "scans_today": scans_today
                })
        finally:
            pool.putconn(conn)


@app.route("/api/activities")
def api_activities():
    """
    Recent activity feed for dashboard.
    No 'bundle_id' anywhere. Only workers + scans.
    """
    pool = get_pool()
    with pool.getconn() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        COALESCE(s.created_at, NOW()) AS ts,
                        w.name        AS worker,
                        NULLIF(w.department, '') AS line,
                        s.operation_code,
                        s.barcode
                    FROM scans s
                    JOIN workers w ON w.id = s.worker_id
                    ORDER BY COALESCE(s.created_at, NOW()) DESC
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
                return jsonify(data)
        finally:
            pool.putconn(conn)


# -------------------------
# Unified device endpoint
# -------------------------
@app.route("/scan", methods=["POST"])
def scan():
    """
    ESP32 posts JSON: {
      "secret": "...",
      "worker_name": "Sachin",
      "barcode": "B123"          # optional
      # "operation_code": "OP10" # optional
    }
    - If only worker_name is present -> treat as login/refresh.
    - If barcode/operation_code present -> record a piece, then return today's rollup.
    """
    payload = request.get_json(silent=True) or {}
    secret = payload.get("secret", "")
    worker_name = (payload.get("worker_name") or "").strip()
    barcode = (payload.get("barcode") or "").strip()
    operation_code = (payload.get("operation_code") or "").strip()

    if secret != DEVICE_SECRET:
        return jsonify({"ok": False, "error": "forbidden"}), 403

    if not worker_name:
        return jsonify({"ok": False, "error": "worker_name required"}), 400

    pool = get_pool()
    start, end = today_bounds_utc()
    with pool.getconn() as conn:
        try:
            with conn:
                with conn.cursor() as cur:
                    # upsert worker
                    cur.execute("""
                        INSERT INTO workers (name)
                        VALUES (%s)
                        ON CONFLICT (name) DO UPDATE SET name=EXCLUDED.name
                        RETURNING id;
                    """, (worker_name,))
                    worker_id = cur.fetchone()[0]

                    # if there is something to record, insert a scan row
                    if barcode or operation_code:
                        cur.execute("""
                            INSERT INTO scans (worker_id, barcode, operation_code, created_at)
                            VALUES (%s, NULLIF(%s, ''), NULLIF(%s, ''), NOW());
                        """, (worker_id, barcode, operation_code))

                    # roll up today's totals for this worker
                    cur.execute("""
                        SELECT COUNT(*)
                          FROM scans
                         WHERE worker_id = %s
                           AND COALESCE(created_at, NOW()) >= %s
                           AND COALESCE(created_at, NOW()) <= %s;
                    """, (worker_id, start, end))
                    today_pieces = cur.fetchone()[0]
                    today_earn = today_pieces * RATE_PER_PIECE

            # return response
            return jsonify({
                "ok": True,
                "today_pieces": today_pieces,
                "today_earn": today_earn
            })
        finally:
            pool.putconn(conn)


# -------------------------
# Jinja (Render templates live from /templates)
# -------------------------
@app.context_processor
def inject_globals():
    return dict(app_name="Banswara Scanner")


if __name__ == "__main__":
    # Local run (Render runs via Gunicorn)
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
