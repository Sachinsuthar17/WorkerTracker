import os
import io
from contextlib import closing
from datetime import datetime
from typing import Optional

from flask import (
    Flask, request, jsonify, render_template, redirect,
    url_for, flash, abort, g, send_file
)
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import SimpleConnectionPool

# Optional: QR generation (used by /workers/<id>/qr.png)
try:
    import qrcode
except Exception:  # pragma: no cover
    qrcode = None

# ------------------------------------------------------------------------------
# App & Config
# ------------------------------------------------------------------------------
app = Flask(__name__)
CORS(app)

# Set a secret key for flashes (adjust for your environment)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-key")

DATABASE_URL = os.environ["DATABASE_URL"]
DB_SSLMODE = os.getenv("DB_SSLMODE", "require")
POOL = SimpleConnectionPool(
    minconn=1,
    maxconn=int(os.getenv("DB_MAX_CONN", "10")),
    dsn=DATABASE_URL,
    sslmode=DB_SSLMODE,
)

# ------------------------------------------------------------------------------
# DB helpers
# ------------------------------------------------------------------------------
def get_db():
    """Get a pooled connection for this request."""
    if "dbconn" not in g:
        g.dbconn = POOL.getconn()
        g.dbconn.autocommit = True
    return g.dbconn

@app.teardown_request
def _return_conn(exc):
    conn = g.pop("dbconn", None)
    if conn is not None:
        POOL.putconn(conn)

def fetchone_dict(cur) -> Optional[dict]:
    row = cur.fetchone()
    if row is None:
        return None
    if isinstance(row, dict):
        return row
    # map tuple → dict when cursor_factory not set
    desc = [c.name for c in cur.description]
    return dict(zip(desc, row))

# ------------------------------------------------------------------------------
# Schema (run ONCE at worker boot, not per request)
# ------------------------------------------------------------------------------
def ensure_schema_once():
    with closing(psycopg2.connect(DATABASE_URL, sslmode=DB_SSLMODE)) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            # Workers
            cur.execute("""
            CREATE TABLE IF NOT EXISTS workers (
              id SERIAL PRIMARY KEY,
              name TEXT NOT NULL,
              qrcode TEXT,
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """)
            # Activities (for /api/activities)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS activities (
              id SERIAL PRIMARY KEY,
              event TEXT NOT NULL,
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """)
            # Operations (used by /operations and /operations/add)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS operations (
              id SERIAL PRIMARY KEY,
              name TEXT NOT NULL,
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """)
    app.config["SCHEMA_READY"] = True

with app.app_context():
    if not app.config.get("SCHEMA_READY"):
        ensure_schema_once()

# ------------------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------------------

@app.get("/")
def home():
    # Keep your existing index template if you have one; otherwise this is fine.
    return render_template("index.html") if os.path.exists(
        os.path.join(app.root_path, "templates", "index.html")
    ) else """
    <!doctype html>
    <meta charset="utf-8">
    <title>ESP32 API Server</title>
    <h1>Service is live 🎉</h1>
    <ul>
      <li><a href="/api/stats">/api/stats</a></li>
      <li><a href="/workers">/workers</a></li>
      <li><a href="/operations">/operations</a></li>
      <li><a href="/assign_operation">/assign_operation</a></li>
      <li><a href="/reports">/reports</a></li>
    </ul>
    """

# -------------------------- API: stats & activities ---------------------------

@app.get("/api/stats")
def api_stats():
    conn = get_db()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT COUNT(*) AS workers FROM workers;")
        workers = cur.fetchone()["workers"]

        cur.execute("SELECT COUNT(*) AS operations FROM operations;")
        operations = cur.fetchone()["operations"]

        cur.execute("SELECT COUNT(*) AS activities FROM activities;")
        activities = cur.fetchone()["activities"]

    return jsonify({
        "workers": workers,
        "operations": operations,
        "activities": activities,
        "ts": datetime.utcnow().isoformat() + "Z",
    })

@app.get("/api/activities")
def api_activities():
    limit = max(1, min(int(request.args.get("limit", 100)), 1000))
    conn = get_db()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT id, event, created_at FROM activities ORDER BY id DESC LIMIT %s;",
            (limit,),
        )
        rows = cur.fetchall()
    return jsonify(rows)

# -------------------------------- Workers UI ---------------------------------

@app.get("/workers")
def workers_page():
    q = (request.args.get("q") or "").strip()
    sql = "SELECT id, name, qrcode, created_at FROM workers"
    params = ()
    if q:
        sql += " WHERE name ILIKE %s"
        params = (f"%{q}%",)
    sql += " ORDER BY id ASC;"

    conn = get_db()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    # Use your existing "workers.html" if present; otherwise render a basic list
    template_path = os.path.join(app.root_path, "templates", "workers.html")
    if os.path.exists(template_path):
        return render_template("workers.html", workers=rows, query=q)

    # Fallback minimal page
    items = "".join(
        f'<li>#{w["id"]} — {w["name"]} '
        f'[<a href="/workers/{w["id"]}/print">print</a>] '
        f'[<img src="/workers/{w["id"]}/qr.png" alt="qr" width="80">]</li>'
        for w in rows
    )
    return f"""
    <!doctype html><meta charset="utf-8">
    <h1>Workers</h1>
    <form><input name="q" placeholder="Search name" value="{q}"><button>Search</button></form>
    <ul>{items or "<li><em>No workers yet.</em></li>"}</ul>
    """

@app.get("/workers/<int:wid>/qr.png")
def worker_qr_png(wid: int):
    """PNG QR for the worker — uses the worker id as payload by default."""
    # Make sure the worker exists
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM workers WHERE id=%s;", (wid,))
        if cur.fetchone() is None:
            abort(404)

    # If qrcode lib missing, return a 1x1 png
    if not qrcode:
        return send_file(
            io.BytesIO(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
                       b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc`\x00\x00\x00\x02\x00\x01"
                       b"\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"),
            mimetype="image/png",
        )

    # Build a simple QR payload; adjust to your real payload if needed.
    payload = f"worker:{wid}"
    img = qrcode.make(payload)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")

@app.get("/workers/<int:wid>/print")
def worker_print(wid: int):
    """Printable view for one worker (uses print_qr.html)."""
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("SELECT id, name, qrcode FROM workers WHERE id=%s;", (wid,))
        row = fetchone_dict(cur)
    if not row:
        abort(404)
    # ✅ Use the template you actually have:
    return render_template("print_qr.html", worker=row)

# ------------------------------- Operations UI --------------------------------

@app.get("/operations")
def operations_page():
    conn = get_db()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id, name, created_at FROM operations ORDER BY id DESC;")
        ops = cur.fetchall()

    # Use existing template if available
    template_path = os.path.join(app.root_path, "templates", "operations.html")
    if os.path.exists(template_path):
        return render_template("operations.html", operations=ops)

    # Fallback minimal page with a form posting to /operations/add
    rows = "".join(f"<li>#{o['id']} — {o['name']}</li>" for o in ops)
    return f"""
    <!doctype html><meta charset="utf-8">
    <h1>Operations</h1>
    <form method="post" action="/operations/add">
      <input name="name" placeholder="Operation name" required>
      <button type="submit">Add</button>
    </form>
    <ul>{rows or "<li><em>No operations yet.</em></li>"}</ul>
    """

@app.post("/operations/add")
def operations_add():
    """Fix for 404: handler now exists."""
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Operation name required", "error")
        return redirect(url_for("operations_page"))

    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("INSERT INTO operations (name) VALUES (%s) RETURNING id;", (name,))
        op_id = cur.fetchone()[0]

    flash(f"Operation {op_id} created", "success")
    return redirect(url_for("operations_page"))

# ------------------------- Stub pages (keep your own) --------------------------

@app.get("/assign_operation")
def assign_operation_page():
    # If you have a template, it will be used. Otherwise a stub renders.
    template_path = os.path.join(app.root_path, "templates", "assign_operation.html")
    if os.path.exists(template_path):
        return render_template("assign_operation.html")
    return "<h1>Assign Operation</h1><p>Build your UI here.</p>"

@app.get("/reports")
def reports_page():
    template_path = os.path.join(app.root_path, "templates", "reports.html")
    if os.path.exists(template_path):
        return render_template("reports.html")
    return "<h1>Reports</h1><p>Build your UI here.</p>"

# ------------------------------------------------------------------------------
# Gunicorn entrypoint
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    # For local testing only; Render will run gunicorn.
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")), debug=True)
