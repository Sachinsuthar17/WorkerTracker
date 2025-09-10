# app.py
import os
import io
import csv
from datetime import datetime, date
from flask import Flask, request, jsonify, render_template, redirect, url_for, send_file, flash
import qrcode  # make sure it's in requirements.txt

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# ---------------- Database URL ---------------- #
DATABASE_URL = os.getenv("DATABASE_URL")

# Render sometimes provides 'postgres://'; SQLAlchemy needs 'postgresql://'
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if not DATABASE_URL:
    raise RuntimeError("❌ DATABASE_URL is not set. Add it in Render dashboard.")

# SQLAlchemy engine + session
engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

DEVICE_SECRET = os.getenv("DEVICE_SECRET", "garment_erp_2024_secret")
AUTO_CREATE_UNKNOWN = os.getenv("AUTO_CREATE", "1") == "1"

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret")

# ---------------- DB Helpers ---------------- #
def query(sql, args=None, one=False):
    """Run a SELECT and return list of mapping rows (or one)."""
    args = args or {}
    with SessionLocal() as session:
        result = session.execute(text(sql), args)
        rows = result.mappings().all()
        return (rows[0] if rows else None) if one else rows

def execute(sql, args=None, expect_id=False):
    """
    Run an INSERT/UPDATE/DELETE. If expect_id=True, the SQL MUST include 'RETURNING id'
    and this returns that id; otherwise returns affected rowcount.
    """
    args = args or {}
    with SessionLocal() as session:
        result = session.execute(text(sql), args)
        ret = None
        if expect_id:
            # expecting a single row, single column id
            ret = result.scalar()
        else:
            ret = result.rowcount
        session.commit()
        return ret

def get_settings():
    return query("SELECT * FROM settings WHERE id=1", one=True)

def ensure_basics():
    """Create schema if missing."""
    from db_setup import init_db  # your Postgres-aware schema creator
    print(f"🔧 Using Postgres DB at: {DATABASE_URL}")
    init_db(DATABASE_URL)

# Initialize DB schema at startup
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
        "SELECT COUNT(*) AS c FROM scans WHERE DATE(timestamp) = CURRENT_DATE",
        one=True
    )["c"]

    total_std_today = query("""
        SELECT COALESCE(SUM(o.std_min),0) AS mins
        FROM scans s 
        JOIN operations o ON s.operation_id = o.id
        WHERE DATE(s.timestamp) = CURRENT_DATE
    """, one=True)["mins"]

    base_rate = get_settings()["base_rate_per_min"]
    earnings_today = round(float(total_std_today) * float(base_rate), 2)

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
        WHERE DATE(s.timestamp) = CURRENT_DATE
