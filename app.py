import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from flask import Flask, jsonify, render_template, request, redirect, url_for
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor, RealDictRow

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
PORT = int(os.environ.get("PORT", "10000"))
DATABASE_URL = os.environ.get("DATABASE_URL")  # e.g. render PostgreSQL URL
DEVICE_SECRET = os.environ.get("DEVICE_SECRET", "changeme")
RATE_PER_PIECE = float(os.environ.get("RATE_PER_PIECE", "5.0"))

app = Flask(__name__)
CORS(app)

# -----------------------------------------------------------------------------
# DB helpers
# -----------------------------------------------------------------------------
def _db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not configured")
    # Render gives postgres://; psycopg prefers postgresql://
    dburl = DATABASE_URL.replace("postgres://", "postgresql://")
    return psycopg2.connect(dburl)

def _rate_sql():
    """
    Returns the SQL expression that calculates the amount earned for a scan.
    We pay priority to an operation-specific rate if available, falling back to env rate.
    """
    # ops.rate_per_piece is optional; COALESCE to env default
    return f"COALESCE(ops.rate_per_piece, {RATE_PER_PIECE})"

# -----------------------------------------------------------------------------
# Bootstrap (create minimal schema if missing)
# -----------------------------------------------------------------------------
BOOTSTRAP_SQL = """
CREATE TABLE IF NOT EXISTS workers (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    department TEXT
);

CREATE TABLE IF NOT EXISTS operations (
    id SERIAL PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    description TEXT,
    rate_per_piece NUMERIC
);

CREATE TABLE IF NOT EXISTS worker_operations (
    id SERIAL PRIMARY KEY,
    worker_id INTEGER NOT NULL REFERENCES workers(id) ON DELETE CASCADE,
    operation_id INTEGER NOT NULL REFERENCES operations(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS scans (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES workers(id) ON DELETE CASCADE,
    operation_id INTEGER REFERENCES operations(id),
    barcode TEXT,
    scanned_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Helpful indexes
CREATE INDEX IF NOT EXISTS idx_scans_scanned_at ON scans(scanned_at DESC);
CREATE INDEX IF NOT EXISTS idx_scans_user_id ON scans(user_id);
CREATE INDEX IF NOT EXISTS idx_scans_operation_id ON scans(operation_id);
"""

@app.before_first_request
def bootstrap():
    try:
        with _db() as conn, conn.cursor() as cur:
            cur.execute(BOOTSTRAP_SQL)
    except Exception as e:
        app.logger.error("Bootstrap failed: %s", e)

# -----------------------------------------------------------------------------
# Pages
# -----------------------------------------------------------------------------
@app.route("/")
def dashboard():
    return render_template("dashboard.html")

@app.route("/production")
def production():  # keep endpoint name 'production' for layout links
    return redirect(url_for("dashboard"))

@app.route("/workers")
def workers():
    # list workers
    with _db() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id, name, department FROM workers ORDER BY name;")
        rows = cur.fetchall()
    return render_template("workers.html", workers=rows)

@app.route("/operations")
def operations_page():
    with _db() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id, code, description, rate_per_piece FROM operations ORDER BY code;")
        ops = cur.fetchall()
    return render_template("operations.html", operations=ops)

@app.route("/assign")
def assign_operations():  # keep name 'assign_operations' for layout links
    # fetch workers + operations for the form
    with _db() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id, name FROM workers ORDER BY name;")
        workers = cur.fetchall()
        cur.execute("SELECT id, code FROM operations ORDER BY code;")
        ops = cur.fetchall()
        cur.execute("""
            SELECT wo.id, w.name AS worker, o.code AS operation
            FROM worker_operations wo
            JOIN workers w ON w.id = wo.worker_id
            JOIN operations o ON o.id = wo.operation_id
            ORDER BY w.name, o.code;
        """)
        assigned = cur.fetchall()
    return render_template("assign_operation.html", workers=workers, operations=ops, assignments=assigned)

@app.route("/reports")
def reports():
    return render_template("reports.html")

@app.route("/settings")
def settings():
    return render_template("settings.html", rate_per_piece=RATE_PER_PIECE, device_secret_set=bool(DEVICE_SECRET))

# -----------------------------------------------------------------------------
# JSON/AJAX endpoints for forms
# -----------------------------------------------------------------------------
@app.post("/workers/add")
def add_worker():
    data = request.form or request.json or {}
    name = (data.get("name") or "").strip()
    dept = (data.get("department") or "").strip() or None
    if not name:
        return jsonify({"ok": False, "error": "name is required"}), 400
    with _db() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("INSERT INTO workers(name, department) VALUES(%s,%s) RETURNING id;", (name, dept))
        wid = cur.fetchone()["id"]
    return jsonify({"ok": True, "id": wid})

@app.post("/operations/add")
def add_operation():
    data = request.form or request.json or {}
    code = (data.get("code") or "").strip()
    desc = (data.get("description") or "").strip() or None
    rate = data.get("rate_per_piece")
    rate_val = float(rate) if rate not in (None, "",) else None
    if not code:
        return jsonify({"ok": False, "error": "code is required"}), 400
    with _db() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "INSERT INTO operations(code, description, rate_per_piece) VALUES(%s,%s,%s) RETURNING id;",
            (code, desc, rate_val)
        )
        oid = cur.fetchone()["id"]
    return jsonify({"ok": True, "id": oid})

@app.post("/assign/save")
def assign_operation_json():
    data = request.form or request.json or {}
    worker_id = data.get("worker_id")
    operation_id = data.get("operation_id")
    if not worker_id or not operation_id:
        return jsonify({"ok": False, "error": "worker_id and operation_id are required"}), 400
    with _db() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        # avoid duplicates
        cur.execute("""
            SELECT 1 FROM worker_operations
            WHERE worker_id=%s AND operation_id=%s
        """, (worker_id, operation_id))
        if not cur.fetchone():
            cur.execute("""
                INSERT INTO worker_operations(worker_id, operation_id) VALUES(%s,%s);
            """, (worker_id, operation_id))
    return jsonify({"ok": True})

@app.post("/assign/delete")
def delete_assignment():
    data = request.form or request.json or {}
    aid = data.get("assignment_id")
    if not aid:
        return jsonify({"ok": False, "error": "assignment_id is required"}), 400
    with _db() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM worker_operations WHERE id=%s;", (aid,))
    return jsonify({"ok": True})

# -----------------------------------------------------------------------------
# Dashboard APIs
# -----------------------------------------------------------------------------
@app.get("/api/stats")
def api_stats():
    """Return quick totals for 'today' in server UTC."""
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    with _db() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(f"""
            SELECT 
                COUNT(s.id) AS pieces,
                COALESCE(SUM({_rate_sql()}), 0) AS amount
            FROM scans s
            LEFT JOIN operations ops ON ops.id = s.operation_id
            WHERE s.scanned_at >= %s AND s.scanned_at < %s;
        """, (start, end))
        row: RealDictRow = cur.fetchone()
    return jsonify({
        "pieces": int(row["pieces"] or 0),
        "amount": float(row["amount"] or 0.0)
    })

@app.get("/api/activities")
def api_activities():
    """
    Latest 100 scan events with worker name, department (line), operation code, and amount.
    IMPORTANT: Does NOT assume 'bundle_id' exists; no join to bundles.
    """
    limit = int(request.args.get("limit", 100))
    limit = max(1, min(limit, 200))

    with _db() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(f"""
            SELECT
                s.scanned_at AS ts,
                w.name AS worker,
                w.department AS line,
                ops.code AS operation,
                {_rate_sql()} AS amount,
                s.barcode AS barcode
            FROM scans s
            LEFT JOIN workers w ON w.id = s.user_id
            LEFT JOIN operations ops ON ops.id = s.operation_id
            ORDER BY s.scanned_at DESC
            LIMIT %s;
        """, (limit,))
        rows = cur.fetchall()

    out = []
    for r in rows:
        out.append({
            "ts": r["ts"].isoformat() if r["ts"] else None,
            "worker": r["worker"],
            "line": r["line"],
            "operation": r["operation"],
            "amount": float(r["amount"] or 0.0),
            "barcode": r.get("barcode"),
        })
    return jsonify(out)

# -----------------------------------------------------------------------------
# ESP32 Scanner endpoint
# -----------------------------------------------------------------------------
@app.post("/scan")
def scan_login():
    """
    ESP32 should POST JSON like:
    {
        "secret": "<DEVICE_SECRET>",
        "worker_name": "Alice",           # OR "worker_id": 1
        "department": "Line A",           # optional, created if worker new
        "operation_code": "OP10",         # optional
        "barcode": "1234567890"           # optional
    }
    """
    data = request.json or {}
    if data.get("secret") != DEVICE_SECRET:
        return jsonify({"ok": False, "error": "unauthorized"}), 403

    worker_id = data.get("worker_id")
    worker_name = (data.get("worker_name") or "").strip()
    department = (data.get("department") or "").strip() or None
    operation_id = None

    with _db() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        # ensure worker
        if not worker_id:
            if not worker_name:
                return jsonify({"ok": False, "error": "worker_name or worker_id required"}), 400
            cur.execute("SELECT id FROM workers WHERE name=%s;", (worker_name,))
            w = cur.fetchone()
            if w:
                worker_id = w["id"]
                # optionally update department if provided and currently null
                if department:
                    cur.execute("UPDATE workers SET department=%s WHERE id=%s AND (department IS NULL OR department='');",
                                (department, worker_id))
            else:
                cur.execute("INSERT INTO workers(name, department) VALUES(%s,%s) RETURNING id;",
                            (worker_name, department))
                worker_id = cur.fetchone()["id"]

        # ensure operation if code provided
        op_code = (data.get("operation_code") or "").strip()
        if op_code:
            cur.execute("SELECT id FROM operations WHERE code=%s;", (op_code,))
            op = cur.fetchone()
            if op:
                operation_id = op["id"]
            else:
                cur.execute("INSERT INTO operations(code) VALUES(%s) RETURNING id;", (op_code,))
                operation_id = cur.fetchone()["id"]

        barcode = (data.get("barcode") or "").strip() or None

        # insert scan
        cur.execute("""
            INSERT INTO scans(user_id, operation_id, barcode, scanned_at)
            VALUES(%s,%s,%s,NOW())
            RETURNING id, scanned_at;
        """, (worker_id, operation_id, barcode))
        row = cur.fetchone()

        # compute today's pieces & earnings for this worker
        now = datetime.now(timezone.utc)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        cur.execute(f"""
            SELECT 
                COUNT(s.id) AS pcs,
                COALESCE(SUM({_rate_sql()}), 0) AS earn
            FROM scans s
            LEFT JOIN operations ops ON ops.id = s.operation_id
            WHERE s.user_id=%s AND s.scanned_at >= %s AND s.scanned_at < %s;
        """, (worker_id, start, end))
        agg = cur.fetchone()

    return jsonify({
        "ok": True,
        "scan_id": row["id"],
        "scanned_at": row["scanned_at"].isoformat(),
        "today_pieces": int(agg["pcs"] or 0),
        "today_earn": float(agg["earn"] or 0.0)
    })

# -----------------------------------------------------------------------------
# Health
# -----------------------------------------------------------------------------
@app.get("/healthz")
def healthz():
    return "ok", 200

# -----------------------------------------------------------------------------
# Run (local)
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=True)
