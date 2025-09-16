import os
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor


# -----------------------------
# Flask
# -----------------------------
app = Flask(__name__, static_folder="static", template_folder="templates")
CORS(app)


# -----------------------------
# Database URL normalizer
# -----------------------------
def _normalize_db_url(raw: str) -> str:
    """
    Make DATABASE_URL friendly for psycopg2:
    - postgres://  -> postgresql://
    - ensure sslmode=require (Render / Neon / Supabase style)
    """
    if not raw:
        return ""

    # fix scheme if needed
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://") :]

    p = urlparse(raw)
    scheme = "postgresql"  # psycopg2 expects this
    q = dict(parse_qsl(p.query or "", keep_blank_values=True))
    q["sslmode"] = (q.get("sslmode") or "require").strip().strip('"').strip("'")

    return urlunparse(
        (scheme, p.netloc, p.path, p.params, urlencode(q, doseq=True), p.fragment)
    )


RAW_DB_URL = os.getenv("DATABASE_URL", "")  # e.g. postgresql://user:pass@host/db?sslmode=require
DB_URL = _normalize_db_url(RAW_DB_URL)


def get_conn():
    if not DB_URL:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)


# -----------------------------
# Optional: bootstrap a simple table
# -----------------------------
def init_db():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS scans (
                id SERIAL PRIMARY KEY,
                code TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        conn.commit()


# -----------------------------
# Routes
# -----------------------------
@app.get("/health")
def health():
    return "OK", 200


@app.get("/")
def index():
    # Renders templates/index.html (make sure that file exists)
    return render_template("index.html")


@app.post("/api/scan")
def api_scan():
    """
    Minimal example endpoint to store a scanned code.
    JSON body: { "code": "ABC123" }
    """
    payload = request.get_json(silent=True) or {}
    code = (payload.get("code") or "").strip()
    if not code:
        return jsonify({"error": "code is required"}), 400

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO scans (code) VALUES (%s) RETURNING id, created_at;", (code,))
        row = cur.fetchone()
        conn.commit()

    return jsonify({"ok": True, "id": row["id"], "created_at": row["created_at"]})


@app.get("/api/scans")
def list_scans():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, code, created_at FROM scans ORDER BY id DESC LIMIT 100;")
        rows = cur.fetchall()
    return jsonify(rows)


# -----------------------------
# Startup
# -----------------------------
if __name__ == "__main__":
    # Local dev: `python app.py`
    port = int(os.getenv("PORT", "5000"))
    init_db()
    app.run(host="0.0.0.0", port=port, debug=True)
else:
    # On render with gunicorn, run init_db once at import
    try:
        init_db()
    except Exception as e:
        # don't block boot if DB isn't ready; logs will show the error
        print(f"DB init skipped: {e}")
