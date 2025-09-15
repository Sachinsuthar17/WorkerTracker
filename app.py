import os
import csv
import io
import logging
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, jsonify, send_from_directory, Response, request, abort
from flask_cors import CORS
import psycopg2
import psycopg2.extras

# -----------------------------------------------------------------------------
# Flask setup
# -----------------------------------------------------------------------------
APP_DIR = Path(__file__).resolve().parent

# Candidate locations to look for index.html + assets on Render
CANDIDATE_UI_DIRS = [
    APP_DIR,
    APP_DIR / "static",
    APP_DIR / "public",
    APP_DIR / "frontend",
    APP_DIR / "templates",
]

def find_ui_dir() -> Path | None:
    for d in CANDIDATE_UI_DIRS:
        if (d / "index.html").exists():
            return d
    return None

UI_DIR = find_ui_dir()

app = Flask(__name__)  # no static_folder; we serve dynamically
CORS(app)
logging.basicConfig(level=logging.INFO)
log = app.logger

def _log_static_presence():
    log.info("Working dir: %s", APP_DIR)
    present = []
    for f in ("index.html", "style.css", "app.js"):
        found = any((d / f).exists() for d in CANDIDATE_UI_DIRS)
        present.append(f"{f}:{'Y' if found else 'N'}")
    log.info("Static search (%s): %s",
             ", ".join([str(p) for p in CANDIDATE_UI_DIRS]),
             ", ".join(present))
    if UI_DIR:
        log.info("Using UI dir: %s", UI_DIR)
    else:
        log.warning("No UI dir found (index.html missing in all candidates).")

_log_static_presence()

# -----------------------------------------------------------------------------
# Database
# -----------------------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL")

def get_conn():
    if not DATABASE_URL:
        return None
    return psycopg2.connect(DATABASE_URL, sslmode="require")

def ensure_db():
    if not DATABASE_URL:
        log.warning("DATABASE_URL not set; API will return mock data only.")
        return

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS workers (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    token TEXT UNIQUE,
                    department TEXT,
                    line TEXT
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS bundles (
                    id SERIAL PRIMARY KEY,
                    barcode_value TEXT NOT NULL DEFAULT '',
                    barcode_type TEXT,
                    qty INTEGER,
                    scanned_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    bundle_code TEXT,
                    status TEXT
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS scans (
                    id SERIAL PRIMARY KEY,
                    token TEXT,
                    kind TEXT,
                    scanned_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS activities (
                    id SERIAL PRIMARY KEY,
                    who TEXT,
                    what TEXT,
                    when_ts TIMESTAMPTZ DEFAULT NOW()
                );
            """)

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM bundles;")
            count = cur.fetchone()[0]

        if count == 0 and os.getenv("SKIP_SEED", "0") != "1":
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name='bundles';
                """)
                cols = {r[0] for r in cur.fetchall()}

            seed = [("A12", 120, "pending"),
                    ("B04",  90, "pending"),
                    ("C33",  45, "pending"),
                    ("D18",  30, "pending")]

            with conn.cursor() as cur:
                if "barcode_value" in cols:
                    rows = []
                    for i, (code, qty, status) in enumerate(seed, start=1):
                        rows.append((
                            f"BC-{code}-{i:04d}",  # barcode_value (NOT NULL)
                            "code128",             # barcode_type
                            qty,
                            None,                  # scanned_at
                            code,
                            status
                        ))
                    psycopg2.extras.execute_batch(
                        cur,
                        """INSERT INTO bundles
                           (barcode_value, barcode_type, qty, scanned_at, bundle_code, status)
                           VALUES (%s,%s,%s,%s,%s,%s)""",
                        rows
                    )
                    log.info("Seeded bundles with dynamic columns: ['bundle_code','qty','status','barcode_value']")
                else:
                    psycopg2.extras.execute_batch(
                        cur,
                        "INSERT INTO bundles (bundle_code, qty, status) VALUES (%s,%s,%s)",
                        seed
                    )
                    log.info("Seeded bundles without barcode_value (column missing)")

                psycopg2.extras.execute_batch(
                    cur,
                    "INSERT INTO activities (who, what, when_ts) VALUES (%s,%s,%s)",
                    [
                        ("System", "Initialized database", datetime.utcnow()),
                        ("System", "Seeded demo bundles", datetime.utcnow() + timedelta(seconds=1)),
                    ],
                )
            conn.commit()
        else:
            log.info("Bundles already present (%s) — seeding skipped", count)

ensure_db()

# -----------------------------------------------------------------------------
# Static UI routes
# -----------------------------------------------------------------------------
@app.get("/")
def serve_index():
    if UI_DIR and (UI_DIR / "index.html").exists():
        return send_from_directory(str(UI_DIR), "index.html")
    # Helpful fallback page
    body = f"""
    <h2>Factory Ops Dashboard</h2>
    <p><code>index.html</code> not found in any of:</p>
    <pre>{chr(10).join(str(p) for p in CANDIDATE_UI_DIRS)}</pre>
    <p>Place <code>index.html</code>, <code>style.css</code>, and <code>app.js</code> in ONE of those folders and redeploy.</p>
    <ul>
      <li>Check API: <a href="/api/stats">/api/stats</a></li>
      <li>Health: <a href="/health">/health</a></li>
    </ul>
    """
    return body, 200, {"Content-Type": "text/html; charset=utf-8"}

# Serve common asset filenames at the root (so your existing <link src="./style.css"> works)
ASSET_EXTS = {".css", ".js", ".map", ".ico", ".png", ".jpg", ".jpeg", ".svg",
              ".woff", ".woff2", ".ttf", ".eot", ".json"}

@app.get("/<path:filename>")
def serve_assets(filename: str):
    # Do NOT swallow API routes
    if filename.startswith("api/") or filename in {"health"}:
        abort(404)
    # Only serve static-like extensions
    ext = Path(filename).suffix.lower()
    if ext not in ASSET_EXTS:
        abort(404)
    # Try the chosen UI_DIR first, then all candidates
    search_dirs = ([UI_DIR] if UI_DIR else []) + CANDIDATE_UI_DIRS
    for d in search_dirs:
        if d and (d / filename).exists():
            return send_from_directory(str(d), filename)
        # Also try same filename but sitting directly under d (no subfolders)
        if d and (d / Path(filename).name).exists():
            return send_from_directory(str(d), Path(filename).name)
    abort(404)

# -----------------------------------------------------------------------------
# Health
# -----------------------------------------------------------------------------
@app.get("/health")
def health():
    return jsonify({"ok": True, "time": datetime.utcnow().isoformat() + "Z"})

# -----------------------------------------------------------------------------
# APIs
# -----------------------------------------------------------------------------
@app.get("/api/stats")
def api_stats():
    if not DATABASE_URL:
        return jsonify({
            "active_workers": 12,
            "total_operations": 348,
            "bundles": 4,
            "earnings_today": 1250,
        })

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM workers;")
        workers = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM scans;")
        ops = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM bundles;")
        bundles = cur.fetchone()[0]
        cur.execute("SELECT COALESCE(SUM(qty),0) FROM bundles WHERE status IS NOT NULL;")
        earnings = (cur.fetchone()[0] or 0) * 10

    return jsonify({
        "active_workers": workers,
        "total_operations": ops,
        "bundles": bundles,
        "earnings_today": earnings,
    })

@app.get("/api/activities")
def api_activities():
    items = []
    if DATABASE_URL:
        with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT who, what, when_ts FROM activities ORDER BY when_ts DESC LIMIT 25;")
            items = [{"who": r["who"], "what": r["what"], "when": r["when_ts"].isoformat()} for r in cur.fetchall()]
    else:
        items = [
            {"who": "System", "what": "Server started", "when": datetime.utcnow().isoformat()},
            {"who": "Scanner", "what": "Processed 3 bundles", "when": datetime.utcnow().isoformat()},
        ]
    return jsonify(items)

@app.get("/api/chart-data")
def chart_data():
    now = datetime.utcnow()
    labels = [(now - timedelta(days=30 - i)).strftime("%b %d") for i in range(31)]
    values = [max(0, (i * 3) % 20 - (i // 7)) for i in range(31)]
    return jsonify({"labels": labels, "values": values})

@app.get("/api/export-earnings.csv")
def export_earnings_csv():
    rows = [("Department", "Earnings")]
    if DATABASE_URL:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT COALESCE(w.department,'Unknown') AS dept, COALESCE(SUM(b.qty),0) * 10 AS earnings
                FROM bundles b
                LEFT JOIN workers w ON TRUE
                GROUP BY dept
                ORDER BY dept;
            """)
            for dept, earnings in cur.fetchall():
                rows.append((dept, int(earnings)))
    else:
        rows += [("Cutting", 540), ("Sewing", 760), ("Finishing", 320)]

    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=earnings.csv"},
    )

@app.post("/api/simulate-scan")
def simulate_scan():
    data = request.get_json(force=True, silent=True) or {}
    token = str(data.get("token", "")).strip()
    kind = str(data.get("kind", "Work")).strip()

    if DATABASE_URL and token:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO scans (token, kind) VALUES (%s,%s);", (token, kind))
            conn.commit()
    return jsonify({"ok": True, "token": token, "kind": kind})

# -----------------------------------------------------------------------------
# Entry
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
