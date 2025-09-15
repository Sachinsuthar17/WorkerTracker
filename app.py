import os
import logging
from datetime import datetime
from collections import Counter

from flask import Flask, jsonify, render_template, request, send_from_directory, abort
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS

# ------------------------------------------------------------------------------
# Flask setup
# ------------------------------------------------------------------------------
app = Flask(__name__, static_folder="static", template_folder="templates")
CORS(app, resources={r"/api/*": {"origins": "*"}})

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(levelname)s:%(name)s:%(message)s",
)
log = app.logger

# ------------------------------------------------------------------------------
# Database URL (force psycopg v3 driver)
# ------------------------------------------------------------------------------
raw_url = os.getenv("DATABASE_URL", "")
# Render often gives postgres://; SQLAlchemy + psycopg wants postgresql+psycopg://
db_url = raw_url.replace("postgres://", "postgresql+psycopg://")
if db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)

if not db_url:
    db_url = "sqlite:///local.db"  # local dev fallback

app.config.update(
    SQLALCHEMY_DATABASE_URI=db_url,
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    JSON_SORT_KEYS=False,
)

db = SQLAlchemy(app)

# ------------------------------------------------------------------------------
# Models
# ------------------------------------------------------------------------------
class Worker(db.Model):
    __tablename__ = "workers"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    token_id = db.Column(db.String(64), unique=True, nullable=False)
    department = db.Column(db.String(80))
    line = db.Column(db.String(40))
    status = db.Column(db.String(40), default="Active")
    qrcode = db.Column(db.String(255))  # URL/value


class Operation(db.Model):
    __tablename__ = "operations"
    id = db.Column(db.Integer, primary_key=True)
    seq_no = db.Column(db.Integer, nullable=False)
    op_no = db.Column(db.String(40), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    machine = db.Column(db.String(80))
    department = db.Column(db.String(80))
    std_min = db.Column(db.Float, default=0.0)
    piece_rate = db.Column(db.Float, default=0.0)


class Bundle(db.Model):
    __tablename__ = "bundles"
    id = db.Column(db.Integer, primary_key=True)
    bundle_code = db.Column(db.String(32), unique=True, nullable=False)
    qty = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(40), nullable=False, default="pending")
    # Keep nullable=True so older rows/seeds don't fail
    barcode_value = db.Column(db.String(120))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Activity(db.Model):
    __tablename__ = "activities"
    id = db.Column(db.Integer, primary_key=True)
    message = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ------------------------------------------------------------------------------
# Bootstrap (create tables + seed once)
# ------------------------------------------------------------------------------
def seed_once():
    db.create_all()

    if Worker.query.count() == 0:
        db.session.add_all([
            Worker(name="Arun K",  token_id="W001", department="Cutting",    line="L1", status="Active"),
            Worker(name="Priya S", token_id="W002", department="Stitching",  line="L2", status="Idle"),
            Worker(name="Rahul M", token_id="W003", department="Finishing",  line="L3", status="Active"),
        ])

    if Operation.query.count() == 0:
        db.session.add_all([
            Operation(seq_no=10, op_no="OP-101", description="Front stitch",   machine="SNLS", department="Stitching", std_min=1.2, piece_rate=2.5),
            Operation(seq_no=20, op_no="OP-205", description="Sleeve attach",  machine="OL",   department="Stitching", std_min=1.8, piece_rate=3.0),
            Operation(seq_no=30, op_no="OP-310", description="Quality check",  machine="-",    department="QC",        std_min=0.9, piece_rate=1.0),
        ])

    if Bundle.query.count() == 0:
        db.session.add_all([
            Bundle(bundle_code="A12", qty=120, status="pending",     barcode_value="A12-0001"),
            Bundle(bundle_code="B05", qty=80,  status="in_progress", barcode_value="B05-0001"),
            Bundle(bundle_code="C77", qty=60,  status="completed",   barcode_value="C77-0001"),
            Bundle(bundle_code="D15", qty=40,  status="pending",     barcode_value="D15-0001"),
        ])

    if Activity.query.count() == 0:
        db.session.add_all([
            Activity(message="System initialized"),
            Activity(message="Bundles seeded"),
            Activity(message="Workers imported"),
        ])

    db.session.commit()
    log.info(
        "DB ready. Workers=%s, Operations=%s, Bundles=%s",
        Worker.query.count(), Operation.query.count(), Bundle.query.count()
    )


with app.app_context():
    seed_once()

# ------------------------------------------------------------------------------
# Serve HTML (with fallbacks if you kept files at repo root)
# ------------------------------------------------------------------------------
def _exists(path: str) -> bool:
    try:
        return os.path.exists(path)
    except Exception:
        return False

@app.get("/")
def home():
    if _exists(os.path.join(app.template_folder, "index.html")):
        return render_template("index.html")
    if _exists("index.html"):
        return send_from_directory(".", "index.html")
    return abort(404, description="index.html not found. Put it in /templates or project root.")

@app.get("/style.css")
def style_root():
    if _exists(os.path.join(app.static_folder, "style.css")):
        return send_from_directory(app.static_folder, "style.css")
    if _exists("style.css"):
        return send_from_directory(".", "style.css")
    return abort(404)

@app.get("/app.js")
def appjs_root():
    if _exists(os.path.join(app.static_folder, "app.js")):
        return send_from_directory(app.static_folder, "app.js")
    if _exists("app.js"):
        return send_from_directory(".", "app.js")
    return abort(404)

@app.get("/favicon.ico")
def favicon():
    if _exists(os.path.join(app.static_folder, "favicon.ico")):
        return send_from_directory(app.static_folder, "favicon.ico", mimetype="image/vnd.microsoft.icon")
    return abort(404)

# ------------------------------------------------------------------------------
# APIs
# ------------------------------------------------------------------------------
@app.get("/api/stats")
def api_stats():
    workers = Worker.query.count()
    bundles = Bundle.query.count()
    ops = Operation.query.count()
    earnings = round(sum((o.piece_rate or 0) * (o.std_min or 0) for o in Operation.query.all()), 2)
    return jsonify({
        "active_workers": workers,
        "total_bundles": bundles,
        "total_operations": ops,
        "total_earnings": earnings,
        "last_updated": datetime.utcnow().isoformat() + "Z",
    })

@app.get("/api/activities")
def api_activities():
    rows = Activity.query.order_by(Activity.created_at.desc()).limit(20).all()
    return jsonify([{"message": r.message, "created_at": r.created_at.isoformat() + "Z"} for r in rows])

@app.get("/api/bundles")
def api_bundles():
    rows = Bundle.query.order_by(Bundle.created_at.desc()).all()
    return jsonify([
        {
            "bundle_code": r.bundle_code,
            "qty": r.qty,
            "status": r.status,
            "barcode_value": r.barcode_value,
            "created_at": r.created_at.isoformat() + "Z",
        } for r in rows
    ])

@app.get("/api/workers")
def api_workers():
    q = Worker.query
    dept = request.args.get("department")
    status = request.args.get("status")
    search = request.args.get("q")
    if dept:
        q = q.filter(Worker.department == dept)
    if status:
        q = q.filter(Worker.status == status)
    if search:
        like = f"%{search}%"
        q = q.filter(Worker.name.ilike(like))
    rows = q.order_by(Worker.name.asc()).all()
    return jsonify([
        {
            "name": r.name,
            "token_id": r.token_id,
            "department": r.department,
            "line": r.line,
            "status": r.status,
            "qrcode": r.qrcode or r.token_id,
        } for r in rows
    ])

@app.get("/api/operations")
def api_operations():
    rows = Operation.query.order_by(Operation.seq_no.asc()).all()
    return jsonify([
        {
            "seq_no": r.seq_no,
            "op_no": r.op_no,
            "description": r.description,
            "machine": r.machine,
            "department": r.department,
            "std_min": r.std_min,
            "piece_rate": r.piece_rate,
        } for r in rows
    ])

@app.get("/api/chart-data")
def api_chart_data():
    statuses = [b.status for b in Bundle.query.all()]
    status_counts = Counter(statuses)
    status_labels = list(status_counts.keys())
    status_values = [status_counts[k] for k in status_labels]

    depts = [o.department or "Unknown" for o in Operation.query.all()]
    dept_counts = Counter(depts)
    dept_labels = list(dept_counts.keys())
    dept_values = [dept_counts[k] for k in dept_labels]

    return jsonify({
        "bundleStatus": {"labels": status_labels, "values": status_values},
        "departmentWorkload": {"labels": dept_labels, "values": dept_values},
    })

@app.post("/api/scan")
def api_scan():
    data = request.get_json(silent=True) or {}
    barcode = (data.get("barcode") or "").strip()
    if not barcode:
        return jsonify({"error": "barcode is required"}), 400

    code = barcode.split("-")[0]
    bundle = Bundle.query.filter_by(bundle_code=code).first()
    if not bundle:
        return jsonify({"error": f"bundle not found for code '{code}'"}), 404

    prev = bundle.status
    bundle.status = "in_progress" if prev == "pending" else "completed"
    bundle.barcode_value = barcode

    db.session.add(Activity(message=f"Scan {barcode}: {prev} → {bundle.status}"))
    db.session.commit()
    return jsonify({"ok": True, "bundle_code": bundle.bundle_code, "status": bundle.status})

@app.get("/healthz")
def healthz():
    return jsonify({"ok": True})

# ------------------------------------------------------------------------------
# Local dev
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=True)
