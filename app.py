import os
import io
import json
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional
from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.utils import secure_filename
import qrcode
import segno
from sqlalchemy import func
import math

# App configuration
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'production-secret-key-2024')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///production.db')
if app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgres://'):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB

# Initialize extensions
db = SQLAlchemy(app)
CORS(app)

# Ensure directories exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs('static/qrcodes', exist_ok=True)

# ----------------------
# Database Models
# ----------------------
class Worker(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    token_id = db.Column(db.String(50), unique=True, nullable=False)
    department = db.Column(db.String(50), nullable=False)
    line = db.Column(db.String(20), nullable=True)
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
# Utility Functions
# ----------------------
def parse_ob_file(file_path):
    """Parse OB (Operations Breakdown) Excel file"""
    try:
        df = pd.read_excel(file_path)
        operations_data = []

        for _, row in df.iterrows():
            std_min = float(row.get('StdMin', 0) or 0)
            piece_rate = std_min * 0.75  # ₹0.75 per standard minute

            operation_data = {
                'op_no': str(row.get('OpNo', '')),
                'name': str(row.get('Description', '')),
                'machine': str(row.get('Machine', '')),
                'sub_section': str(row.get('SubSection', '')),
                'std_min': std_min,
                'piece_rate': piece_rate,
                'department': str(row.get('SubSection', ''))
            }
            operations_data.append(operation_data)

        return operations_data
    except Exception as e:
        print(f"Error parsing OB file: {str(e)}")
        return []

def parse_production_order_file(file_path):
    """Parse Production Order file"""
    try:
        try:
            df = pd.read_excel(file_path)
        except:
            df = pd.read_csv(file_path)

        production_orders = []
        for _, row in df.iterrows():
            order_data = {
                'order_no': str(row.get('Order No', '') or row.get('order_no', '')),
                'style_number': str(row.get('Style Number', '') or row.get('style_number', '')),
                'style_name': str(row.get('Style Name', '') or row.get('style_name', '')),
                'buyer': str(row.get('Buyer', '') or row.get('buyer', '')),
                'total_quantity': int(row.get('Total Quantity', 0) or row.get('total_quantity', 0))
            }
            if order_data['order_no'] and order_data['total_quantity'] > 0:
                production_orders.append(order_data)

        return production_orders
    except Exception as e:
        print(f"Error parsing Production Order file: {str(e)}")
        return []

def generate_bundles(production_order_id, total_quantity):
    """Generate 12 bundles for a production order"""
    bundles = []
    bundle_qty = math.ceil(total_quantity / 12)

    production_order = ProductionOrder.query.get(production_order_id)
    if not production_order:
        return []

    for i in range(12):
        if i == 11:  # Last bundle
            remaining_qty = total_quantity - (bundle_qty * 11)
            if remaining_qty > 0:
                current_bundle_qty = remaining_qty
            else:
                continue
        else:
            current_bundle_qty = bundle_qty

        bundle = Bundle(
            production_order_id=production_order_id,
            bundle_no=f"{production_order.order_no}-B{i+1:02d}",
            qty_per_bundle=current_bundle_qty,
            assigned_line=f"Line-{(i % 4) + 1}",
            status='pending'
        )
        bundles.append(bundle)

    return bundles

def generate_worker_qr_code(worker_id):
    """Generate QR code for worker"""
    worker = Worker.query.get(worker_id)
    if not worker:
        return None

    qr_data = f"W:{worker.token_id}"
    qr = segno.make(qr_data)

    filename = f"worker_{worker_id}.png"
    filepath = os.path.join('static/qrcodes', filename)
    qr.save(filepath, scale=8)

    return filename

# ----------------------
# Routes
# ----------------------
@app.route('/')
def dashboard():
    """Main dashboard"""
    total_workers = Worker.query.filter_by(status='active').count()
    total_bundles = Bundle.query.count()
    pending_bundles = Bundle.query.filter_by(status='pending').count()
    completed_bundles = Bundle.query.filter_by(status='completed').count()

    recent_logs = db.session.query(WorkerLog, Worker.name).\
        join(Worker).order_by(WorkerLog.timestamp.desc()).limit(10).all()

    return render_template('dashboard.html',
                         total_workers=total_workers,
                         total_bundles=total_bundles,
                         pending_bundles=pending_bundles,
                         completed_bundles=completed_bundles,
                         recent_logs=recent_logs)

@app.route('/workers')
def workers():
    """Workers management page"""
    workers = Worker.query.order_by(Worker.created_at.desc()).all()
    return render_template('workers.html', workers=workers)

@app.route('/production')
def production():
    """Production management page"""
    production_orders = ProductionOrder.query.order_by(ProductionOrder.created_at.desc()).all()
    ob_files = OBFile.query.order_by(OBFile.upload_date.desc()).all()
    return render_template('production.html', 
                         production_orders=production_orders,
                         ob_files=ob_files)

@app.route('/operations')
def operations():
    """Operations management page"""
    operations = Operation.query.order_by(Operation.op_no).all()
    return render_template('operations.html', operations=operations)

@app.route('/bundles')
def bundles():
    """Bundle management page"""
    bundles = db.session.query(Bundle, ProductionOrder.style_number).\
        join(ProductionOrder).order_by(Bundle.created_at.desc()).all()
    workers = Worker.query.filter_by(status='active').all()
    return render_template('bundles.html', bundles=bundles, workers=workers)

@app.route('/reports')
def reports():
    """Reports page"""
    worker_stats = db.session.query(
        Worker.name,
        Worker.department,
        func.sum(WorkerBundle.pieces_completed).label('total_pieces'),
        func.sum(WorkerBundle.earnings).label('total_earnings')
    ).join(WorkerBundle).group_by(Worker.id).all()

    return render_template('reports.html', worker_stats=worker_stats)

# (All your other routes unchanged …)

# ----------------------
# Database Initialization
# ----------------------
def create_tables():
    """Ensure all tables exist at startup"""
    with app.app_context():
        db.create_all()

# Call immediately at import time
create_tables()

# ----------------------
# Run App
# ----------------------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
