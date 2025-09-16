import os
import io
import csv
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

from flask import Flask, render_template, request, jsonify, Response, send_from_directory
from flask_cors import CORS
from jinja2 import TemplateNotFound

import psycopg2
import psycopg2.extras


# -----------------------------------------------------------------------------
# App / Config
# -----------------------------------------------------------------------------
app = Flask(__name__)
CORS(app)

RAW_DB_URL = os.getenv("DATABASE_URL", "").strip().strip('"').strip("'")
if not RAW_DB_URL:
    raise RuntimeError("DATABASE_URL is not set. Add it in Render → Environment.")

DEVICE_SECRET = os.getenv("DEVICE_SECRET", "changeme-device-secret")
RATE_PER_PIECE = float(os.getenv("RATE_PER_PIECE", "5.0"))  # used to compute earnings


def _normalize_postgres_url(url: str) -> str:
    """
    Make the DATABASE_URL safe for psycopg2:
    - Force scheme 'postgresql'
    - Ensure ?sslmode=require is present (Render PG usually needs it)
    """
    p = urlparse(url)
    scheme = (p.scheme or "postgresql").split("+", 1)[0]
    if scheme == "postgres":
        scheme = "postgresql"

    q = dict(parse_qsl(p.query, keep_blank_values=True))
    if not q.get("sslmode"):
        q["sslmode"] = "require"

    return urlunparse((
        scheme,
        p.netloc,
        p.path,
        p.params,
        urlencode(q, doseq=True),
        p.fragment,
    ))


DB_URL = _normalize_postgres_url(RAW_DB_URL)


def get_conn():
    # Default rows are tuples; use DictCursor when you want dicts.
    return psycopg2.connect(DB_URL)


# -----------------------------------------------------------------------------
# DB bootstrap
# -----------------------------------------------------------------------------
def init_db():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS workers (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                department TEXT,
                token_id TEXT UNIQUE,
                status TEXT DEFAULT 'active',
                is_logged_in BOOLEAN DEFAULT FALSE,
                last_login TIMESTAMPTZ,
                last_logout TIMESTAMPTZ,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS operations (
                id SERIAL PRIMARY KEY,
                op_no INTEGER UNIQUE,
                description TEXT,
                machine TEXT,
                department TEXT,
                std_min NUMERIC,
                piece_rate NUMERIC,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS bundles (
                id SERIAL PRIMARY KEY,
                code TEXT UNIQUE,
                qty INTEGER DEFAULT 0,
                status TEXT DEFAULT 'Pending'
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS scan_logs (
                id SERIAL PRIMARY KEY,
                token_id TEXT NOT NULL,
                scan_type TEXT DEFAULT 'work',
                scanned_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def seed_if_empty():
    with get_conn() as conn, conn.cursor() as cur:
        # operations
        cur.execute("SELECT COUNT(*) FROM operations")
        if cur.fetchone()[0] == 0:
            depts = ["SLEEVE", "COLLAR", "LINING", "BODY", "ASSE-1", "ASSE-2", "FLAP", "BACK", "POST ASSEMBLY"]
            machines = ["SNLS", "OL", "FOA", "BH", "BARTACK"]
            rows = []
            for i in range(1, 41):
                rows.append((
                    200 + i,
                    f"Operation step {i} - sample",
                    machines[i % len(machines)],
                    depts[i % len(depts)],
                    round(0.3 + (i % 7) * 0.2, 2),
                    round(0.6 + (i % 6) * 0.25, 2),
                ))
            cur.executemany(
                """
                INSERT INTO operations (op_no, description, machine, department, std_min, piece_rate)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (op_no) DO NOTHING
                """,
                rows,
            )

        # bundles
        cur.execute("SELECT COUNT(*) FROM bundles")
        if cur.fetchone()[0] == 0:
            seed = [
                ("A12", 28, "Pending"), ("B04", 22, "Pending"), ("C09", 20, "Pending"),
                ("A01", 30, "In Progress"), ("B11", 26, "In Progress"),
                ("C02", 18, "In Progress"), ("D07", 33, "In Progress"),
                ("A05", 16, "QA"), ("C03", 14, "QA"),
                ("A08", 25, "Completed"), ("B06", 27, "Completed"),
                ("C12", 21, "Completed"), ("D01", 24, "Completed"), ("E03", 19, "Completed"),
            ]
            cur.executemany(
                """
                INSERT INTO bundles (code, qty, status) VALUES (%s,%s,%s)
                ON CONFLICT (code) DO NOTHING
                """,
                seed,
            )


# Initialize DB on boot; if PG isn’t ready yet, don’t crash the app.
try:
    init_db()
    seed_if_empty()
except Exception as e:
    print("DB init/seed error:", e)


# -----------------------------------------------------------------------------
# Pages
# -----------------------------------------------------------------------------
@app.route("/")
def home():
    try:
        return render_template("index.html")
    except TemplateNotFound:
        return "OK", 200


# -----------------------------------------------------------------------------
# APIs for UI
# -----------------------------------------------------------------------------
def _count(table: str) -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        return int(cur.fetchone()[0])


@app.route("/api/stats")
def api_stats():
    scans_today = 0
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM scan_logs WHERE scan_type='work' AND DATE(scanned_at)=CURRENT_DATE")
        scans_today = int(cur.fetchone()[0])

    return jsonify({
        "activeWorkers": _count("workers"),
        "totalBundles": _count("bundles"),
        "totalOperations": _count("operations"),
        "totalEarnings": round(scans_today * RATE_PER_PIECE, 2),
    })


@app.route("/api/chart-data")
def api_chart_data():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT status, COUNT(*) FROM bundles GROUP BY status")
        status_map = {k: int(v) for k, v in cur.fetchall()}

        cur.execute("SELECT department, COUNT(*) FROM operations GROUP BY department ORDER BY department")
        dept_rows = cur.fetchall()

    bundle_status = [
        status_map.get("Pending", 0),
        status_map.get("In Progress", 0),
        status_map.get("QA", 0),
        status_map.get("Completed", 0),
    ]
    departments = [r[0] for r in dept_rows]
    workloads = [int(r[1]) * 10 for r in dept_rows]

    return jsonify({
        "bundleStatus": bundle_status,
        "departments": departments,
        "deptLoads": workloads,
    })


@app.route("/api/activities")
def api_activities():
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(
            """
            SELECT s.id, s.token_id, s.scan_type, s.scanned_at, w.name AS worker_name
            FROM scan_logs s
            LEFT JOIN workers w ON w.token_id = s.token_id
            ORDER BY s.scanned_at DESC
            LIMIT 12
            """
        )
        rows = cur.fetchall()

    items = [{
        "id": r["id"],
        "text": f"{r['scan_type'].title()} scan for token {r['token_id']}",
        "time": r["scanned_at"].isoformat() if r["scanned_at"] else "",
    } for r in rows]
    return jsonify(items)


@app.route("/api/workers")
def api_workers():
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("""
            SELECT id, name, department, token_id, status, is_logged_in, last_login, last_logout
            FROM workers
            ORDER BY id DESC
        """)
        rows = [dict(r) for r in cur.fetchall()]
    return jsonify(rows)


@app.route("/api/operations")
def api_operations():
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("""
            SELECT id, op_no, description, machine, department, std_min, piece_rate
            FROM operations
            ORDER BY op_no ASC
        """)
        rows = [dict(r) for r in cur.fetchall()]
    return jsonify(rows)


@app.route("/api/bundles")
def api_bundles():
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT id, code, qty, status FROM bundles ORDER BY code")
        rows = [dict(r) for r in cur.fetchall()]
    return jsonify(rows)


@app.route("/api/bundles/assign", methods=["POST"])
def api_assign_bundle():
    data = request.get_json(silent=True) or {}
    code = data.get("code")
    worker_token = data.get("workerToken")
    op_no = data.get("opNo")

    if not code or not worker_token or not op_no:
        return jsonify({"error": "Missing fields"}), 400

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE bundles SET status='In Progress' WHERE code=%s", (code,))
        cur.execute("INSERT INTO scan_logs (token_id, scan_type) VALUES (%s, %s)", (worker_token, "work"))

    return jsonify({"ok": True})


@app.route("/api/bundles/move", methods=["POST"])
def api_move_bundle():
    data = request.get_json(silent=True) or {}
    code = data.get("code")
    to_status = data.get("to")
    if to_status not in ("Pending", "In Progress", "QA", "Completed"):
        return jsonify({"error": "Invalid status"}), 400

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE bundles SET status=%s WHERE code=%s", (to_status, code))

    return jsonify({"ok": True})


@app.route("/api/upload/ob", methods=["POST"])
def api_upload_ob():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "file is required"}), 400
    # TODO: parse Excel and upsert operations
    return jsonify({"ok": True})


@app.route("/api/upload/po", methods=["POST"])
def api_upload_po():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "file is required"}), 400
    # TODO: store PDF if you need to
    return jsonify({"ok": True})


@app.route("/api/reports/earnings.csv")
def api_earnings_csv():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT COALESCE(department,'UNKNOWN'), COUNT(*) FROM workers GROUP BY department ORDER BY 1")
        rows = cur.fetchall()

    si = io.StringIO()
    writer = csv.writer(si)
    writer.writerow(["Department", "Earnings"])
    for dept, count in rows:
        writer.writerow([dept, int(count) * 20000])  # dummy calc
    si.seek(0)
    return Response(
        si.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=earnings_report.csv"},
    )


# -----------------------------------------------------------------------------
# QR Codes (SVG) for tokens
# -----------------------------------------------------------------------------
@app.route("/qr/<token_id>")
def qr_code(token_id):
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256">
<rect width="100%" height="100%" fill="white"/>
<text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" font-size="16">{token_id}</text>
</svg>"""
    return Response(svg, mimetype="image/svg+xml")


# -----------------------------------------------------------------------------
# ESP32 Scan Endpoint
# -----------------------------------------------------------------------------
@app.route("/scan", methods=["POST"])
def scan():
    data = request.get_json(silent=True) or {}
    token_id = data.get("token_id")
    secret = data.get("secret")
    scan_type = data.get("scan_type", "work")

    if not token_id or not secret:
        return jsonify({"status": "error", "message": "Missing token_id or secret"}), 400
    if secret != DEVICE_SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 403

    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT * FROM workers WHERE token_id=%s", (token_id,))
        worker = cur.fetchone()
        if not worker:
            return jsonify({"status": "error", "message": "Invalid token_id"}), 404

        cur.execute("INSERT INTO scan_logs (token_id, scan_type) VALUES (%s, %s)", (token_id, scan_type))

        is_logged_in = bool(worker["is_logged_in"])
        if scan_type == "login":
            cur.execute("UPDATE workers SET is_logged_in=TRUE, last_login=NOW() WHERE token_id=%s", (token_id,))
            is_logged_in = True
            message = "Login successful"
        elif scan_type == "logout":
            cur.execute("UPDATE workers SET is_logged_in=FALSE, last_logout=NOW() WHERE token_id=%s", (token_id,))
            is_logged_in = False
            message = "Logout successful"
        else:
            message = "Work scan logged"

        cur.execute(
            """
            SELECT COUNT(*) FROM scan_logs
            WHERE token_id=%s AND scan_type='work' AND DATE(scanned_at)=CURRENT_DATE
            """,
            (token_id,),
        )
        scans_today = int(cur.fetchone()[0])

    return jsonify({
        "status": "success",
        "message": message,
        "name": worker["name"],
        "department": worker["department"],
        "is_logged_in": is_logged_in,
        "scans_today": scans_today,
        "earnings": scans_today * RATE_PER_PIECE,
    })


# -----------------------------------------------------------------------------
# Misc
# -----------------------------------------------------------------------------
@app.route("/favicon.ico")
def favicon():
    return send_from_directory(os.path.join(app.root_path, "static"), "favicon.ico", mimetype="image/vnd.microsoft.icon")


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
