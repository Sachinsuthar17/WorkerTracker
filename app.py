import os
import math
from datetime import datetime, timezone, date
from contextlib import contextmanager

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
import psycopg2
from psycopg2.pool import SimpleConnectionPool

# -------------------- Config --------------------
APP_TITLE = "ESP32 Scanner Dashboard"

DATABASE_URL = os.getenv("DATABASE_URL")  # e.g. from Render PostgreSQL add-on
DEVICE_SECRET = os.getenv(
    "DEVICE_SECRET",
    "u38fh39fh28fh92hf928hfh92hF9H2hf92h3f9h2F"  # <- keep in sync with ESP32
)

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL env var is required")

app = Flask(__name__)
CORS(app)

# Gunicorn on Render will import app:app from this file.

# ---------------- Connection Pool ---------------
pool: SimpleConnectionPool | None = None
inited = False  # guarded initialisation since Flask 3 removed before_first_request

def make_pool():
    global pool
    if pool is None:
        pool = SimpleConnectionPool(
            1, 10, dsn=DATABASE_URL, sslmode="require"
        )

@contextmanager
def db() -> psycopg2.extensions.connection:
    if pool is None:
        make_pool()
    conn = pool.getconn()
    try:
        yield conn
    finally:
        pool.putconn(conn)

def ensure_schema(conn):
    with conn.cursor() as cur:
        # workers table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS workers (
                id SERIAL PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                department TEXT
            );
        """)
        # scans table (no bundle_id!)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS scans (
                id SERIAL PRIMARY KEY,
                worker_id INTEGER NOT NULL REFERENCES workers(id) ON DELETE CASCADE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                operation_code TEXT,
                barcode TEXT,
                quantity INTEGER NOT NULL DEFAULT 1,
                rate NUMERIC(10,2) NOT NULL DEFAULT 0.00
            );
        """)
        # simple helper index for today queries
        cur.execute("CREATE INDEX IF NOT EXISTS idx_scans_created_at ON scans (created_at DESC);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_scans_worker_id_created ON scans (worker_id, created_at DESC);")
    conn.commit()

def init_once():
    global inited
    if inited:
        return
    make_pool()
    with db() as conn:
        ensure_schema(conn)
    inited = True

@app.before_request
def _guard_init():
    # initialize only once and only when the process starts serving
    init_once()

# ---------------- Helper functions --------------
def today_bounds_utc():
    # today in UTC (works fine for server-side stats)
    today = date.today()
    start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    end = datetime(today.year, today.month, today.day, 23, 59, 59, 999999, tzinfo=timezone.utc)
    return start, end

def upsert_worker(conn, name: str):
    name = name.strip()
    if not name:
        raise ValueError("empty worker name")
    with conn.cursor() as cur:
        cur.execute("SELECT id, name, COALESCE(department,'') FROM workers WHERE LOWER(name)=LOWER(%s)", (name,))
        row = cur.fetchone()
        if row:
            return row[0], row[1], row[2]
        cur.execute("INSERT INTO workers(name) VALUES (%s) RETURNING id, name", (name,))
        row = cur.fetchone()
    conn.commit()
    return row[0], row[1], ""

def insert_scan(conn, worker_id: int, operation_code: str | None, barcode: str | None):
    # Simple business logic: each scan = 1 piece; rate determined by operation prefix if present
    qty = 1
    rate = 0.00
    if operation_code:
        # Example rule: OP<number> => rate by number*0.5 (you can adjust)
        # Plain, predictable, and safe if you don't have a rates table yet.
        try:
            num = int(''.join([c for c in operation_code if c.isdigit()]) or "0")
            rate = max(0, min(9999, num * 0.5))
        except Exception:
            rate = 0.00

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO scans (worker_id, operation_code, barcode, quantity, rate)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (worker_id, operation_code, barcode, qty, rate))
        _ = cur.fetchone()
    conn.commit()

def summarize_today(conn, worker_id: int | None = None):
    start, end = today_bounds_utc()
    with conn.cursor() as cur:
        if worker_id:
            cur.execute("""
                SELECT COALESCE(SUM(quantity),0) AS pieces,
                       COALESCE(SUM(quantity*rate),0) AS earn
                FROM scans
                WHERE created_at BETWEEN %s AND %s
                  AND worker_id = %s
            """, (start, end, worker_id))
        else:
            cur.execute("""
                SELECT COALESCE(SUM(quantity),0) AS pieces,
                       COALESCE(SUM(quantity*rate),0) AS earn
                FROM scans
                WHERE created_at BETWEEN %s AND %s
            """, (start, end))
        row = cur.fetchone()
        pieces = int(row[0] or 0)
        earn = float(row[1] or 0.0)
    return pieces, earn

# ----------------- Routes (UI) -------------------
@app.route("/")
def dashboard():
    # Your dashboard.html should call /api/stats and /api/activities via fetch()
    return render_template("dashboard.html", app_title=APP_TITLE)

@app.route("/workers")
def workers_page():
    return render_template("workers.html", app_title=APP_TITLE)

@app.route("/operations")
def operations_page():
    return render_template("operations.html", app_title=APP_TITLE)

@app.route("/reports")
def reports_page():
    return render_template("reports.html", app_title=APP_TITLE)

@app.route("/settings")
def settings_page():
    return render_template("settings.html", app_title=APP_TITLE)

@app.route("/assign_operation")
def assign_operation_page():
    return render_template("assign_operation.html", app_title=APP_TITLE)

# --------------- Routes (API) --------------------
@app.route("/api/stats")
def api_stats():
    with db() as conn:
        total_pieces, total_earn = summarize_today(conn, None)
        # active workers today
        start, end = today_bounds_utc()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(DISTINCT worker_id)
                FROM scans
                WHERE created_at BETWEEN %s AND %s
            """, (start, end))
            active_workers = cur.fetchone()[0] or 0

            cur.execute("""
                SELECT COUNT(DISTINCT COALESCE(operation_code, ''))
                FROM scans
                WHERE created_at BETWEEN %s AND %s
            """, (start, end))
            distinct_ops = cur.fetchone()[0] or 0

        return jsonify({
            "pieces_today": total_pieces,
            "earn_today": round(total_earn, 2),
            "active_workers": active_workers,
            "operations_today": distinct_ops
        })

@app.route("/api/activities")
def api_activities():
    """
    Recent activity stream for the dashboard.
    No bundle_id, no bundles join. Only workers + scans.
    Optional filters: ?worker=<name>&q=<text>&limit=100
    """
    limit = max(1, min(200, int(request.args.get("limit", 100))))
    worker_name = request.args.get("worker", "").strip()
    q = request.args.get("q", "").strip()

    params = []
    wheres = []
    sql = """
        SELECT
            s.created_at AS ts,
            w.name AS worker,
            COALESCE(s.operation_code, '') AS op,
            COALESCE(s.barcode, '') AS barcode,
            s.quantity,
            s.rate,
            (s.quantity * s.rate) AS amount
        FROM scans s
        JOIN workers w ON w.id = s.worker_id
    """

    if worker_name:
        wheres.append("LOWER(w.name) = LOWER(%s)")
        params.append(worker_name)

    if q:
        # search in op/barcode
        wheres.append("(LOWER(COALESCE(s.operation_code,'')) LIKE LOWER(%s) OR LOWER(COALESCE(s.barcode,'')) LIKE LOWER(%s))")
        params.extend([f"%{q}%", f"%{q}%"])

    if wheres:
        sql += " WHERE " + " AND ".join(wheres)

    sql += " ORDER BY s.created_at DESC LIMIT %s"
    params.append(limit)

    with db() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
        activities = []
        for r in rows:
            ts, worker, op, barcode, qty, rate, amount = r
            activities.append({
                "timestamp": ts.isoformat(),
                "worker": worker,
                "operation": op,
                "barcode": barcode,
                "qty": qty,
                "rate": float(rate),
                "amount": float(amount)
            })
    return jsonify({"items": activities})

@app.route("/scan", methods=["POST"])
def scan():
    """
    Single unified endpoint for the ESP32.

    Input JSON:
      {
        "secret": "...",
        "worker_name": "Alice",
        "operation_code": "OP10",   # optional
        "barcode": "123456",        # optional
      }
    Output JSON:
      {
        "ok": true,
        "today_pieces": 12,
        "today_earn": 60.0
      }
    """
    data = request.get_json(silent=True) or {}
    secret = str(data.get("secret", "")).strip()
    if not secret or secret != DEVICE_SECRET:
        return jsonify({"ok": False, "error": "Forbidden"}), 403

    worker_name = str(data.get("worker_name", "")).strip()
    if not worker_name:
        return jsonify({"ok": False, "error": "worker_name is required"}), 400

    op = data.get("operation_code")
    op = str(op).strip() if op else None
    bc = data.get("barcode")
    bc = str(bc).strip() if bc else None

    try:
        with db() as conn:
            worker_id, _, _ = upsert_worker(conn, worker_name)

            # Insert a scan if an operation or barcode is provided.
            # If neither is provided, we just make sure the worker exists and return his/her today totals.
            if op or bc:
                insert_scan(conn, worker_id, op, bc)

            pieces, earn = summarize_today(conn, worker_id)

        return jsonify({
            "ok": True,
            "today_pieces": pieces,
            "today_earn": round(earn, 2)
        })
    except Exception as e:
        # Log to console
        print("ERROR in /scan:", e)
        return jsonify({"ok": False, "error": "server error"}), 500


# -------------- Health & Ping --------------------
@app.route("/healthz")
def healthz():
    return "ok", 200


# -------------- Main (local dev) ----------------
if __name__ == "__main__":
    # Local debug
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")), debug=True)
