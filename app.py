import os
import csv
import io
import logging
from datetime import datetime, timedelta
from pathlib import Path

from flask import (
    Flask, jsonify, send_from_directory, Response, request
)
from flask_cors import CORS
import psycopg2
import psycopg2.extras

# -----------------------------------------------------------------------------
# Flask setup
# -----------------------------------------------------------------------------
# Static files live in the SAME folder as app.py:
#   - index.html
#   - style.css
#   - app.js
#
# static_url_path='' makes /style.css and /app.js resolve at the root.
APP_DIR = Path(__file__).resolve().parent
app = Flask(__name__, static_folder=str(APP_DIR), static_url_path='')
CORS(app)
logging.basicConfig(level=logging.INFO)
log = app.logger

# Helpful startup diagnostics so you can see what Render actually packaged
def _log_static_presence():
    files = list(APP_DIR.glob("*"))
    summary = ", ".join(sorted([p.name for p in files if p.suffix in {'.html','.css','.js'}]))
    log.info("Working dir: %s", APP_DIR)
    log.info("Static present: %s", summary or "(no html/css/js found)")
    for f in ["index.html", "style.css", "app.js"]:
        log.info("%s exists? %s", f, (APP_DIR / f).exists())

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
    """
    Create tables if they don't exist. Seed a few demo rows if empty.
    The seed step adapts to whether `barcode_value` exists on `bundles`.
    """
    if not DATABASE_URL:
        log.warning("DATABASE_URL not set; API will return mock data only.")
        return

    with get_conn() as conn:
        with conn.cursor() as cur:
            # workers
            cur.execute("""
                CREATE TABLE IF NOT EXISTS workers (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    token TEXT UNIQUE,
                    department TEXT,
                    line TEXT
                );
            """)
            # bundles (barcode_value is NOT NULL in your DB; include it and give a default)
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
            # scans (lightweight)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS scans (
                    id SERIAL PRIMARY KEY,
                    token TEXT,
                    kind TEXT,
                    scanned_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            # activities (to back your /api/activities table)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS activities (
                    id SERIAL PRIMARY KEY,
                    who TEXT,
                    what TEXT,
                    when_ts TIMESTAMPTZ DEFAULT NOW()
                );
            """)

        # detect if we need to seed
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM bundles;")
            count = cur.fetchone()[0]

        if count == 0 and os.getenv("SKIP_SEED", "0") != "1":
            # Does column barcode_value exist?
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name='bundles';
                """)
                cols = {r[0] for r in cur.fetchall()}

            # a tiny seed set
            seed = [
                ("A12", 120, "pending"),
                ("B04", 90,  "pending"),
                ("C33", 45,  "pending"),
                ("D18", 30,  "pending"),
            ]

            with conn.cursor() as cur:
                if "barcode_value" in cols:
                    # include a simple generated barcode so NOT NULL isn't violated
                    rows = []
                    for i, (code, qty, status) in enumerate(seed, start=1):
                        rows.append((
                            f"BC-{code}-{i:04d}",   # barcode_value
                            "code128",              # barcode_type
                            qty,
                            None,                   # scanned_at
                            code,
                            status
                        ))
                    psycopg2.extras.execute_batch(
                        cur,
                        """
                        INSERT INTO bundles
                          (barcode_value, barcode_type, qty, scanned_at, bundle_code, status)
                        VALUES (%s,%s,%s,%s,%s,%s)
                        """,
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

                # a little activity feed
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

# Run ensure_db at import time so Render logs show results during boot
ensure_db()

# -----------------------------------------------------------------------------
# Static file routes
# -----------------------------------------------------------------------------
@app.route("/")
def root():
    # Serve your UI if present; otherwise, show a helpful page.
    index_path = APP_DIR / "index.html"
    if index_path.exists():
        return send_from_directory(str(APP_DIR), "index.html")
    return (
        """
        <h2>Factory Ops Dashboard</h2>
        <p><code>index.html</code> not found in the deployment bundle.</p>
        <p>Add <code>index.html</code>, <code>style.css</code>, and <code>app.js</code> to the same directory as <code>app.py</code> and redeploy.</p>
        <ul>
          <li>Check API: <a href="/api/stats">/api/stats</a></li>
          <li>Health: <a href="/health">/health</a></li>
        </ul>
        """,
        200,
        {"Content-Type": "text/html; charset=utf-8"},
    )

# Let Flask serve style.css and app.js directly from the same folder
# (This works because static_folder=APP_DIR and static_url_path='')
# e.g. GET /style.css, GET /app.js

# -----------------------------------------------------------------------------
# Health
# -----------------------------------------------------------------------------
@app.get("/health")
def health():
    return jsonify({"ok": True, "time": datetime.utcnow().isoformat() + "Z"})

# -----------------------------------------------------------------------------
# Minimal APIs the UI expects
# -----------------------------------------------------------------------------
@app.get("/api/stats")
def api_stats():
    """
    Returns top-level metrics used on the overview tiles.
    Falls back to mock numbers when DATABASE_URL is absent.
    """
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

        # Fake earnings: qty of bundles with status not null * 10
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
    """
    Returns a small recent activity list.
    """
    items = []
    if DATABASE_URL:
        with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT who, what, when_ts FROM activities ORDER BY when_ts DESC LIMIT 25;")
            items = [
                {"who": r["who"], "what": r["what"], "when": r["when_ts"].isoformat()}
                for r in cur.fetchall()
            ]
    else:
        items = [
            {"who": "System", "what": "Server started", "when": datetime.utcnow().isoformat()},
            {"who": "Scanner", "what": "Processed 3 bundles", "when": datetime.utcnow().isoformat()},
        ]
    return jsonify(items)

@app.get("/api/chart-data")
def chart_data():
    """
    Very simple month-series mock. Replace with your real aggregation later.
    """
    now = datetime.utcnow()
    labels = [(now - timedelta(days=30 - i)).strftime("%b %d") for i in range(31)]
    values = [max(0, (i * 3) % 20 - (i // 7)) for i in range(31)]
    return jsonify({"labels": labels, "values": values})

@app.get("/api/export-earnings.csv")
def export_earnings_csv():
    """
    Quick CSV export used by your 'Export Earnings CSV' link.
    """
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
    writer = csv.writer(buf)
    writer.writerows(rows)
    out = buf.getvalue()
    return Response(
        out,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=earnings.csv"},
    )

# -----------------------------------------------------------------------------
# ESP32 scan simulation (used by your front-end)
# -----------------------------------------------------------------------------
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
