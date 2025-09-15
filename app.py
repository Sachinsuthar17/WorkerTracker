# app.py
import os, json, logging
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory, abort
import psycopg2
import psycopg2.extras

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("app")

ROOT = Path(__file__).resolve().parent

# --------------------------------------------------------------------
# Flask
# --------------------------------------------------------------------
app = Flask(__name__)

# --------------------------------------------------------------------
# Database helpers
# --------------------------------------------------------------------
def _conn():
    url = os.getenv("DATABASE_URL")
    if not url:
        return None
    # Render Postgres usually needs ssl
    if "sslmode" not in url:
        url = url + ("?sslmode=require" if "?" not in url else "&sslmode=require")
    return psycopg2.connect(url)

def _exec(sql, params=None, many=False, returning=False):
    conn = _conn()
    if not conn:
        return None
    with conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if many:
                psycopg2.extras.execute_batch(cur, sql, params or [])
            else:
                cur.execute(sql, params or ())
            rows = cur.fetchall() if returning else None
            return rows

def _scalar(sql, params=None, default=0):
    rows = _exec(sql, params, returning=True)
    if not rows:
        return default
    first = list(rows[0].values())[0]
    return first if first is not None else default

def ensure_db():
    """
    Create tables if missing and repair expected columns so seeding/inserts won’t crash.
    """
    conn = _conn()
    if not conn:
        log.warning("DATABASE_URL not set — running in mock (no-DB) mode.")
        return

    with conn:
        with conn.cursor() as cur:
            # workers
            cur.execute("""
                CREATE TABLE IF NOT EXISTS workers (
                    id SERIAL PRIMARY KEY,
                    token_id TEXT UNIQUE,
                    name TEXT,
                    department TEXT,
                    line TEXT,
                    status TEXT DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            # bundles
            cur.execute("""
                CREATE TABLE IF NOT EXISTS bundles (
                    id SERIAL PRIMARY KEY,
                    bundle_code TEXT,
                    qty INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            # make sure bundle_code exists for old tables
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name='bundles'
            """)
            cols = {r[0] for r in cur.fetchall()}
            if "bundle_code" not in cols:
                cur.execute("ALTER TABLE bundles ADD COLUMN bundle_code TEXT")
                log.info("Added missing column bundles.bundle_code")

            # scans
            cur.execute("""
                CREATE TABLE IF NOT EXISTS scans (
                    id SERIAL PRIMARY KEY,
                    token_id TEXT,
                    scan_type TEXT,
                    meta JSONB DEFAULT '{}'::jsonb,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)

            # seed a few rows if empty
            cur.execute("SELECT COUNT(*) FROM bundles")
            (count_bundles,) = cur.fetchone()
            if count_bundles == 0:
                seed = [
                    ("A12", 120, "pending"),
                    ("B03",  60, "in_progress"),
                    ("C77", 200, "done"),
                    ("D18",  80, "pending"),
                ]
                psycopg2.extras.execute_batch(
                    cur,
                    "INSERT INTO bundles (bundle_code, qty, status) VALUES (%s,%s,%s)",
                    seed
                )
                log.info("Seeded bundles")

            cur.execute("SELECT COUNT(*) FROM workers")
            (count_workers,) = cur.fetchone()
            if count_workers == 0:
                workers = [
                    ("1001", "Ada Lovelace", "Assembly", "L1", "active"),
                    ("1002", "Ken Thompson", "Finishing", "L2", "active"),
                    ("1003", "Grace Hopper", "QA", "L3", "inactive"),
                ]
                psycopg2.extras.execute_batch(
                    cur,
                    "INSERT INTO workers (token_id, name, department, line, status) VALUES (%s,%s,%s,%s,%s)",
                    workers
                )
                log.info("Seeded workers")

    log.info("DB ready")

# Run initialization at import (Flask 3.x removed before_first_request)
try:
    ensure_db()
except Exception as e:
    log.exception("Database initialization failed: %s", e)

# --------------------------------------------------------------------
# Static: serve your UI files from repo root
# --------------------------------------------------------------------
@app.route("/")
def index():
    return send_from_directory(ROOT, "index.html")

@app.route("/style.css")
def css():
    return send_from_directory(ROOT, "style.css")

@app.route("/app.js")
def js():
    return send_from_directory(ROOT, "app.js")

# optional: route top-level slugs back to SPA
@app.route("/<path:slug>")
def spa(slug):
    # If it’s a known asset, serve it; otherwise serve SPA
    allowed = {"index.html", "style.css", "app.js", "favicon.ico"}
    if slug in allowed and (ROOT / slug).exists():
        return send_from_directory(ROOT, slug)
    return send_from_directory(ROOT, "index.html")

# --------------------------------------------------------------------
# API
# --------------------------------------------------------------------
@app.get("/api/stats")
def api_stats():
    if not _conn():
        # mock
        return jsonify({
            "active_workers": 12,
            "total_operations": 1342,
            "bundles": 23,
            "earnings_today": 482.5,
            "last_update": datetime.utcnow().isoformat() + "Z",
        })

    active_workers = _scalar("SELECT COUNT(*) FROM workers WHERE status='active'")
    total_ops = _scalar("SELECT COUNT(*) FROM scans")
    bundles = _scalar("SELECT COUNT(*) FROM bundles")
    # simple demo earning: 2.5 per scan today
    earnings_today = _scalar(
        "SELECT COUNT(*) FROM scans WHERE created_at::date = CURRENT_DATE"
    ) * 2.5

    return jsonify({
        "active_workers": active_workers,
        "total_operations": total_ops,
        "bundles": bundles,
        "earnings_today": float(earnings_today),
        "last_update": datetime.utcnow().isoformat() + "Z",
    })

@app.get("/api/activities")
def api_activities():
    if not _conn():
        items = []
        now = datetime.utcnow()
        for i in range(15):
            items.append({
                "time": (now - timedelta(minutes=i*7)).isoformat() + "Z",
                "text": f"Token {1000+i} scanned bundle",
            })
        return jsonify(items)

    rows = _exec(
        "SELECT token_id, scan_type, created_at FROM scans ORDER BY created_at DESC LIMIT 50",
        returning=True,
    ) or []
    out = []
    for r in rows:
        out.append({
            "time": r["created_at"].isoformat() if r["created_at"] else None,
            "text": f"Token {r['token_id']} - {r['scan_type']}",
        })
    return jsonify(out)

@app.get("/api/chart-data")
def api_chart_data():
    # 12 months demo data
    labels = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    data1 = [12,18,15,22,19,25,28,31,26,24,20,18]
    data2 = [9,11,10,14,12,16,18,20,17,15,12,10]
    return jsonify({"labels": labels, "series1": data1, "series2": data2})

@app.post("/api/scan")
def api_scan():
    payload = request.get_json(silent=True) or {}
    token_id = str(payload.get("token_id", "")).strip()
    scan_type = str(payload.get("type", "")).strip() or "work"
    if not token_id:
        return jsonify({"status": "error", "message": "Missing token_id"}), 400

    if _conn():
        _exec(
            "INSERT INTO scans (token_id, scan_type, meta) VALUES (%s,%s,%s)",
            (token_id, scan_type, json.dumps(payload)),
        )
    return jsonify({"status": "ok", "message": f"Scan recorded for {token_id}", "type": scan_type})

# Simple upload stubs your UI can hit; they don’t store files (demo only)
@app.post("/api/upload/ob-excel")
def upload_ob_excel():
    if "file" not in request.files:
        return jsonify({"status": "error", "message": "No file"}), 400
    return jsonify({"status": "ok", "message": "OB file received"})

@app.post("/api/upload/po-pdf")
def upload_po_pdf():
    if "file" not in request.files:
        return jsonify({"status": "error", "message": "No file"}), 400
    return jsonify({"status": "ok", "message": "Production order PDF received"})

# Health
@app.get("/healthz")
def health():
    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
