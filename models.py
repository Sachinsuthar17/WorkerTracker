"""Database models for the Garment ERP system.

The models are defined using SQLAlchemy and cover workers (users), bundles,
operations, scans, and task assignments.  Relationships are kept simple to
allow easy querying and reporting.  Timestamps default to UTC via
``datetime.utcnow`` for consistency.
"""

from datetime import datetime
from flask_sqlalchemy import SQLAlchemy


# Create a global SQLAlchemy object.  The app will configure and initialise
# this instance in ``app.py`` or ``db_setup.py``.  Defining it here allows
# other modules to import ``db`` without creating circular dependencies.
db = SQLAlchemy()


class User(db.Model):
    """Represents a worker in the factory.

    Each user has a unique ``token_id`` which is encoded into a QR code.  The
    ``department`` field groups workers by functional area (e.g. SLEEVE,
    BODY).  ``qr_path`` stores the path to the generated QR image for
    convenience when rendering templates.
    """

    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    token_id = db.Column(db.String(120), unique=True, nullable=False)
    department = db.Column(db.String(120), nullable=True)
    qr_path = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # One-to-many relationships
    scans = db.relationship("Scan", backref="worker", lazy=True)
    tasks = db.relationship("Task", backref="worker", lazy=True)


class Bundle(db.Model):
    """Represents a bundle or batch of garments.

    Bundles are associated with a production order (``order_id``) and have
    additional attributes like size, colour, and quantity.  A QR code is
    generated for each bundle and stored at ``qr_path``.
    """

    __tablename__ = "bundles"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.String(120), nullable=False)
    size = db.Column(db.String(50), nullable=True)
    color = db.Column(db.String(50), nullable=True)
    qty = db.Column(db.Integer, nullable=False, default=0)
    qr_path = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    scans = db.relationship("Scan", backref="bundle", lazy=True)
    tasks = db.relationship("Task", backref="bundle", lazy=True)


class Operation(db.Model):
    """Defines a sewing or production operation.

    The ``sequence`` field is used to order operations and map them to real
    machine codes.  Scans reference an ``operation_id`` so that we know
    which step of the process was performed.
    """

    __tablename__ = "operations"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    sequence = db.Column(db.Integer, nullable=False, default=0)

    scans = db.relationship("Scan", backref="operation", lazy=True)


class Scan(db.Model):
    """Captures a scan event from the shop floor.

    Each scan records which worker scanned which bundle for which operation
    along with a timestamp.  This table grows over time and forms the basis
    for reporting and performance analysis.
    """

    __tablename__ = "scans"
    id = db.Column(db.Integer, primary_key=True)
    worker_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    bundle_id = db.Column(db.Integer, db.ForeignKey("bundles.id"), nullable=False)
    operation_id = db.Column(
        db.Integer, db.ForeignKey("operations.id"), nullable=False
    )
    timestamp = db.Column(
        db.DateTime, default=datetime.utcnow, index=True, nullable=False
    )


class Task(db.Model):
    """Represents the assignment of a bundle to a worker.

    The ``status`` field allows simple workflow tracking (e.g. assigned,
    in_progress, done).  ``assigned_at`` records when the task was
    created.  A worker may have multiple tasks across different bundles.
    """

    __tablename__ = "tasks"
    id = db.Column(db.Integer, primary_key=True)
    worker_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    bundle_id = db.Column(db.Integer, db.ForeignKey("bundles.id"), nullable=False)
    assigned_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(30), default="assigned")