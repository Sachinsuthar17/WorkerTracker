import os
from datetime import datetime, time
from flask import Flask, jsonify, request, render_template, Response
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
import io, csv

# ---------------- App & DB config ----------------
app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev")

db_url = os.getenv("DATABASE_URL", "sqlite:///garment.db")
# Normalize legacy scheme and force psycopg driver for SQLAlchemy if using Postgres
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
if db_url.startswith("postgresql://") and "+psycopg" not in db_url:
    db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["DEVICE_SECRET"] = os.getenv("DEVICE_SECRET", "garment_erp_2024_secret")
app.config["RATE_PER_PIECE"] = float(os.getenv("RATE_PER_PIECE", "25"))

db = SQLAlchemy(app)
migrate = Migrate(app, db)

# ---------------- Models ----------------
class Setting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    base_rate_per_min = db.Column(db.Float, default=0.5)
    efficiency_target = db.Column(db.Float, default=100)
    quality_target = db.Column(db.Float, default=95)

class Worker(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    worker_id = db.Column(db.String(32), unique=True, index=True)
    name = db.Column(db.String(120), nullable=False)
    department = db.Column(db.String(120))
    skill = db.Column(db.String(32))
    rate = db.Column(db.Float, default=25.0)
    line = db.Column(db.String(64))
    token_id = db.Column(db.String(120), unique=True, index=True)
    is_logged_in = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Operation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(32), unique=True, index=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)

class ProductionOrder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_no = db.Column(db.String(64), unique=True, index=True)
    style = db.Column(db.String(120))
    buyer = db.Column(db.String(120))
    quantity = db.Column(db.Integer)
    delivery_date = db.Column(db.Date)

class Bundle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(64), unique=True, index=True)
    production_order_id = db.Column(db.Integer, db.ForeignKey("production_order.id"))
    color = db.Column(db.String(32))
    size_range = db.Column(db.String(64))
    quantity = db.Column(db.Integer, default=0)
    current_operation = db.Column(db.String(32))
    status = db.Column(db.String(32), default="CREATED")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ScanLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    token_id = db.Column(db.String(120), index=True)
    scan_type = db.Column(db.String(32))  # login/logout/work/bundle
    bundle_code = db.Column(db.String(64))
    operation_code = db.Column(db.String(32))
    scanned_at = db.Column(db.DateTime, default=datetime.utcnow)

class ProductionLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    worker_id = db.Column(db.Integer, db.ForeignKey("worker.id"))
    operation_id = db.Column(db.Integer, db.ForeignKey("operation.id"))
    bundle_id = db.Column(db.Integer, db.ForeignKey("bundle.id"))
    quantity = db.Column(db.Integer, default=1)
    status = db.Column(db.String(32), default="COMPLETED")
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# ---------------- Page routes ----------------
@app.route("/")
def dashboard():
    return render_template("dashboard.html")

@app.route("/workers")
def workers_lines():
    return render_template("workers.html")

@app.route("/settings")
def settings():
    return render_template("settings.html")

@app.route("/reports")
def reports():
    return render_template("reports.html")

@app.route("/ob")
def ob_management():
    return render_template("ob.html")

@app.route("/orders")
def production_orders():
    return render_template("orders.html")

@app.route("/bundles")
def bundle_management():
    return render_template("bundles.html")

@app.route("/live")
def live_scanning():
    return render_template("live.html")

# ---------------- ESP32 scan endpoint ----------------
@app.post("/api/scan")
def api_scan():
    data = request.get_json(silent=True) or {}
    token_id = (data.get("token_id") or "").strip()
    secret = (data.get("secret") or "").strip()
    scan_type = (data.get("scan_type") or "work").strip()
    bundle_code = (data.get("bundle_code") or "").strip()
    operation_code = (data.get("operation_code") or "").strip()

    if not token_id:
        return jsonify({"status": "error", "message": "token_id missing"}), 400
    if secret != app.config["DEVICE_SECRET"]:
        return jsonify({"status": "error", "message": "unauthorized"}), 401

    w = Worker.query.filter((Worker.token_id == token_id) | (Worker.worker_id == token_id)).first()
    if not w:
        return jsonify({"status": "error", "message": "unknown worker"}), 404

    if scan_type == "login":
        w.is_logged_in = True
    elif scan_type == "logout":
        w.is_logged_in = False

    db.session.add(
        ScanLog(
            token_id=token_id,
            scan_type=scan_type,
            bundle_code=bundle_code or None,
            operation_code=operation_code or None,
        )
    )
    if scan_type == "work":
        op = Operation.query.filter_by(code=operation_code).first()
        db.session.add(
            ProductionLog(
                worker_id=w.id,
                operation_id=op.id if op else None,
                quantity=1,
                status="COMPLETED",
            )
        )

    db.session.commit()

    # compute scans_today for this worker
    today = datetime.utcnow().date()
    start = datetime.combine(today, time.min)
    end = datetime.combine(today, time.max)
    scans_today = (
        ScanLog.query.filter(
            ScanLog.token_id == token_id,
            ScanLog.scan_type == "work",
            ScanLog.scanned_at >= start,
            ScanLog.scanned_at <= end,
        ).count()
    )
    earnings_inr = scans_today * app.config["RATE_PER_PIECE"]

    return jsonify(
        {
            "status": "success",
            "name": w.name,
            "department": w.department or "",
            "scans_today": scans_today,
            "earnings": round(earnings_inr / 83.0, 2),  # ESP32 display logic
        }
    )

# ---------------- JSON APIs for SPA ----------------
@app.get("/api/stats")
def api_stats():
    workers = Worker.query.count()
    bundles = Bundle.query.count()
    orders = ProductionOrder.query.count()
    today = datetime.utcnow().date()
    start = datetime.combine(today, time.min)
    end = datetime.combine(today, time.max)
    scans_today = (
        ScanLog.query.filter(
            ScanLog.scan_type == "work",
            ScanLog.scanned_at >= start,
            ScanLog.scanned_at <= end,
        ).count()
    )
    earnings_today = scans_today * app.config["RATE_PER_PIECE"]
    logged_in = Worker.query.filter_by(is_logged_in=True).count()
    return jsonify(
        {
            "workers": workers,
            "bundles": bundles,
            "orders": orders,
            "scans_today": scans_today,
            "estimated_earnings_today_total": earnings_today,
            "active_workers": logged_in,
        }
    )

@app.get("/api/activities")
def api_activities():
    items = (
        db.session.query(ScanLog, Worker)
        .join(Worker, ScanLog.token_id == Worker.token_id, isouter=True)
        .order_by(ScanLog.scanned_at.desc())
        .limit(50)
        .all()
    )
    return jsonify(
        [
            {
                "token_id": s.token_id,
                "scan_type": s.scan_type,
                "bundle_code": s.bundle_code,
                "operation_code": s.operation_code,
                "scanned_at": s.scanned_at.isoformat(),
                "worker_name": w.name if w else None,
                "department": w.department if w else None,
            }
            for s, w in items
        ]
    )

@app.get("/api/workers")
def api_workers():
    ws = Worker.query.order_by(Worker.created_at.desc()).all()
    return jsonify(
        [
            {
                "id": w.id,
                "worker_id": w.worker_id,
                "name": w.name,
                "department": w.department,
                "skill": w.skill,
                "rate": w.rate,
                "line": w.line,
                "token_id": w.token_id,
                "is_logged_in": w.is_logged_in,
                "created_at": w.created_at.isoformat() if w.created_at else None,
            }
            for w in ws
        ]
    )

@app.post("/add_worker")
def add_worker():
    name = request.form.get("name", "").strip()
    department = request.form.get("department", "").strip()
    token_id = request.form.get("token_id", "").strip()
    rate = float(request.form.get("rate", "25") or 25)
    worker_id = request.form.get("worker_id", "").strip() or None
    w = Worker(
        name=name,
        department=department,
        token_id=token_id,
        rate=rate,
        worker_id=worker_id,
    )
    db.session.add(w)
    db.session.commit()
    return ("", 204)

@app.get("/api/operations")
def api_operations():
    ops = Operation.query.order_by(Operation.name).all()
    return jsonify(
        [{"id": o.id, "code": o.code, "name": o.name, "description": o.description} for o in ops]
    )

@app.post("/add_operation")
def add_operation():
    code = request.form.get("code", "").strip() or None
    name = request.form.get("name", "").strip()
    desc = request.form.get("description", "").strip()
    db.session.add(Operation(code=code, name=name, description=desc))
    db.session.commit()
    return ("", 204)

@app.get("/api/production")
def api_production():
    rows = (
        db.session.query(ProductionLog, Worker, Operation)
        .join(Worker, ProductionLog.worker_id == Worker.id, isouter=True)
        .join(Operation, ProductionLog.operation_id == Operation.id, isouter=True)
        .order_by(ProductionLog.timestamp.desc())
        .limit(200)
        .all()
    )
    return jsonify(
        [
            {
                "id": p.id,
                "timestamp": p.timestamp.isoformat(),
                "quantity": p.quantity,
                "status": p.status,
                "worker_name": w.name if w else None,
                "operation_name": o.name if o else None,
            }
            for p, w, o in rows
        ]
    )

@app.post("/add_production")
def add_production():
    worker_id = int(request.form.get("worker_id"))
    operation_id = int(request.form.get("operation_id"))
    qty = int(request.form.get("quantity", "1"))
    db.session.add(ProductionLog(worker_id=worker_id, operation_id=operation_id, quantity=qty))
    db.session.commit()
    return ("", 204)

# ---------------- CSV exports ----------------
@app.get("/api/export/workers.csv")
def export_workers():
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["ID", "WorkerID", "Name", "Department", "Rate", "Line", "Token", "Created"])
    for x in Worker.query.order_by(Worker.name).all():
        w.writerow([x.id, x.worker_id, x.name, x.department, x.rate, x.line, x.token_id, x.created_at])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment;filename=workers.csv"})

@app.get("/api/export/scans.csv")
def export_scans():
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["ID", "Token", "Type", "Bundle", "Operation", "Time"])
    for s in ScanLog.query.order_by(ScanLog.scanned_at.desc()).all():
        w.writerow([s.id, s.token_id, s.scan_type, s.bundle_code, s.operation_code, s.scanned_at])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment;filename=scans.csv"})

@app.get("/api/export/production.csv")
def export_production():
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["ID", "WorkerID", "OperationID", "Quantity", "Status", "Timestamp"])
    for p in ProductionLog.query.order_by(ProductionLog.timestamp.desc()).all():
        w.writerow([p.id, p.worker_id, p.operation_id, p.quantity, p.status, p.timestamp])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment;filename=production.csv"})

# ---------------- One-time DB bootstrap (Flask 3.x safe) ----------------
_initialized = False
@app.before_request
def _init_once():
    global _initialized
    if _initialized:
        return
    with app.app_context():
        db.create_all()
        if not Setting.query.first():
            db.session.add(Setting()); db.session.commit()
        if not Worker.query.first():
            db.session.add(Worker(name="Rajesh Kumar", department="SLEEVE", token_id="5001"))
            db.session.add(Worker(name="Priya Sharma", department="BODY", token_id="5077"))
            db.session.commit()
        if not Operation.query.first():
            db.session.add(Operation(code="5001", name="Loading Sleeve - Jkt"))
            db.session.add(Operation(code="5077", name="Sew Dart Front Plain2 - Jkt"))
            db.session.commit()
    _initialized = True

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
