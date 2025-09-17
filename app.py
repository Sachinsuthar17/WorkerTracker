import os
import uuid
import base64
import io
from datetime import datetime
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

from flask import (
    Flask, jsonify, render_template, render_template_string,
    request, send_file, flash, redirect, url_for
)
from flask_cors import CORS
from werkzeug.utils import secure_filename

import psycopg2
from psycopg2.extras import RealDictCursor

import openpyxl

# QR code (PNG via Pillow)
try:
    import qrcode
    from PIL import Image  # noqa: F401  (required by qrcode[pil])
    QR_AVAILABLE = True
except Exception:
    QR_AVAILABLE = False

# -----------------------------
# Flask Setup
# -----------------------------
app = Flask(__name__, static_folder="static", template_folder="templates")
CORS(app)
app.secret_key = os.urandom(24)  # For flash messages

# File uploads (ephemeral on Render unless you mount a Disk)
UPLOAD_FOLDER = os.environ.get("UPLOAD_DIR", "uploads")
ALLOWED_EXTENSIONS = {"xlsx", "xls", "pdf"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5MB
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# -----------------------------
# Database Configuration
# -----------------------------
def _normalize_db_url(raw: str) -> str:
    """Normalize DATABASE_URL for psycopg2 & force SSL."""
    if not raw:
        return ""
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://"):]
    p = urlparse(raw)
    scheme = "postgresql"
    q = dict(parse_qsl(p.query or "", keep_blank_values=True))
    q["sslmode"] = (q.get("sslmode") or "require").strip().strip('"').strip("'")
    return urlunparse((scheme, p.netloc, p.path, p.params, urlencode(q, doseq=True), p.fragment))

RAW_DB_URL = os.getenv("DATABASE_URL", "")
DB_URL = _normalize_db_url(RAW_DB_URL)

def get_conn():
    if not DB_URL:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)

# -----------------------------
# Helpers
# -----------------------------
def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def generate_qr_base64(data: str) -> str | None:
    """Return a data: URI (PNG in base64) for a QR of `data`."""
    if not QR_AVAILABLE:
        return None
    try:
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        return f"data:image/png;base64,{b64}"
    except Exception as e:
        app.logger.exception("QR code generation error")
        return None

def data_uri_png_to_bytes(data_uri: str) -> bytes:
    """Convert data:image/png;base64,... to raw PNG bytes."""
    prefix = "data:image/png;base64,"
    if data_uri.startswith(prefix):
        return base64.b64decode(data_uri[len(prefix):])
    # Fallback: try to split by first comma
    if "," in data_uri:
        return base64.b64decode(data_uri.split(",", 1)[1])
    return base64.b64decode(data_uri)

# -----------------------------
# Database Initialization
# -----------------------------
def init_db():
    """Create tables if not exist (aligned to the code below)."""
    with get_conn() as conn, conn.cursor() as cur:
        # Workers
        cur.execute("""
            CREATE TABLE IF NOT EXISTS workers (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                token_id VARCHAR(50) UNIQUE NOT NULL,
                department VARCHAR(50) NOT NULL,
                line VARCHAR(20),
                status VARCHAR(20) DEFAULT 'Active',  -- Active / Inactive
                qr_code TEXT,                         -- data:image/png;base64,...
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)

        # Operations
        cur.execute("""
            CREATE TABLE IF NOT EXISTS operations (
                id SERIAL PRIMARY KEY,
                seq_no INTEGER,
                op_no VARCHAR(20) NOT NULL,
                description TEXT NOT NULL,
                machine VARCHAR(50),
                department VARCHAR(50),
                std_min DECIMAL(5,2),
                piece_rate DECIMAL(8,2),
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)

        # Bundles
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bundles (
                id SERIAL PRIMARY KEY,
                bundle_no VARCHAR(50) UNIQUE NOT NULL,
                order_no VARCHAR(50),
                style VARCHAR(100),
                color VARCHAR(50),
                size VARCHAR(20),
                quantity INTEGER,
                status VARCHAR(20) DEFAULT 'Pending',
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)

        # Production orders
        cur.execute("""
            CREATE TABLE IF NOT EXISTS production_orders (
                id SERIAL PRIMARY KEY,
                order_no VARCHAR(50) UNIQUE NOT NULL,
                style VARCHAR(200),
                quantity INTEGER,
                buyer VARCHAR(200),
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)

        # File uploads (metadata only)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS file_uploads (
                id SERIAL PRIMARY KEY,
                filename VARCHAR(200) NOT NULL,
                original_filename VARCHAR(200) NOT NULL,
                file_type VARCHAR(20) NOT NULL,
                file_path VARCHAR(500) NOT NULL,
                uploaded_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)

        # Scans
        cur.execute("""
            CREATE TABLE IF NOT EXISTS scans (
                id SERIAL PRIMARY KEY,
                code TEXT NOT NULL,
                worker_id INTEGER REFERENCES workers(id),
                bundle_id INTEGER REFERENCES bundles(id),
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)

        # Production logs
        cur.execute("""
            CREATE TABLE IF NOT EXISTS production_logs (
                id SERIAL PRIMARY KEY,
                worker_id INTEGER REFERENCES workers(id),
                operation_id INTEGER REFERENCES operations(id),
                bundle_id INTEGER REFERENCES bundles(id),
                quantity INTEGER,
                start_time TIMESTAMPTZ,
                end_time TIMESTAMPTZ,
                status VARCHAR(20) DEFAULT 'In Progress',
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)

        conn.commit()
        app.logger.info("✅ Database tables initialized successfully!")

def seed_sample_data():
    """Seed minimal sample rows if tables are empty."""
    with get_conn() as conn, conn.cursor() as cur:
        try:
            # Workers
            cur.execute("SELECT COUNT(*) AS count FROM workers;")
            if (cur.fetchone()["count"] or 0) == 0:
                app.logger.info("📝 Adding sample workers...")
                for name, token_id, dept, line in [
                    ("John Doe",  "W001", "Cutting",   "L1"),
                    ("Jane Smith","W002", "Sewing",    "L2"),
                    ("Mike Johnson","W003","Finishing","L3"),
                ]:
                    qr = generate_qr_base64(token_id)
                    cur.execute(
                        """
                        INSERT INTO workers (name, token_id, department, line, status, qr_code)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (name, token_id, dept, line, "Active", qr)
                    )

            # Operations
            cur.execute("SELECT COUNT(*) AS count FROM operations;")
            if (cur.fetchone()["count"] or 0) == 0:
                app.logger.info("📝 Adding sample operations...")
                for seq, op_no, desc, machine, dept, std_min, piece_rate in [
                    (1, "OP001", "Fabric Cutting", "Cutting Machine", "Cutting", 15.5, 25.00),
                    (2, "OP002", "Sleeve Attach",  "Overlock",        "Sewing",  12.3, 20.00),
                ]:
                    cur.execute(
                        """
                        INSERT INTO operations (seq_no, op_no, description, machine, department, std_min, piece_rate)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (seq, op_no, desc, machine, dept, std_min, piece_rate)
                    )

            # Bundles
            cur.execute("SELECT COUNT(*) AS count FROM bundles;")
            if (cur.fetchone()["count"] or 0) == 0:
                app.logger.info("📝 Adding sample bundles...")
                for bundle_no, order_no, style, color, size, qty, status in [
                    ("B001", "650010011410", "SAINTX MENS BLAZER", "Navy", "M", 50, "In Progress"),
                    ("B002", "650010011410", "SAINTX MENS BLAZER", "Navy", "L", 60, "Completed"),
                ]:
                    cur.execute(
                        """
                        INSERT INTO bundles (bundle_no, order_no, style, color, size, quantity, status)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (bundle_no, order_no, style, color, size, qty, status)
                    )

            # Production order
            cur.execute("SELECT COUNT(*) AS count FROM production_orders;")
            if (cur.fetchone()["count"] or 0) == 0:
                app.logger.info("📝 Adding sample production order...")
                cur.execute(
                    """
                    INSERT INTO production_orders (order_no, style, quantity, buyer)
                    VALUES (%s, %s, %s, %s)
                    """,
                    ("650010011410", "SAINTX MENS BLAZER", 1119, "BANSWARA GARMENTS A UNIT OF BANSWAR")
                )

            conn.commit()
            app.logger.info("✅ Sample data seeded successfully!")
        except Exception:
            conn.rollback()
            app.logger.exception("Sample data seeding error")

# -----------------------------
# Routes (UI)
# -----------------------------
@app.get("/")
def index():
    # Try template; if not present, serve a minimal page so you don’t crash
    tpl = os.path.join(app.template_folder or "", "index.html")
    if os.path.exists(tpl):
        return render_template("index.html")
    return render_template_string("""
        <html><head><title>Production Management</title></head>
        <body style="font-family: system-ui, sans-serif; padding: 24px;">
            <h1>Production Management</h1>
            <p>Backend is running. Add your frontend at <code>templates/index.html</code>.</p>
            <ul>
                <li><a href="/health">/health</a></li>
                <li><a href="/api/dashboard-stats">/api/dashboard-stats</a></li>
                <li><a href="/api/chart-data">/api/chart-data</a></li>
                <li><a href="/api/bundles">/api/bundles</a></li>
                <li><a href="/api/workers">/api/workers</a></li>
                <li><a href="/api/operations">/api/operations</a></li>
                <li><a href="/api/production-order">/api/production-order</a></li>
                <li><a href="/api/scans">/api/scans</a></li>
            </ul>
        </body></html>
    """)

@app.get("/health")
def health():
    return "OK", 200

# -----------------------------
# Routes (APIs)
# -----------------------------
@app.get("/api/dashboard-stats")
def dashboard_stats():
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS count FROM workers WHERE status = 'Active'")
            active_workers = cur.fetchone()["count"] or 0

            cur.execute("SELECT COUNT(*) AS count FROM bundles")
            total_bundles = cur.fetchone()["count"] or 0

            cur.execute("SELECT COUNT(*) AS count FROM operations")
            total_operations = cur.fetchone()["count"] or 0

            cur.execute("SELECT COALESCE(SUM(piece_rate * 5), 0) AS total FROM operations WHERE piece_rate IS NOT NULL")
            total_earnings = float(cur.fetchone()["total"] or 0.0)

            return jsonify({
                "activeWorkers": active_workers,
                "totalBundles": total_bundles,
                "totalOperations": total_operations,
                "totalEarnings": total_earnings
            })
    except Exception:
        app.logger.exception("Dashboard stats error")
        return jsonify({"activeWorkers": 0, "totalBundles": 0, "totalOperations": 0, "totalEarnings": 0})

@app.get("/api/chart-data")
def chart_data():
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT status, COUNT(*) AS count FROM bundles GROUP BY status")
            bundle_rows = cur.fetchall()
            bundle_status = {row["status"]: row["count"] for row in bundle_rows}

            cur.execute("SELECT department, COUNT(*) AS count FROM workers GROUP BY department")
            dept_rows = cur.fetchall()
            department_data = {row["department"]: row["count"] for row in dept_rows}

            return jsonify({"bundleStatus": bundle_status, "departmentWorkload": department_data})
    except Exception:
        app.logger.exception("Chart data error")
        # Fallback demo data
        return jsonify({
            "bundleStatus": {"Pending": 2, "In Progress": 2, "Completed": 1},
            "departmentWorkload": {"Cutting": 1, "Sewing": 2, "Finishing": 1, "Quality": 1, "Packing": 1}
        })

@app.get("/api/recent-activity")
def recent_activity():
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT 'Scan' AS type, s.code AS description, s.created_at
                FROM scans s
                ORDER BY s.created_at DESC
                LIMIT 10
            """)
            activities = cur.fetchall()
            return jsonify([dict(row) for row in activities])
    except Exception:
        app.logger.exception("Recent activity error")
        return jsonify([])

@app.get("/api/workers")
def get_workers():
    try:
        search = request.args.get("search", "")
        department = request.args.get("department", "")
        status = request.args.get("status", "")
        with get_conn() as conn, conn.cursor() as cur:
            query = "SELECT * FROM workers WHERE 1=1"
            params = []
            if search:
                query += " AND (name ILIKE %s OR token_id ILIKE %s)"
                params.extend([f"%{search}%", f"%{search}%"])
            if department:
                query += " AND department = %s"
                params.append(department)
            if status:
                query += " AND status = %s"
                params.append(status)
            query += " ORDER BY created_at DESC"
            cur.execute(query, params)
            rows = cur.fetchall()
            return jsonify([dict(r) for r in rows])
    except Exception:
        app.logger.exception("Workers API error")
        return jsonify([])

@app.get("/api/operations")
def get_operations():
    try:
        search = request.args.get("search", "")
        with get_conn() as conn, conn.cursor() as cur:
            query = "SELECT * FROM operations WHERE 1=1"
            params = []
            if search:
                query += " AND (description ILIKE %s OR op_no ILIKE %s)"
                params.extend([f"%{search}%", f"%{search}%"])
            query += " ORDER BY seq_no NULLS LAST, id"
            cur.execute(query, params)
            rows = cur.fetchall()
            return jsonify([dict(r) for r in rows])
    except Exception:
        app.logger.exception("Operations API error")
        return jsonify([])

@app.get("/api/bundles")
def get_bundles():
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM bundles ORDER BY created_at DESC")
            rows = cur.fetchall()
            return jsonify([dict(r) for r in rows])
    except Exception:
        app.logger.exception("Bundles API error")
        return jsonify([])

@app.get("/api/production-order")
def get_production_order():
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM production_orders ORDER BY created_at DESC LIMIT 1")
            row = cur.fetchone()
            return jsonify(dict(row) if row else {})
    except Exception:
        app.logger.exception("Production order API error")
        return jsonify({})

@app.post("/api/upload")
def upload_file():
    try:
        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400
        f = request.files["file"]
        file_type = request.form.get("type", "unknown")
        if not f.filename:
            return jsonify({"error": "No file selected"}), 400
        if f and allowed_file(f.filename):
            filename = secure_filename(f.filename)
            unique = f"{uuid.uuid4()}_{filename}"
            path = os.path.join(app.config["UPLOAD_FOLDER"], unique)
            f.save(path)
            with get_conn() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO file_uploads (filename, original_filename, file_type, file_path)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                    """,
                    (unique, filename, file_type, path)
                )
                file_id = cur.fetchone()["id"]
                conn.commit()
            return jsonify({"success": True, "file_id": file_id, "filename": filename, "message": "File uploaded successfully"})
        return jsonify({"error": "Invalid file type"}), 400
    except Exception:
        app.logger.exception("File upload error")
        return jsonify({"error": "Upload failed"}), 500

@app.post("/api/scan")
def api_scan():
    try:
        payload = request.get_json(silent=True) or {}
        code = (payload.get("code") or "").strip()
        if not code:
            return jsonify({"error": "code is required"}), 400
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO scans (code) VALUES (%s) RETURNING id, created_at", (code,))
            row = cur.fetchone()
            conn.commit()
            return jsonify({"ok": True, "id": row["id"], "created_at": row["created_at"]})
    except Exception:
        app.logger.exception("Scan API error")
        return jsonify({"error": "Scan failed"}), 500

@app.get("/api/scans")
def list_scans():
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT id, code, created_at FROM scans ORDER BY id DESC LIMIT 100")
            rows = cur.fetchall()
            return jsonify([dict(r) for r in rows])
    except Exception:
        app.logger.exception("Scans list error")
        return jsonify([])

@app.get("/api/reports/production")
def production_report():
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT
                    w.name AS worker_name,
                    o.description AS operation_desc,
                    COUNT(pl.id) AS completed_operations,
                    SUM(pl.quantity) AS total_quantity
                FROM production_logs pl
                JOIN workers w ON pl.worker_id = w.id
                JOIN operations o ON pl.operation_id = o.id
                WHERE pl.status = 'Completed'
                GROUP BY w.name, o.description
                ORDER BY total_quantity DESC NULLS LAST
                LIMIT 10
            """)
            rows = cur.fetchall()
            return jsonify([dict(r) for r in rows])
    except Exception:
        app.logger.exception("Production report error")
        return jsonify([])

# -----------------------------
# Simple Worker management (forms)
# -----------------------------
@app.get("/workers")
def workers_page():
    # Minimal page so redirects don’t crash even without templates
    return render_template_string("""
        <h2>Workers</h2>
        <p>Upload via Excel or add manually.</p>
        <form action="{{ url_for('upload_workers') }}" method="post" enctype="multipart/form-data">
            <input type="file" name="file" />
            <button type="submit">Upload Excel</button>
        </form>
        <form action="{{ url_for('add_worker') }}" method="post" style="margin-top:1rem;">
            <input name="name" placeholder="Name" required />
            <input name="token_id" placeholder="Token ID" required />
            <input name="department" placeholder="Department" required />
            <input name="line" placeholder="Line" />
            <select name="status">
                <option value="Active" selected>Active</option>
                <option value="Inactive">Inactive</option>
            </select>
            <button type="submit">Add Worker</button>
        </form>
        <p><a href="/">Back</a></p>
    """)

@app.route("/add_worker", methods=["GET", "POST"])
def add_worker():
    if request.method == "GET":
        return redirect(url_for("workers_page"))

    name = request.form.get("name", "").strip()
    token_id = request.form.get("token_id", "").strip()
    department = request.form.get("department", "").strip()
    line = request.form.get("line", "").strip()
    status = request.form.get("status", "Active").strip() or "Active"

    if not token_id:
        flash("Token ID is required.", "error")
        return redirect(url_for("workers_page"))
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM workers WHERE token_id = %s", (token_id,))
            if cur.fetchone():
                flash("Duplicate Token ID not allowed.", "error")
                return redirect(url_for("workers_page"))

            qr = generate_qr_base64(token_id)
            cur.execute(
                """
                INSERT INTO workers (name, token_id, department, line, status, qr_code)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (name, token_id, department, line, status, qr)
            )
            conn.commit()
        flash("Worker added successfully!", "success")
        return redirect(url_for("workers_page"))
    except Exception:
        app.logger.exception("Error adding worker")
        flash("Server error. Please try again.", "error")
        return redirect(url_for("workers_page"))

@app.route("/edit_worker/<int:worker_id>", methods=["GET", "POST"])
def edit_worker(worker_id: int):
    if request.method == "GET":
        # In a real UI, render a form; here we just redirect to the list.
        return redirect(url_for("workers_page"))

    name = request.form.get("name", "").strip()
    department = request.form.get("department", "").strip()
    line = request.form.get("line", "").strip()
    status = request.form.get("status", "Active").strip() or "Active"

    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE workers SET name=%s, department=%s, line=%s, status=%s WHERE id=%s",
                (name, department, line, status, worker_id)
            )
            conn.commit()
        flash("Worker updated successfully!", "success")
        return redirect(url_for("workers_page"))
    except Exception:
        app.logger.exception("Error editing worker")
        flash("Server error. Please try again.", "error")
        return redirect(url_for("workers_page"))

@app.post("/delete_worker/<int:worker_id>")
def delete_worker(worker_id: int):
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM workers WHERE id = %s", (worker_id,))
            conn.commit()
        flash("Worker deleted successfully!", "success")
        return redirect(url_for("workers_page"))
    except Exception:
        app.logger.exception("Error deleting worker")
        flash("Server error. Please try again.", "error")
        return redirect(url_for("workers_page"))

@app.get("/download_qr/<int:worker_id>")
def download_qr(worker_id: int):
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT qr_code FROM workers WHERE id = %s", (worker_id,))
            row = cur.fetchone()
        if not row or not row.get("qr_code"):
            flash("QR code not found.", "error")
            return redirect(url_for("workers_page"))

        png_bytes = data_uri_png_to_bytes(row["qr_code"])
        return send_file(
            io.BytesIO(png_bytes),
            mimetype="image/png",
            as_attachment=True,
            download_name=f"qr_{worker_id}.png"
        )
    except Exception:
        app.logger.exception("Error downloading QR")
        flash("Error downloading QR code.", "error")
        return redirect(url_for("workers_page"))

@app.post("/upload_workers")
def upload_workers():
    if "file" not in request.files:
        flash("No file uploaded.", "error")
        return redirect(url_for("workers_page"))

    f = request.files["file"]
    if not f.filename:
        flash("No file selected.", "error")
        return redirect(url_for("workers_page"))

    if not allowed_file(f.filename):
        flash("Invalid file type.", "error")
        return redirect(url_for("workers_page"))

    filename = secure_filename(f.filename)
    path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    f.save(path)

    added = skipped = invalid = 0
    skipped_tokens: list[str] = []

    try:
        wb = openpyxl.load_workbook(path)
        ws = wb.active

        # Headers (first row)
        header = [str(c.value).strip().lower() if c.value is not None else "" for c in ws[1]]
        # Support either 'status' OR legacy 'active'
        required = ["name", "token_id", "department", "line"]
        missing = [col for col in required if col not in header]
        if missing:
            flash(f"Excel missing required columns: {', '.join(missing)}", "error")
            return redirect(url_for("workers_page"))

        idx = {col: header.index(col) for col in header}
        has_status = "status" in header
        has_active = "active" in header

        with get_conn() as conn, conn.cursor() as cur:
            for row in ws.iter_rows(min_row=2, values_only=True):
                try:
                    name = (row[idx["name"]] if "name" in idx else "") or ""
                    token_id = (row[idx["token_id"]] if "token_id" in idx else "") or ""
                    department = (row[idx["department"]] if "department" in idx else "") or ""
                    line = (row[idx["line"]] if "line" in idx else "") or ""

                    if not token_id:
                        invalid += 1
                        continue

                    cur.execute("SELECT 1 FROM workers WHERE token_id = %s", (token_id,))
                    if cur.fetchone():
                        skipped += 1
                        skipped_tokens.append(token_id)
                        continue

                    # Determine status
                    status = "Active"
                    if has_status:
                        cell = row[idx["status"]]
                        status = (str(cell).strip().title() if cell else "Active")
                        if status not in ("Active", "Inactive"):
                            status = "Active"
                    elif has_active:
                        cell = row[idx["active"]]
                        status = "Active" if bool(cell) else "Inactive"

                    qr = generate_qr_base64(token_id)
                    cur.execute(
                        """
                        INSERT INTO workers (name, token_id, department, line, status, qr_code)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (name, token_id, department, line, status, qr)
                    )
                    added += 1
                except Exception:
                    app.logger.exception("Error processing upload row")
                    invalid += 1

            conn.commit()

        try:
            os.remove(path)
        except Exception:
            pass

        summary = f"Added: {added}, Skipped (duplicates): {skipped}, Invalid: {invalid}"
        if skipped_tokens:
            summary += f" | Skipped tokens (first 10): {', '.join(skipped_tokens[:10])}"
        flash(summary, "success")
        return redirect(url_for("workers_page"))
    except Exception:
        app.logger.exception("Excel processing error")
        flash("Error processing Excel file.", "error")
        return redirect(url_for("workers_page"))

# -----------------------------
# Startup
# -----------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.logger.info("🚀 Starting Production Management System...")
    try:
        init_db()
        seed_sample_data()
        app.logger.info("✅ Database initialization completed!")
    except Exception:
        app.logger.exception("❌ Database initialization failed")
    app.run(host="0.0.0.0", port=port, debug=True)
else:
    try:
        init_db()
        seed_sample_data()
        app.logger.info("✅ Database initialization completed!")
    except Exception:
        app.logger.exception("❌ DB init skipped")
