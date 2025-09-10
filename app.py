import os
import io
import csv
from datetime import datetime, date
from flask import Flask, request, jsonify, render_template, redirect, url_for, send_file, flash
import qrcode

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
    """Run a SELECT and return list of dict rows (or one)."""
    args = args or {}
    with SessionLocal() as session:
        result = session.execute(text(sql), args)
        rows = result.mappings().all()
        return (rows[0] if rows else None) if one else rows

def execute(sql, args=None, expect_id=False):
    """
    Run an INSERT/UPDATE/DELETE.
    - If expect_id=True, the SQL MUST include 'RETURNING id' and this returns that id.
    - Otherwise returns affected rowcount.
    """
    args = args or {}
    with SessionLocal() as session:
        result = session.execute(text(sql), args)
        ret = result.scalar() if expect_id else result.rowcount
        session.commit()
        return ret

def get_settings():
    return query("SELECT * FROM settings WHERE id=1", one=True)

def ensure_basics():
    """Create schema if missing."""
    from db_setup import init_db
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

    base_rate = float(get_settings()["base_rate_per_min"])
    earnings_today = round(float(total_std_today) * base_rate, 2)

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
        GROUP BY u.name
        ORDER BY pieces DESC
        LIMIT 10
    """)

    return render_template(
        "dashboard.html",
        total_workers=total_workers,
        bundles_active=bundles_active,
        scans_today=scans_today,
        earnings_today=earnings_today,
        recent=recent,
        leaderboard=leaderboard,
        settings=get_settings()
    )

# ---------------- Users ---------------- #
@app.route("/users", methods=["GET", "POST"])
def users():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        worker_code = request.form.get("worker_code", "").strip()
        department = request.form.get("department") or None
        skill = request.form.get("skill") or None
        hourly_rate = float(request.form.get("hourly_rate") or 0)

        try:
            execute(
                """
                INSERT INTO users(worker_code, name, department, skill, hourly_rate, qr_code)
                VALUES (:worker_code, :name, :department, :skill, :hourly_rate, :qr_code)
                """,
                dict(worker_code=worker_code, name=name, department=department,
                     skill=skill, hourly_rate=hourly_rate, qr_code=worker_code)
            )
            flash("Worker added", "success")
        except Exception:
            flash(f"Worker code already exists: {worker_code}", "danger")

        return redirect(url_for("users"))

    rows = query("SELECT * FROM users ORDER BY id DESC")
    return render_template("users.html", users=rows)

@app.route("/users/<int:uid>/delete", methods=["POST"])
def users_delete(uid):
    execute("DELETE FROM users WHERE id = :id", {"id": uid})
    flash("Worker deleted", "info")
    return redirect(url_for("users"))

@app.route("/qrcode/worker/<int:uid>.png")
def worker_qr(uid):
    row = query("SELECT worker_code FROM users WHERE id=:id", {"id": uid}, one=True)
    if not row:
        return ("not found", 404)
    return send_file(io.BytesIO(generate_qr_png(row["worker_code"])), mimetype="image/png")

# ---------------- Bundles ---------------- #
@app.route("/bundles", methods=["GET","POST"])
def bundles_page():
    if request.method == "POST":
        bundle_code = request.form.get("bundle_code", "").strip()
        style = request.form.get("style") or None
        color = request.form.get("color") or None
        size_range = request.form.get("size_range") or None
        quantity = int(request.form.get("quantity") or 0)

        try:
            execute(
                """
                INSERT INTO bundles(bundle_code, style, color, size_range, quantity, current_op, qr_code)
                VALUES (:bundle_code, :style, :color, :size_range, :quantity, :current_op, :qr_code)
                """,
                dict(bundle_code=bundle_code, style=style, color=color,
                     size_range=size_range, quantity=quantity,
                     current_op=None, qr_code=bundle_code)
            )
            flash("Bundle added", "success")
        except Exception:
            flash(f"Bundle already exists: {bundle_code}", "danger")

        return redirect(url_for("bundles_page"))

    rows = query("SELECT * FROM bundles ORDER BY id DESC")
    return render_template("bundles.html", bundles=rows)

@app.route("/qrcode/bundle/<int:bid>.png")
def bundle_qr(bid):
    row = query("SELECT bundle_code FROM bundles WHERE id=:id", {"id": bid}, one=True)
    if not row:
        return ("not found", 404)
    return send_file(io.BytesIO(generate_qr_png(row["bundle_code"])), mimetype="image/png")

# ---------------- Operations ---------------- #
@app.route("/operations", methods=["GET","POST"])
def operations_page():
    if request.method == "POST":
        op_no = request.form.get("op_no", "").strip()
        description = request.form.get("description") or None
        section = request.form.get("section") or None
        std_min = float(request.form.get("std_min") or 0)

        try:
            execute(
                """
                INSERT INTO operations(op_no, description, section, std_min)
                VALUES (:op_no, :description, :section, :std_min)
                """,
                dict(op_no=op_no, description=description, section=section, std_min=std_min)
            )
            flash("Operation added", "success")
        except Exception:
            flash(f"Operation already exists: {op_no}", "danger")

        return redirect(url_for("operations_page"))

    rows = query("SELECT * FROM operations ORDER BY op_no ASC")
    return render_template("operations.html", operations=rows)

# ---------------- Tasks ---------------- #
@app.route("/assign_task", methods=["GET","POST"])
def assign_task():
    if request.method == "POST":
        worker_id = int(request.form.get("worker_id"))
        description = request.form.get("description", "").strip()
        execute(
            "INSERT INTO tasks(worker_id, description, status) VALUES (:worker_id, :description, 'OPEN')",
            dict(worker_id=worker_id, description=description)
        )
        flash("Task assigned", "success")
        return redirect(url_for("assign_task"))

    workers = query("SELECT * FROM users ORDER BY name")
    tasks = query("""
        SELECT t.*, u.name 
        FROM tasks t 
        JOIN users u ON u.id = t.worker_id 
        ORDER BY t.created_at DESC
    """)
    return render_template("assign_task.html", workers=workers, tasks=tasks)

@app.route("/tasks/<int:tid>/complete", methods=["POST"])
def complete_task(tid):
    execute("UPDATE tasks SET status='DONE' WHERE id=:id", {"id": tid})
    flash("Task completed", "info")
    return redirect(url_for("assign_task"))

# ---------------- Reports ---------------- #
@app.route("/reports")
def reports():
    start = request.args.get("start") or date.today().isoformat()
    end = request.args.get("end") or date.today().isoformat()

    rows = query("""
        SELECT u.name AS worker, COUNT(*) AS pieces, ROUND(SUM(o.std_min),2) AS std_min,
               ROUND(SUM(o.std_min) * (SELECT base_rate_per_min FROM settings WHERE id=1), 2) AS earnings
        FROM scans s 
        JOIN users u ON u.id = s.worker_id
        JOIN operations o ON o.id = s.operation_id
        WHERE DATE(s.timestamp) BETWEEN :start AND :end
        GROUP BY u.name
        ORDER BY pieces DESC
    """, {"start": start, "end": end})

    bundles = query("""
        SELECT b.bundle_code, COUNT(*) AS pieces, ROUND(SUM(o.std_min),2) AS std_min
        FROM scans s
        JOIN bundles b ON b.id = s.bundle_id
        JOIN operations o ON o.id = s.operation_id
        WHERE DATE(s.timestamp) BETWEEN :start AND :end
        GROUP BY b.bundle_code
        ORDER BY pieces DESC
    """, {"start": start, "end": end})

    return render_template(
        "reports.html",
        rows=rows, bundles=bundles,
        start=start, end=end,
        settings=get_settings()
    )

@app.route("/export/scans.csv")
def export_scans_csv():
    rows = query("""
        SELECT s.id, s.timestamp, u.worker_code, u.name, b.bundle_code, 
               o.op_no, o.description, o.std_min
        FROM scans s
        JOIN users u ON u.id=s.worker_id
        JOIN bundles b ON b.id=s.bundle_id
        JOIN operations o ON o.id=s.operation_id
        ORDER BY s.timestamp DESC
    """)
    si = io.StringIO()
    writer = csv.writer(si)
    writer.writerow(["id","timestamp","worker_code","name","bundle_code","operation","description","std_min"])
    for r in rows:
        writer.writerow([
            r["id"], r["timestamp"], r["worker_code"], r["name"],
            r["bundle_code"], r["op_no"], r["description"], r["std_min"]
        ])
    return send_file(
        io.BytesIO(si.getvalue().encode("utf-8")),
        mimetype="text/csv",
        as_attachment=True,
        download_name="scans.csv"
    )

# ---------------- APIs ---------------- #
@app.route("/api/logs")
def api_logs():
    rows = query("""
        SELECT s.timestamp, u.name AS worker, b.bundle_code AS bundle, o.op_no AS operation
        FROM scans s
        JOIN users u ON u.id = s.worker_id
        JOIN bundles b ON b.id = s.bundle_id
        JOIN operations o ON o.id = s.operation_id
        ORDER BY s.id DESC
        LIMIT 30
    """)
    return jsonify([dict(r) for r in rows])

@app.route("/scan", methods=["POST"])
def scan():
    data = request.get_json(silent=True) or request.form.to_dict()
    secret = data.get("device_secret") or request.headers.get("X-Device-Secret")

    if secret != DEVICE_SECRET:
        return jsonify({"ok": False, "error": "Invalid device secret"}), 403

    worker_qr = (data.get("worker_qr") or "").strip()
    bundle_qr = (data.get("bundle_qr") or "").strip()
    operation = (data.get("operation") or "").strip()

    if not (worker_qr and bundle_qr and operation):
        return jsonify({"ok": False, "error": "worker_qr, bundle_qr, operation required"}), 400

    # Worker
    w = query("SELECT id FROM users WHERE worker_code=:code", {"code": worker_qr}, one=True)
    if not w and AUTO_CREATE_UNKNOWN:
        wid = execute(
            "INSERT INTO users(worker_code, name, qr_code) VALUES (:c,:n,:q) RETURNING id",
            {"c": worker_qr, "n": worker_qr, "q": worker_qr},
            expect_id=True
        )
    elif not w:
        return jsonify({"ok": False, "error": f"Unknown worker {worker_qr}"}), 404
    else:
        wid = w["id"]

    # Bundle
    b = query("SELECT id FROM bundles WHERE bundle_code=:code", {"code": bundle_qr}, one=True)
    if not b and AUTO_CREATE_UNKNOWN:
        bid = execute(
            "INSERT INTO bundles(bundle_code, qr_code) VALUES (:c,:q) RETURNING id",
            {"c": bundle_qr, "q": bundle_qr},
            expect_id=True
        )
    elif not b:
        return jsonify({"ok": False, "error": f"Unknown bundle {bundle_qr}"}), 404
    else:
        bid = b["id"]

    # Operation
    o = query("SELECT id FROM operations WHERE op_no=:op", {"op": operation}, one=True)
    if not o and AUTO_CREATE_UNKNOWN:
        oid = execute(
            "INSERT INTO operations(op_no, description, std_min) VALUES (:o,:d,:m) RETURNING id",
            {"o": operation, "d": "AUTO", "m": 0.5},
            expect_id=True
        )
    elif not o:
        return jsonify({"ok": False, "error": f"Unknown operation {operation}"}), 404
    else:
        oid = o["id"]

    execute(
        "INSERT INTO scans(worker_id, bundle_id, operation_id) VALUES (:w,:b,:o)",
        {"w": wid, "b": bid, "o": oid}
    )
    return jsonify({"ok": True})

@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat()}), 200

# ---------------- Main ---------------- #
if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
