import os
import io
import csv
import sqlite3
from datetime import datetime, date
from flask import Flask, request, jsonify, render_template, redirect, url_for, send_file, flash
import qrcode  # require in requirements.txt

# ---------------- Database Path ---------------- #
default_data_dir = '/opt/render/data'
try:
    os.makedirs(default_data_dir, exist_ok=True)
except Exception:
    default_data_dir = '/tmp'
    os.makedirs(default_data_dir, exist_ok=True)

default_db = os.path.join(default_data_dir, 'factory.db')
DB_PATH = os.getenv("DATABASE_URL", default_db)

DEVICE_SECRET = os.getenv("DEVICE_SECRET", "garment_erp_2024_secret")
AUTO_CREATE_UNKNOWN = os.getenv("AUTO_CREATE", "1") == "1"

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret")

# ---------------- DB Helpers ---------------- #

def get_conn():
    # ✅ ensure directory exists before every connection
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def query(sql, args=(), one=False):
    with get_conn() as conn:
        cur = conn.execute(sql, args)
        rv = cur.fetchall()
        cur.close()
    return (rv[0] if rv else None) if one else rv

def execute(sql, args=()):
    with get_conn() as conn:
        cur = conn.execute(sql, args)
        conn.commit()
        last_id = cur.lastrowid
        cur.close()
        return last_id

def get_settings():
    return query("SELECT * FROM settings WHERE id=1", one=True)

def ensure_basics():
    from db_setup import init_db
    print(f"🔧 Using DB at {DB_PATH}")  # helpful for Render logs
    init_db()

# Initialize DB at startup
ensure_basics()

# ---------------- QR Code ---------------- #

def generate_qr_png(text: str) -> bytes:
    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return bio.read()

# ---------------- Routes ---------------- #

@app.route("/")
def index():
    return redirect(url_for("dashboard"))

@app.route("/dashboard")
def dashboard():
    total_workers = query("SELECT COUNT(*) AS c FROM users", one=True)["c"]
    bundles_active = query("SELECT COUNT(*) AS c FROM bundles", one=True)["c"]
    scans_today = query(
        "SELECT COUNT(*) AS c FROM scans WHERE DATE(timestamp, 'localtime') = DATE('now','localtime')",
        one=True)["c"]

    total_std_today = query("""
        SELECT COALESCE(SUM(o.std_min),0) AS mins
        FROM scans s 
        JOIN operations o ON s.operation_id = o.id
        WHERE DATE(s.timestamp, 'localtime') = DATE('now','localtime')
    """, one=True)["mins"]

    base_rate = get_settings()["base_rate_per_min"]
    earnings_today = round(total_std_today * base_rate, 2)

    recent = query("""
        SELECT s.id, s.timestamp, u.name AS worker, b.bundle_code AS bundle, 
               o.op_no, o.description AS op_desc, o.std_min
        FROM scans s
        JOIN users u ON u.id = s.worker_id
        JOIN bundles b ON b.id = s.bundle_id
        JOIN operations o ON o.id = s.operation_id
        ORDER BY s.timestamp DESC
        LIMIT 20
    """)

    leaderboard = query("""
        SELECT u.name, COUNT(*) AS pieces, ROUND(SUM(o.std_min),2) AS std_min
        FROM scans s
        JOIN users u ON u.id = s.worker_id
        JOIN operations o ON o.id = s.operation_id
        WHERE DATE(s.timestamp, 'localtime') = DATE('now','localtime')
        GROUP BY u.name
        ORDER BY pieces DESC
        LIMIT 10
    """)

    return render_template("dashboard.html",
        total_workers=total_workers,
        bundles_active=bundles_active,
        scans_today=scans_today,
        earnings_today=earnings_today,
        recent=recent,
        leaderboard=leaderboard,
        settings=get_settings()
    )

# ---------------- Users ---------------- #
# (your existing user routes here)

# ---------------- Bundles ---------------- #
# (your existing bundle routes here)

# ---------------- Operations ---------------- #
# (your existing operation routes here)

# ---------------- Tasks ---------------- #
# (your existing task routes here)

# ---------------- Reports ---------------- #
# (your existing reports routes here)

# ---------------- APIs ---------------- #

@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat()}), 200

# ---------------- Main ---------------- #

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
