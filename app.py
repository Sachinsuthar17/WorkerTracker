import os
import math
import pandas as pd
from datetime import datetime
from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.utils import secure_filename
from sqlalchemy import func, case
import segno

# ----------------------
# App Configuration
# ----------------------
app = Flask(__name__, template_folder="templates", static_folder="static")

# Secret key for sessions/flash
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'production-secret-key-2024')

# Database connection (Render Postgres or fallback SQLite)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///production.db')
if app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgres://'):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB

db = SQLAlchemy(app)
CORS(app)

# Ensure directories exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.join(app.static_folder, 'qrcodes'), exist_ok=True)

# ----------------------
# Database Models
# ----------------------
class Worker(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    token_id = db.Column(db.String(50), unique=True, nullable=False)
    department = db.Column(db.String(50), nullable=False)
    line = db.Column(db.String(20))
    status = db.Column(db.String(20), default='active')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    worker_bundles = db.relationship('WorkerBundle', backref='worker', lazy=True)
    logs = db.relationship('WorkerLog', backref='worker', lazy=True)

class Operation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    op_no = db.Column(db.String(10), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    machine = db.Column(db.String(100))
    sub_section = db.Column(db.String(100))
    std_min = db.Column(db.Float, default=0.0)
    piece_rate = db.Column(db.Float, default=0.0)
    department = db.Column(db.String(50))
    skill_level = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ProductionOrder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_no = db.Column(db.String(50), unique=True, nullable=False)
    style_number = db.Column(db.String(100), nullable=False)
    style_name = db.Column(db.String(200))
    buyer = db.Column(db.String(100))
    total_quantity = db.Column(db.Integer, nullable=False)
    order_date = db.Column(db.DateTime, default=datetime.utcnow)
    delivery_date = db.Column(db.DateTime)
    status = db.Column(db.String(20), default='active')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    bundles = db.relationship('Bundle', backref='production_order', lazy=True)

class OBFile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    file_name = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255))
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)
    parsed_data = db.Column(db.Text)
    total_operations = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default='processed')

class Bundle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    production_order_id = db.Column(db.Integer, db.ForeignKey('production_order.id'), nullable=False)
    bundle_no = db.Column(db.String(50), nullable=False)
    size = db.Column(db.String(10))
    color = db.Column(db.String(50))
    qty_per_bundle = db.Column(db.Integer, nullable=False)
    assigned_line = db.Column(db.String(20))
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    worker_bundles = db.relationship('WorkerBundle', backref='bundle', lazy=True)

class WorkerBundle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    worker_id = db.Column(db.Integer, db.ForeignKey('worker.id'), nullable=False)
    bundle_id = db.Column(db.Integer, db.ForeignKey('bundle.id'), nullable=False)
    operation_id = db.Column(db.Integer, db.ForeignKey('operation.id'), nullable=False)
    pieces_completed = db.Column(db.Integer, default=0)
    earnings = db.Column(db.Float, default=0.0)
    assigned_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)
    status = db.Column(db.String(20), default='assigned')

    operation = db.relationship('Operation', backref='worker_bundles')

class WorkerLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    worker_id = db.Column(db.Integer, db.ForeignKey('worker.id'), nullable=False)
    action_type = db.Column(db.String(50), nullable=False)
    details = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# ----------------------
# Jinja helpers
# ----------------------
@app.template_filter('inr')
def inr(value):
    try:
        return f"₹{float(value):.2f}"
    except Exception:
        return "₹0.00"

@app.context_processor
def inject_now():
    return {"now": datetime.utcnow()}

# ----------------------
# Parsers (unchanged)
# ----------------------
def parse_ob_file(file_path):
    try:
        df = pd.read_excel(file_path)
        operations_data = []
        for _, row in df.iterrows():
            std_min = float(row.get('StdMin', 0) or 0)
            piece_rate = std_min * 0.75  # ₹0.75 per std minute
            operations_data.append({
                'op_no': str(row.get('OpNo', '')),
                'name': str(row.get('Description', '')),
                'machine': str(row.get('Machine', '')),
                'sub_section': str(row.get('SubSection', '')),
                'std_min': std_min,
                'piece_rate': piece_rate,
                'department': str(row.get('SubSection', ''))
            })
        return operations_data
    except Exception as e:
        print(f"Error parsing OB file: {e}")
        return []

def parse_production_order_file(file_path):
    try:
        try:
            df = pd.read_excel(file_path)
        except Exception:
            df = pd.read_csv(file_path)
        orders = []
        for _, row in df.iterrows():
            order_data = {
                'order_no': str(row.get('Order No', '') or row.get('order_no', '')),
                'style_number': str(row.get('Style Number', '') or row.get('style_number', '')),
                'style_name': str(row.get('Style Name', '') or row.get('style_name', '')),
                'buyer': str(row.get('Buyer', '') or row.get('buyer', '')),
                'total_quantity': int(row.get('Total Quantity', 0) or row.get('total_quantity', 0))
            }
            if order_data['order_no'] and order_data['total_quantity'] > 0:
                orders.append(order_data)
        return orders
    except Exception as e:
        print(f"Error parsing Production Order file: {e}")
        return []

def generate_bundles(production_order_id, total_quantity):
    bundles = []
    bundle_qty = math.ceil(total_quantity / 12)
    order = ProductionOrder.query.get(production_order_id)
    if not order:
        return []
    for i in range(12):
        if i == 11:
            remaining_qty = total_quantity - (bundle_qty * 11)
            if remaining_qty <= 0:
                continue
            current_qty = remaining_qty
        else:
            current_qty = bundle_qty
        bundles.append(Bundle(
            production_order_id=production_order_id,
            bundle_no=f"{order.order_no}-B{i+1:02d}",
            qty_per_bundle=current_qty,
            assigned_line=f"Line-{(i % 4) + 1}",
            status='pending'
        ))
    return bundles

def generate_worker_qr_code(worker_id):
    worker = Worker.query.get(worker_id)
    if not worker:
        return None
    qr_data = f"W:{worker.token_id}"
    qr = segno.make(qr_data)
    filename = f"worker_{worker_id}.png"
    filepath = os.path.join(app.static_folder, 'qrcodes', filename)
    qr.save(filepath, scale=8)
    return filename

# ----------------------
# Data helpers used by UI
# ----------------------
def bundle_progress_map():
    """returns dict {bundle_id: {'completed': int, 'earnings': float}}"""
    rows = (
        db.session.query(
            WorkerBundle.bundle_id,
            func.coalesce(func.sum(WorkerBundle.pieces_completed), 0).label("completed"),
            func.coalesce(func.sum(WorkerBundle.earnings), 0.0).label("earnings"),
        )
        .group_by(WorkerBundle.bundle_id)
        .all()
    )
    return {r.bundle_id: {"completed": int(r.completed or 0), "earnings": float(r.earnings or 0)} for r in rows}

# ----------------------
# Routes
# ----------------------
@app.route('/')
def dashboard():
    total_workers = Worker.query.filter_by(status='active').count()
    total_bundles = Bundle.query.count()
    operations_count = Operation.query.count()

    # Totals
    total_earnings = db.session.query(func.coalesce(func.sum(WorkerBundle.earnings), 0.0)).scalar() or 0.0

    # Department workload (counts of operations per department)
    dept_rows = (
        db.session.query(Operation.department, func.count(Operation.id))
        .group_by(Operation.department)
        .all()
    )
    dept_labels = [d[0] or "—" for d in dept_rows]
    dept_counts = [int(d[1]) for d in dept_rows]

    # Recent logs
    recent_logs = (
        db.session.query(WorkerLog, Worker.name)
        .join(Worker)
        .order_by(WorkerLog.timestamp.desc())
        .limit(4)
        .all()
    )

    # Bundle status buckets for donut
    status_rows = (
        db.session.query(Bundle.status, func.count(Bundle.id))
        .group_by(Bundle.status)
        .all()
    )
    donut = {k or "pending": int(v) for k, v in status_rows}

    return render_template(
        'dashboard.html',
        active='dashboard',
        total_workers=total_workers,
        total_bundles=total_bundles,
        operations_count=operations_count,
        total_earnings=total_earnings,
        dept_labels=dept_labels,
        dept_counts=dept_counts,
        donut=donut,
        recent_logs=recent_logs,
    )

@app.route('/workers')
def workers():
    workers = Worker.query.order_by(Worker.created_at.desc()).all()
    return render_template('workers.html', active='workers', workers=workers)

@app.route('/production')
def production():
    orders = ProductionOrder.query.order_by(ProductionOrder.created_at.desc()).all()
    return render_template('production.html', active='production', orders=orders)

@app.route('/operations')
def operations():
    operations = Operation.query.order_by(Operation.op_no).all()
    return render_template('operations.html', active='operations', operations=operations)

@app.route('/bundles')
def bundles():
    # Join to order to show style number, and compute progress/earnings
    bundle_rows = (
        db.session.query(Bundle, ProductionOrder.style_number)
        .join(ProductionOrder, Bundle.production_order_id == ProductionOrder.id)
        .order_by(Bundle.created_at.desc())
        .all()
    )
    prog_map = bundle_progress_map()
    # Decorate rows for the template
    view = []
    for b, style in bundle_rows:
        comp = prog_map.get(b.id, {"completed": 0, "earnings": 0.0})
        completed = comp["completed"]
        pct = 0
        if b.qty_per_bundle and b.qty_per_bundle > 0:
            pct = min(100, int(round(100 * completed / b.qty_per_bundle)))
        view.append({
            "id": b.id,
            "bundle_no": b.bundle_no,
            "status": b.status,
            "color": b.color or "-",
            "qty": b.qty_per_bundle,
            "line": b.assigned_line or "-",
            "completed_str": f"{completed}/{b.qty_per_bundle}",
            "pct": pct,
            "earnings": comp["earnings"],
            "style": style or "",
        })
    return render_template('bundles.html', active='bundles', bundles=view)

@app.route('/reports')
def reports():
    stats = (
        db.session.query(
            Worker.name.label('name'),
            func.coalesce(func.sum(WorkerBundle.pieces_completed), 0).label('total_pieces'),
            func.coalesce(func.sum(WorkerBundle.earnings), 0.0).label('total_earnings'),
        )
        .join(WorkerBundle, Worker.id == WorkerBundle.worker_id)
        .group_by(Worker.id)
        .order_by(Worker.name.asc())
        .all()
    )

    # Bar chart labels and values (completion % approximated out of 100)
    labels = [s.name for s in stats]
    # If you have a max target per worker, replace 100 with that target.
    bars = [min(100, int(round((s.total_pieces or 0)))) for s in stats]

    return render_template(
        'reports.html',
        active='reports',
        worker_stats=stats,
        labels=labels,
        bars=bars
    )

# ----------------------
# Init DB
# ----------------------
def create_tables():
    with app.app_context():
        db.create_all()

create_tables()

# ----------------------
# Run App
# ----------------------
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
