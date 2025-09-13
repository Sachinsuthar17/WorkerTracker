from . import db
from sqlalchemy import func
from datetime import datetime

class Worker(db.Model):
    __tablename__ = "workers"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    token_id = db.Column(db.String, unique=True, nullable=False, index=True)
    department = db.Column(db.String, nullable=False)
    qrcode_path = db.Column(db.String)
    created_at = db.Column(db.DateTime, default=func.now())
    is_logged_in = db.Column(db.Boolean, default=False)
    last_scanner_id = db.Column(db.String)

class Log(db.Model):
    __tablename__ = "logs"
    id = db.Column(db.Integer, primary_key=True)
    worker_id = db.Column(db.Integer, db.ForeignKey("workers.id"), nullable=True)
    token_id = db.Column(db.String, index=True)
    action = db.Column(db.String)  # login/logout/error/scan
    scanner_id = db.Column(db.String)
    timestamp = db.Column(db.DateTime, default=func.now())
    metadata = db.Column(db.JSON)

class ProductionOrder(db.Model):
    __tablename__ = "production_orders"
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String, index=True)
    brand = db.Column(db.String)
    total_pieces = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=func.now())
    raw_upload_reference = db.Column(db.String)

class Bundle(db.Model):
    __tablename__ = "bundles"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("production_orders.id"))
    bundle_number = db.Column(db.Integer)  # 1..12
    pieces_assigned = db.Column(db.Integer, default=0)
    pieces_completed = db.Column(db.Integer, default=0)

class BundleOperation(db.Model):
    __tablename__ = "bundle_operations"
    id = db.Column(db.Integer, primary_key=True)
    bundle_id = db.Column(db.Integer, db.ForeignKey("bundles.id"))
    operation_name = db.Column(db.String)
    rate_per_piece = db.Column(db.Float, default=0.0)

class Assignment(db.Model):
    __tablename__ = "assignments"
    id = db.Column(db.Integer, primary_key=True)
    worker_id = db.Column(db.Integer, db.ForeignKey("workers.id"))
    bundle_id = db.Column(db.Integer, db.ForeignKey("bundles.id"))
    assigned_at = db.Column(db.DateTime, default=func.now())
    completed_at = db.Column(db.DateTime, nullable=True)
