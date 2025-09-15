# app.py
import os, json, logging
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory, Response
import psycopg2
import psycopg2.extras

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("app")

ROOT = Path(__file__).resolve().parent

app = Flask(__name__)

# ----------------------------- DB helpers -----------------------------
def _conn():
    url = os.getenv("DATABASE_URL")
    if not url:
        return None
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
                return None
            cur.execute(sql, params or ())
            if returning:
                return cur.fetchall()
            return None

def _scalar(sql, params=None, default=0):
    rows = _exec(sql, params, returning=True)
    if not rows:
        return default
    v = list(rows[0].values())[0]
    return v if v is not None else default

def _columns_for(table):
    """Return {col: {'nullable': bool, 'data_type': str}}"""
    conn = _conn()
    if not conn:
        return {}
    with conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT column_name, is_nullable, data_type
                FROM information_schema.columns
                WHERE table_name=%s
            """, (table,))
            out = {}
            for name, is_null, dt in cur.fetchall():
                out[name] = {"nullable": (is_null.lower() == "yes"), "data_type": dt}
            return out

# -------------------------- DB bootstrap logic ------------------------
def ensure_db():
    conn = _conn()
    if not conn:
        log.warning("DATABASE_URL not set — running in mock (no-DB) mode.")
        return

    with conn:
        with conn.cursor() as cur:
            # Minimal tables (won't drop anything you already have)
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
            cur.execute("""
                CREATE TABLE IF NOT EXISTS bundles (
                    id SERIAL PRIMARY KEY,
                    bundle_code TEXT,
                    qty INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS scans (
                    id SERIAL PRIMARY KEY,
                    token_id TEXT,
                    scan_type TEXT,
                    meta JSONB DEFAULT '{}'::jsonb,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)

    # If your existing table already has stricter columns, we adapt inserts to them:
    bcols = _columns_for("bundles")

    # Skip seeding when requested
    if os.getenv("SKIP_SEED", "0") == "1":
        log.info("SKIP_SEED=1 -> not inserting demo rows")
        return

    # Only seed when the table is really empty
    try:
        count_bundles = _scalar("SELECT COUNT(*) FROM bundles", default=0)
    except Exception:
        count_bundles = 0

    if count_bundles > 0:
        log.info("Bundles already present (%s) — seeding skipped", count_bundles)
        return

    seed_src = [
        ("A12", 120, "pending"),
        ("B03",  60, "in_progress"),
        ("C77", 200, "done"),
        ("D18",  80, "pending"),
    ]

    # Build dynamic column list for insert
    base_cols = ["bundle_code", "qty", "status"]
    # If your table also requires barcode_value / barcode_type (NOT NULL), populate sensible defaults.
    if "barcode_value" in bcols and not bcols["barcode_value"]["nullable"]:
        base_cols.append("barcode_value")
    if "barcode_type" in bcols and not bcols["barcode_type"]["nullable"]:
        base_cols.append("barcode_type")

    # Prepare rows that match the dynamic columns
    rows = []
    for code, qty, status in seed_src:
        r = [code, qty, status]
        if "barcode_value" in base_cols:
            r.append(code)                 # use bundle_code as barcode_value
        if "barcode_type" in base_cols:
            r.append("code128")            # default barcode type
        rows.append(tuple(r))

    placeholders = ",".join(["%s"] * len(base_cols))
    sql = f"INSERT INTO bundles ({', '.join(base_cols)}) VALUES ({placeholders})"

    try:
        _exec(sql, rows, many=True)
        log.info("Seeded bundles with dynamic columns: %s", base_cols)
    except Exception as e:
        # If the live table has *other* extra NOT NULL columns we don't know about, just skip seeding.
        log.exception("Seeding bundles failed; skipping. Reason: %s", e)

    # Seed workers if empty (safe)
    if _scalar("SELECT COUNT(*) FROM workers", default=0) == 0:
        workers = [
            ("1001", "Ada Lovelace", "Assembly", "L1", "active"),
            ("1002", "Ken Thompson", "Finishing", "L2", "active"),
            ("1003", "Grace Hopper", "QA", "L3", "inactive"),
        ]
        _exec(
            "INSERT INTO workers (token_id, name, department, line, status) VALUES (%s,%s,%s,%s,%s)",
            workers, many=True
        )
        log.info("Seeded workers")

try:
    ensure_db()
except Exception as e:
    log.exception("Database initialization failed: %s", e)

# --------------------------- Static / UI routes -----------------------
@app.route("/")
def index():
    # Serve your SPA if present; otherwise show a helpful placeholder so / never 404s.
    path = ROOT / "index.html"
    if path.exists():
        return send_from_directory(ROOT, "index.html")
    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Factory Ops Dashboard</title>
<style>body{{font-family:system-ui,Segoe UI,Arial;margin:40px;color:#111}}
code{{background:#f2f2f2;padding:.2rem .4rem;border-radius:4px}}</style></head>
<body>
  <h2>Factory Ops Dashboard</h2>
  <p><strong>index.html</strong> not found in the deployment bundle.</p>
  <p>Add <code>index.html</code>, <code>style.css</code>, and <code>app.js</code> to the same directory as <code>app.py</code> and redeploy.</p>
  <ul>
    <li>Check API: <a href="/api/stats">/api/stats</a></li>
    <li>Health: <a href="/healthz">/healthz</a></li>
  </ul>
</body></html>"""
    return Response(html, mimetype="text/html")

@app.route("/style.css")
def css():
    return send_from_directory(ROOT, "style.css")

@app.route("/app.js")
def js():
    return send_from_directory(ROOT, "app.js")

# Optional SPA catch-all (keeps deep links working if your index is present)
@app.route("/<path:slug>")
def spa(slug):
    allowed = {"index.html", "style.css", "app.js", "favicon.ico"}
    f = ROOT / slug
    if slug in allowed and f.exists():
        return send_from_directory(ROOT, slug)
    if (ROOT / "index.html").exists():
        return send_from_directory(ROOT, "index.html")
    return ("Not Found", 404)

# ------------------------------ API ----------------------------------
@app.get("/api/stats")
def api_stats():
    if not _conn():
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
        now = datetime.utcnow()
        return jsonify([
            {"time": (now - timedelta(minutes=i*7)).isoformat() + "Z",
             "text": f"Token {1000+i} scanned bundle"}
            for i in range(15)
        ])
    rows = _exec(
        "SELECT token_id, scan_type, created_at FROM scans ORDER BY created_at DESC LIMIT 50",
        returning=True,
    ) or []
    return jsonify([
        {"time": r["created_at"].isoformat() if r["created_at"] else None,
         "text": f"Token {r['token_id']} - {r['scan_type']}"}
        for r in rows
    ])

@app.get("/api/chart-data")
def api_chart_data():
    labels = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    s1 = [12,18,15,22,19,25,28,31,26,24,20,18]
    s2 = [ 9,11,10,14,12,16,18,20,17,15,12,10]
    return jsonify({"labels": labels, "series1": s1, "series2": s2})

@app.post("/api/scan")
def api_scan():
    data = request.get_json(silent=True) or {}
    token_id = str(data.get("token_id", "")).strip()
    scan_type = str(data.get("type", "work")).strip()
    if not token_id:
        return jsonify({"status": "error", "message": "Missing token_id"}), 400
    if _conn():
        _exec(
            "INSERT INTO scans (token_id, scan_type, meta) VALUES (%s,%s,%s)",
            (token_id, scan_type, json.dumps(data))
        )
    return jsonify({"status": "ok", "message": f"Scan recorded for {token_id}", "type": scan_type})

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

@app.get("/healthz")
def health():
    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
