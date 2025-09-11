"""Database initialisation and seeding script.

Run this script to create all tables and populate them with initial data.  It
will also generate QR codes for workers and bundles.  The script uses the
Flask application context to ensure proper configuration of SQLAlchemy.

Usage::

    python db_setup.py

Environment variables (via ``config.Config``) control the database URL and
secret key.  This script is idempotent: if data already exists it will
skip seeding.
"""

import os
from flask import Flask
from config import Config
from models import db, User, Bundle, Operation
from qr_utils import make_worker_qr, make_bundle_qr


app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)


def init_db() -> None:
    """Create tables and seed example data if necessary."""

    with app.app_context():
        db.create_all()

        # Seed operations if none exist.  Operations define the available
        # sequence codes that the ESP32 scanner can reference via operation_id.
        if Operation.query.count() == 0:
            ops = [
                Operation(name="Load Sleeve - Jkt", sequence=5001),
                Operation(name="Collar Attach", sequence=5005),
                Operation(name="Front Press", sequence=5077),
            ]
            db.session.add_all(ops)
            db.session.commit()

        # Create workers if table is empty.  These workers come from the
        # screenshots provided and will have token IDs that match the ESP32
        # demo sketch.  After creation, QR codes are generated and the file
        # paths stored.
        if User.query.count() == 0:
            workers = [
                ("Rajesh Kumar", "5001", "SLEEVE"),
                ("Priya Sharma", "5077", "BODY"),
                ("Amit Singh", "5160", "COLLAR"),
                ("Sunita Devi", "5313", "LINING"),
                ("Ravi Patel", "5331", "ASSE-1"),
            ]
            for name, token, dept in workers:
                u = User(name=name, token_id=token, department=dept)
                db.session.add(u)
            db.session.commit()
            # Generate QR codes after persisting to get IDs.
            for u in User.query.all():
                path = make_worker_qr(
                    os.path.join("static", "qrcodes"), u.token_id, f"worker_{u.id}.png"
                )
                u.qr_path = path
            db.session.commit()

        # Create sample bundles if none exist.  Each bundle has an order ID
        # (e.g. the production order), a size range, colour and quantity.  A
        # payload encoding these fields is placed into the QR code so that the
        # ESP32 can decode them.
        if Bundle.query.count() == 0:
            bundles = [
                ("650010011410", "036-050", "BLK3", 50),
                ("650010011410", "036-050", "BLK4", 50),
                ("650010011410", "036-050", "GREN", 44),
            ]
            for order_id, size, color, qty in bundles:
                b = Bundle(order_id=order_id, size=size, color=color, qty=qty)
                db.session.add(b)
            db.session.commit()
            # Generate QR codes after commit to capture IDs.
            for b in Bundle.query.all():
                payload = f"{b.id}|{b.order_id}|{b.size}|{b.color}"
                path = make_bundle_qr(
                    os.path.join("static", "qrcodes"), payload, f"bundle_{b.id}.png"
                )
                b.qr_path = path
            db.session.commit()

        print("Database initialised.")


if __name__ == "__main__":
    init_db()