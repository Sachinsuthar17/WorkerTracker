from flask import Flask, render_template, request, jsonify, Response, send_from_directory
from flask_cors import CORS
import os
import io
import csv

# ---- Postgres (psycopg v3) ----
import psycopg
from psycopg.rows import dict_row
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

app = Flask(__name__)
CORS(app)

# ---- DATABASE URL: sanitize & force sslmode=require ----
_raw = (os.getenv("DATABASE_URL") or "").strip().strip('"').strip("'")
if not _raw:
    raise RuntimeError("DATABASE_URL is not set.")

p = urlparse(_raw)
scheme = (p.scheme or "postgresql").split("+", 1)[0]
if scheme == "postgres":
    scheme = "postgresql"
q = dict(parse_qsl(p.query, keep_blank_values=True))
q["sslmode"] = (q.get("sslmode") or "require")
DB_URL = urlunparse((scheme, p.netloc, p.path, p.params, urlencode(q, doseq=True), p.fragment))

def get_conn():
    # psycopg v3 connects with a single URL string
    return psycopg.connect(DB_URL, row_factory=dict_row)

# ---- Auto-migrate: ensure tables & missing columns exist ----
def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
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
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS operations (
                    id SERIAL PRIMARY KEY,
                    op_no INTEGER UNIQUE,
                    description TEXT,
                    machine TEXT,
                    department TEXT,
                    std_min NUMERIC,
                    piece_rate NUMERIC,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)
            # In case the table already existed without piece_rate, add it:
            cur.execute("ALTER TABLE operations ADD COLUMN IF NOT EXISTS piece_rate NUMERIC;")

            cur.execute("""
                CREATE TABLE IF NOT EXISTS bundles (
                    id SERIAL PRIMARY KEY,
                    code TEXT UNIQUE,
                    qty INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'Pending'
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS scan_logs (
                    id SERIAL PRIMARY KEY,
                    token_id TEXT NOT NULL,
                    scan_type TEXT DEFAULT 'work',
                    scanned_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)
        conn.commit()

# Run bootstrap once at import time; app will fail fast with a clear error if DB URL is bad
init_db()

@app.route("/")
def index():
    return "OK"  # replace with render_template('index.html') if you have templates

# (keep your other routes below)
# ...
# favicon (optional)
@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
