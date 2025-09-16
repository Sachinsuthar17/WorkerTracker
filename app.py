import os
import logging
from flask import Flask, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from sqlalchemy import select, func

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("app")

app = Flask(__name__)
CORS(app)

# ---- DB URL (convert to psycopg v3 driver if needed) -------------------------
raw_url = os.getenv(
    "DATABASE_URL",
    # fallback for local dev; Render will provide DATABASE_URL
    "sqlite:///app.db"
)
if raw_url.startswith("postgres://"):
    raw_url = raw_url.replace("postgres://", "postgresql+psycopg://", 1)
elif raw_url.startswith("postgresql://") and "+psycopg" not in raw_url:
    raw_url = raw_url.replace("postgresql://", "postgresql+psycopg://", 1)

app.config.update(
    SQLALCHEMY_DATABASE_URI=raw_url,
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
)

db = SQLAlchemy(app)

# ---- Models ------------------------------------------------------------------
class Worker(db.Model):
    __tablename__ = "workers"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120))
    token_id = db.Column(db.String(120), unique=True, index=True)
    department = db.Column(db.String(120))
    line = db.Column(db.String(120))
    status = db.Column(db.String(50), default="active")
    # Column that caused crashes if missing in DB:
    qrcode = db.Column(db.Text)  # nullable

class Operation(db.Model):
    __tablename__ = "operations"
    id = db.Column(db.Integer, primary_key=True)
    seq_no = db.Column(db.Integer)
    op_no = db.Column(db.String(50))
    description = db.Column(db.Text)
    machine = db.Column(db.String(120))
    department = db.Column(db.String(120))
    std_min = db.Column(db.Float)
    # Column that caused crashes if missing in DB:
    piece_rate = db.Column(db.Numeric(10, 2))  # nullable

# ---- Auto-migration: create tables + add missing columns ---------------------
def auto_migrate():
    with app.app_context():
        # Create tables defined by models (no-op if they already exist)
        db.create_all()

        # Add ONLY the specific missing columns we know about, idempotently
        statements = [
            # workers.qrcode
            """ALTER TABLE workers
               ADD COLUMN IF NOT EXISTS qrcode TEXT""",
            # operations.piece_rate
            """ALTER TABLE operations
               ADD COLUMN IF NOT EXISTS piece_rate NUMERIC(10,2)""",
        ]
        with db.engine.begin() as conn:
            for sql in statements:
                conn.exec_driver_sql(sql)
        log.info("Auto-migration complete (qrcode, piece_rate ensured).")

# ---- Seed minimal data (after migration). Uses SA 2.0 count to avoid crashes -
def seed_once():
    with app.app_context():
        try:
            w_count = db.session.execute(select(func.count()).select_from(Worker)).scalar()
            if w_count == 0:
                db.session.add(Worker(
                    name="Demo Worker", token_id="DEMO-1",
                    department="General", line="A", status="active"
                ))
                db.session.commit()
                log.info("Seeded workers")

            o_count = db.session.execute(select(func.count()).select_from(Operation)).scalar()
            if o_count == 0:
                db.session.add(Operation(
                    seq_no=1, op_no="OP-001", description="Demo Operation",
                    machine="M-1", department="General", std_min=1.0, piece_rate=0
                ))
                db.session.commit()
                log.info("Seeded operations")
        except Exception as e:
            log.warning("Seeding skipped due to error: %s", e)

# ---- Routes ------------------------------------------------------------------
@app.route("/healthz")
def healthz():
    return jsonify({"ok": True})

@app.route("/")
def root():
    static_dir = os.path.join(os.getcwd(), "static")
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return send_from_directory(static_dir, "index.html")
    return jsonify({"message": "API is running"})

# ---- Boot order: migrate FIRST, then seed -----------------------------------
with app.app_context():
    auto_migrate()
    seed_once()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
