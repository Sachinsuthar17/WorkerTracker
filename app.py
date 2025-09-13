import os
import csv
import random
import threading
from datetime import datetime, timezone

from flask import (
    Flask, render_template, request, jsonify, send_from_directory, Response
)

import psycopg2
import psycopg2.extras

# -------------------------
# Config
# -------------------------
DATABASE_URL = os.getenv("DATABASE_URL")  # e.g. Render Postgres connection URL
DEVICE_SECRET = os.getenv("DEVICE_SECRET", "my-esp32-secret")
RATE_PER_PIECE = float(os.getenv("RATE_PER_PIECE", "5.0"))

app = Flask(__name__, static_folder="static", template_folder="templates")

# -------------------------
# DB helpers
# -------------------------
def get_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL env var is not set.")
    return psycopg2.connect(DATABASE_URL, sslmode="require")


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    # workers
    cur.execute("""
        CREATE TABLE IF NOT EXISTS workers (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            token_id TEXT UNIQUE NOT NULL,
            department TEXT NOT NULL,
            line TEXT NOT NULL,
            is_logged_in BOOLEAN DEFAULT FALSE,
            last_login TIMESTAMP,
            last_logout TIMESTAMP
        )
    """)

    # operations
    cur.execute("""
        CREATE TABLE IF NOT EXISTS operations (
            id SERIAL PRIMARY KEY,
            seq_no INTEGER,
            op_no INTEGER,
            description TEXT,
            machine TEXT,
            department TEXT,
            std_min NUMERIC,
            rate NUMERIC
        )
    """)

    # bundles
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bundles (
            id SERIAL PRIMARY KEY,
            bundle_code TEXT UNIQUE,
            qty INTEGER,
            status TEXT
        )
    """)

    # scan logs
    cur.execute("""
        CREATE TABLE IF NOT EXISTS scan_logs (
            id SERIAL PRIMARY KEY,
            token_id TEXT NOT NULL,
            scan_type TEXT NOT NULL,       -- work | login | logout
            scanned_at TIMESTAMP DEFAULT NOW()
        )
    """)

    # activities (for recent activity feed)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS activities (
            id SERIAL PRIMARY KEY,
            actor TEXT,
            department TEXT,
            action TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.commit()

    # seed workers if empty
    cur.execute("SELECT COUNT(*) FROM workers")
    if cur.fetchone()[0] == 0:
        departments = ["SLEEVE","COLLAR","LINING","BODY","ASSE-1","ASSE-2","FLAP","BACK","POST ASSEMBLY"]
        rows = []
        for i in range(28):
            rows.append((
                f"Worker {i+1}",
                str(1000 + i),
                departments[i % len(departments)],
                f"Line-{(i % 4) + 1}"
            ))
        psycopg2.extras.execute_batch(
            cur,
            "INSERT INTO workers (name, token_id, department, line) VALUES (%s,%s,%s,%s)",
            rows
        )

    # seed operations if empty
    cur.execute("SELECT COUNT(*) FROM operations")
    if cur.fetchone()[0] == 0:
        machines = ["SNLS","OL","FOA","BH","BARTACK"]
        departments = ["SLEEVE","COLLAR","LINING","BODY","ASSE-1","ASSE-2","FLAP","BACK","POST ASSEMBLY"]
        rows = []
        for i in range(40):
            rows.append((
                i + 1,
                200 + i,
                f"Operation step {i+1} — sample description for visual",
                machines[i % len(machines)],
                departments[i % len(departments)],
                round(random.random() * 2 + 0.3, 2),
                round(random.random() * 2 + 0.6, 2),
            ))
        psycopg2.extras.execute_batch(
            cur,
            """INSERT INTO operations (seq_no, op_no, description, machine, department, std_min, rate)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            rows
        )

    # seed bundles if empty
    cur.execute("SELECT COUNT(*) FROM bundles")
    if cur.fetchone()[0] == 0:
        seed = [
            ("A12", 28, "Pending"), ("B04", 22, "Pending"), ("C09", 20, "Pending"),
            ("A01", 30, "In Progress"), ("B11", 26, "In Progress"), ("C02", 18, "In Progress"),
            ("D07", 33, "In Progress"), ("A05", 16, "QA"), ("C03", 14, "QA"),
            ("A08", 25, "Completed"), ("B06", 27, "Completed"), ("C12", 21, "Completed"),
            ("D01", 24, "Completed"), ("E03", 19, "Completed"),
        ]
        psycopg2.extras.execute_batch(
            cur,
            "INSERT INTO bundles (bundle_code, qty, status) VALUES (%s,%s,%s)",
            seed
        )

    conn.commit()
    conn.close()


# -------------------------
# Safe one-time init (works on Flask 3.x)
# -------------------------
_initialized = False
_init_lock = threading.Lock()

@app.before_request
def _ensure_initialized():
    global _initialized
    if not _initialized:
        with _init_lock:
            if not _initialized:
                try:
                    init_db()
                    _initialized = True
                except Exception as e:
                    # Don't crash the worker; log and continue so health checks still pass
                    app.logger.exception("Database initialization failed: %s", e)


# -------------------------
# Health
# -------------------------
@app.route("/health")
def health():
    return "ok", 200


# -------------------------
# Routes (UI)
# -------------------------
@app.route("/")
def index():
    # Expect templates/index.html from your SPA (Option B)
    return render_template("index.html")


@app.route("/favicon.ico")
def favicon():
    return send_from_directory(os.path.join(app.root_path, "static"), "favicon.ico", mimetype="image/vnd.microsoft.icon")


# -------------------------
# API: Dashboard & Data
# -------------------------
@app.route("/api/stats")
def api_stats():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM workers WHERE is_logged_in=TRUE")
    active_workers = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM operations")
    total_operations = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM bundles")
    total_bundles = cur.fetchone()[0]

    # naive earnings: count today's 'work' scans * RATE_PER_PIECE
    cur.execute("""
        SELECT COUNT(*) FROM scan_logs
        WHERE scan_type='work' AND DATE(scanned_at) = CURRENT_DATE
    """)
    scans_today = cur.fetchone()[0]
    earnings = scans_today * RATE_PER_PIECE

    conn.close()
    return jsonify({
        "active_workers": active_workers,
        "total_operations": total_operations,
        "total_bundles": total_bundles,
        "earnings": earnings
    })


@app.route("/api/activities")
def api_activities():
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("""
        SELECT actor, department, action, created_at
        FROM activities
        ORDER BY created_at DESC
        LIMIT 50
    """)
    rows = cur.fetchall()
    conn.close()

    def fmt_time(ts):
        if not ts:
            return "now"
        dt = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        mins = int(delta.total_seconds() // 60)
        return f"{mins} min ago" if mins < 60 else f"{mins//60} hr ago"

    data = [{
        "actor": r["actor"],
        "department": r["department"],
        "action": r["action"],
        "time": fmt_time(r["created_at"])
    } for r in rows]

    return jsonify(data)


@app.route("/api/chart-data")
def api_chart_data():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT DATE_TRUNC('month', scanned_at) AS m, COUNT(*)
        FROM scan_logs
        WHERE scan_type='work'
        GROUP BY 1
        ORDER BY 1
    """)
    rows = cur.fetchall()
    conn.close()

    labels_all = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    values_map = {(r[0].month if r[0] else 1): r[1] for r in rows}
    values = [int(values_map.get(i, random.randint(250, 950))) for i in range(1, 13)]

    return jsonify({"labels": labels_all, "values": values})


@app.route("/api/workers")
def api_workers():
    q = (request.args.get("q") or "").strip().lower()
    dept = (request.args.get("department") or "").strip()

    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT name, token_id, department, line, is_logged_in FROM workers")
    rows = cur.fetchall()
    conn.close()

    def match(r):
        blob = f"{r['name']} {r['token_id']} {r['department']} {r['line']}".lower()
        if dept and r["department"] != dept:
            return False
        if q and q not in blob:
            return False
        return True

    data = [{
        "name": r["name"],
        "token_id": r["token_id"],
        "department": r["department"],
        "line": r["line"],
        "status": "Active" if r["is_logged_in"] else "Idle"
    } for r in rows if match(r)]

    return jsonify(data)


@app.route("/api/operations")
def api_operations():
    flt = (request.args.get("department") or "").strip()
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    if flt:
        cur.execute("SELECT * FROM operations WHERE department=%s ORDER BY seq_no", (flt,))
    else:
        cur.execute("SELECT * FROM operations ORDER BY seq_no")
    rows = cur.fetchall()
    conn.close()

    data = [{
        "seq": r["seq_no"],
        "opNo": r["op_no"],
        "description": r["description"],
        "machine": r["machine"],
        "department": r["department"],
        "stdMin": float(r["std_min"]),
        "rate": float(r["rate"])
    } for r in rows]
    return jsonify(data)


@app.route("/api/bundles")
def api_bundles():
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT bundle_code, qty, status FROM bundles ORDER BY bundle_code")
    rows = cur.fetchall()
    conn.close()
    data = [{"id": r["bundle_code"], "qty": r["qty"], "status": r["status"]} for r in rows]
    return jsonify(data)


@app.route("/api/bundles/assign", methods=["POST"])
def api_assign_bundle():
    data = request.get_json(silent=True) or {}
    bundle_id = data.get("bundle_id")
    worker_token = data.get("worker_token")
    op_no = data.get("op_no")

    if not bundle_id or not worker_token or not op_no:
        return jsonify({"status": "error", "message": "Missing fields"}), 400

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE bundles SET status='In Progress' WHERE bundle_code=%s", (bundle_id,))
    cur.execute("""
        INSERT INTO activities (actor, department, action)
        VALUES (%s, %s, %s)
    """, (f"Token {worker_token}", "—", f"Assigned bundle #{bundle_id} to op {op_no}"))
    conn.commit()
    conn.close()

    return jsonify({"status": "success"})


@app.route("/api/bundles/move", methods=["POST"])
def api_move_bundle():
    data = request.get_json(silent=True) or {}
    bundle_id = data.get("bundle_id")
    next_status = data.get("next_status")
    if not bundle_id or not next_status:
        return jsonify({"status": "error", "message": "Missing fields"}), 400

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE bundles SET status=%s WHERE bundle_code=%s", (next_status, bundle_id))
    cur.execute("""
        INSERT INTO activities (actor, department, action)
        VALUES (%s, %s, %s)
    """, ("System", "—", f"Bundle #{bundle_id} moved to {next_status}"))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})


@app.route("/api/upload/ob", methods=["POST"])
def api_upload_ob():
    # stub endpoint; integrate real Excel parsing later
    return jsonify({"status": "success", "message": "OB file received"})


@app.route("/api/upload/po", methods=["POST"])
def api_upload_po():
    # stub endpoint; integrate real PDF parsing later
    return jsonify({"status": "success", "message": "PO file received"})


@app.route("/api/reports/earnings.csv")
def api_report_earnings():
    # Department earnings CSV (fake data for demo)
    departments = ["SLEEVE","COLLAR","LINING","BODY","ASSE-1","ASSE-2","FLAP","BACK"]
    def generate():
        yield "Department,Earnings\n"
        for d in departments:
            yield f"{d},{random.randint(20000, 50000)}\n"
    headers = {"Content-Disposition": "attachment; filename=earnings.csv"}
    return Response(generate(), mimetype="text/csv", headers=headers)


# -------------------------
# ESP32 Scan Endpoint
# -------------------------
@app.route("/scan", methods=["POST"])
def scan():
    data = request.get_json(silent=True) or {}
    token_id = data.get("token_id")
    secret = data.get("secret")
    scan_type = data.get("scan_type", "work")

    # 1) validate input
    if not token_id or not secret:
        return jsonify({"status": "error", "message": "Missing token_id or secret"}), 400

    # 2) auth
    if secret != DEVICE_SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 403

    # 3) look up worker
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT * FROM workers WHERE token_id=%s", (token_id,))
    worker = cur.fetchone()
    if not worker:
        conn.close()
        return jsonify({"status": "error", "message": "Invalid token_id"}), 404

    # 4) log the scan
    cur.execute(
        "INSERT INTO scan_logs (token_id, scan_type) VALUES (%s, %s)",
        (token_id, scan_type),
    )

    # 5) update login state if needed
    is_logged_in = worker["is_logged_in"]
    if scan_type == "login":
        cur.execute(
            "UPDATE workers SET is_logged_in=TRUE, last_login=NOW() WHERE token_id=%s",
            (token_id,),
        )
        is_logged_in = True
        message = "Login successful"
    elif scan_type == "logout":
        cur.execute(
            "UPDATE workers SET is_logged_in=FALSE, last_logout=NOW() WHERE token_id=%s",
            (token_id,),
        )
        is_logged_in = False
        message = "Logout successful"
    else:
        message = "Work scan logged"

    # 6) count today's scans for earnings
    cur.execute("""
        SELECT COUNT(*) FROM scan_logs
        WHERE token_id=%s AND scan_type='work' AND DATE(scanned_at)=CURRENT_DATE
    """, (token_id,))
    scans_today = cur.fetchone()[0]

    # also add an activity row for the feed
    cur.execute("""
        INSERT INTO activities (actor, department, action)
        VALUES (%s, %s, %s)
    """, (worker["name"], worker["department"], f"{scan_type.title()} scan"))

    conn.commit()
    conn.close()

    return jsonify({
        "status": "success",
        "message": message,
        "name": worker["name"],
        "department": worker["department"],
        "is_logged_in": is_logged_in,
        "scans_today": scans_today,
        "earnings": scans_today * RATE_PER_PIECE,
    })


# -------------------------
# Entrypoint
# -------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
