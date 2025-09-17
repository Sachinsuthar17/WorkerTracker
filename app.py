import os
import json
import uuid
from datetime import datetime
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
from flask import Flask, jsonify, render_template, request, send_file, flash, redirect, url_for
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
from werkzeug.utils import secure_filename
import openpyxl

# Try to import QR code and Pillow
try:
    import qrcode
    import io
    import base64
    from PIL import Image
    QR_AVAILABLE = True
except ImportError:
    QR_AVAILABLE = False
    print("QR code or Pillow libraries not available - some features disabled")

# -----------------------------
# Flask Setup
# -----------------------------
app = Flask(__name__, static_folder="static", template_folder="templates")
CORS(app)
app.secret_key = os.urandom(24)  # For flash messages

# File upload configuration
UPLOAD_FOLDER = 'uploads'
QR_FOLDER = 'static/qrcodes'
ALLOWED_EXTENSIONS = {'xlsx', 'xls', 'pdf'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB limit

# Create directories if they don't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(QR_FOLDER, exist_ok=True)

# -----------------------------
# Database Configuration
# -----------------------------
def _normalize_db_url(raw: str) -> str:
    """Make DATABASE_URL friendly for psycopg2"""
    if not raw:
        return ""
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://"):]
    p = urlparse(raw)
    scheme = "postgresql"
    q = dict(parse_qsl(p.query or "", keep_blank_values=True))
    q["sslmode"] = (q.get("sslmode") or "require").strip().strip('"').strip("'")
    return urlunparse(
        (scheme, p.netloc, p.path, p.params, urlencode(q, doseq=True), p.fragment)
    )

RAW_DB_URL = os.getenv("DATABASE_URL", "")
DB_URL = _normalize_db_url(RAW_DB_URL)

def get_conn():
    if not DB_URL:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)

# -----------------------------
# Database Initialization
# -----------------------------
def init_db():
    """Initialize all database tables"""
    with get_conn() as conn, conn.cursor() as cur:
        # Workers table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS workers (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                token_id VARCHAR(50) UNIQUE NOT NULL,
                department VARCHAR(50) NOT NULL,
                line VARCHAR(20),
                status VARCHAR(20) DEFAULT 'Active',
                qr_code TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        
        # Operations table
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
        
        # Bundles table
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
        
        # Production orders table
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
        
        # File uploads table
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
        
        # Scans table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS scans (
                id SERIAL PRIMARY KEY,
                code TEXT NOT NULL,
                worker_id INTEGER REFERENCES workers(id),
                bundle_id INTEGER REFERENCES bundles(id),
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        
        # Production logs table
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
        print("✅ Database tables initialized successfully!")

# -----------------------------
# Helper Functions
# -----------------------------
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def generate_qr_code(data):
    """Generate QR code as base64 string"""
    if not QR_AVAILABLE:
        return None
    try:
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        qr_base64 = base64.b64encode(buffer.getvalue()).decode()
        return f"data:image/png;base64,{qr_base64}"
    except Exception as e:
        print(f"QR code generation error: {e}")
        return None

def seed_sample_data():
    """Add sample data if tables are empty"""
    with get_conn() as conn, conn.cursor() as cur:
        try:
            # Workers sample data
            cur.execute("SELECT COUNT(*) FROM workers")
            if cur.fetchone()[0] == 0:
                print("📝 Adding sample workers...")
                sample_workers = [
                    ('John Doe', 'W001', 'Cutting', 'L1'),
                    ('Jane Smith', 'W002', 'Sewing', 'L2'),
                    ('Mike Johnson', 'W003', 'Finishing', 'L3')
                ]
                for name, token_id, dept, line in sample_workers:
                    qr_code = generate_qr_code(token_id)
                    cur.execute(
                        "INSERT INTO workers (name, token_id, department, line, qr_code) VALUES (%s, %s, %s, %s, %s)",
                        (name, token_id, dept, line, qr_code)
                    )

            # Operations sample data
            cur.execute("SELECT COUNT(*) FROM operations")
            if cur.fetchone()[0] == 0:
                print("📝 Adding sample operations...")
                sample_operations = [
                    (1, 'OP001', 'Fabric Cutting', 'Cutting Machine', 'Cutting', 15.5, 25.00),
                    (2, 'OP002', 'Sleeve Attach', 'Overlock', 'Sewing', 12.3, 20.00)
                ]
                for seq, op_no, desc, machine, dept, std_min, piece_rate in sample_operations:
                    cur.execute(
                        "INSERT INTO operations (seq_no, op_no, description, machine, department, std_min, piece_rate) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (seq, op_no, desc, machine, dept, std_min, piece_rate)
                    )

            # Bundles sample data
            cur.execute("SELECT COUNT(*) FROM bundles")
            if cur.fetchone()[0] == 0:
                print("📝 Adding sample bundles...")
                sample_bundles = [
                    ('B001', '650010011410', 'SAINTX MENS BLAZER', 'Navy', 'M', 50, 'In Progress'),
                    ('B002', '650010011410', 'SAINTX MENS BLAZER', 'Navy', 'L', 60, 'Completed')
                ]
                for bundle_no, order_no, style, color, size, qty, status in sample_bundles:
                    cur.execute(
                        "INSERT INTO bundles (bundle_no, order_no, style, color, size, quantity, status) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (bundle_no, order_no, style, color, size, qty, status)
                    )

            # Production orders sample data
            cur.execute("SELECT COUNT(*) FROM production_orders")
            if cur.fetchone()[0] == 0:
                print("📝 Adding sample production order...")
                cur.execute(
                    "INSERT INTO production_orders (order_no, style, quantity, buyer) VALUES (%s, %s, %s, %s)",
                    ('650010011410', 'SAINTX MENS BLAZER', 1119, 'BANSWARA GARMENTS A UNIT OF BANSWAR')
                )

            conn.commit()
            print("✅ Sample data seeded successfully!")
        except Exception as e:
            print(f"Sample data seeding error: {e}")
            conn.rollback()

# -----------------------------
# Routes
# -----------------------------
@app.route('/')
def index():
    return render_template('index.html')

@app.route("/health")
def health():
    return "OK", 200

@app.route("/api/dashboard-stats")
def dashboard_stats():
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM workers WHERE status = 'Active'")
            active_workers = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM bundles")
            total_bundles = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM operations")
            total_operations = cur.fetchone()[0] or 0
            cur.execute("SELECT COALESCE(SUM(piece_rate * 5), 0) FROM operations WHERE piece_rate IS NOT NULL")
            total_earnings = float(cur.fetchone()[0] or 0)
            return jsonify({
                "activeWorkers": active_workers,
                "totalBundles": total_bundles,
                "totalOperations": total_operations,
                "totalEarnings": total_earnings
            })
    except Exception as e:
        print(f"Dashboard stats error: {e}")
        return jsonify({
            "activeWorkers": 0,
            "totalBundles": 0,
            "totalOperations": 0,
            "totalEarnings": 0
        })

@app.route("/api/chart-data")
def chart_data():
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT status, COUNT(*) FROM bundles GROUP BY status")
            bundle_status = dict(cur.fetchall())
            cur.execute("SELECT department, COUNT(*) FROM workers GROUP BY department")
            department_data = dict(cur.fetchall())
            return jsonify({
                "bundleStatus": bundle_status,
                "departmentWorkload": department_data
            })
    except Exception as e:
        print(f"Chart data error: {e}")
        return jsonify({
            "bundleStatus": {"Pending": 2, "In Progress": 2, "Completed": 1},
            "departmentWorkload": {"Cutting": 1, "Sewing": 2, "Finishing": 1, "Quality": 1, "Packing": 1}
        })

@app.route("/api/recent-activity")
def recent_activity():
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT 'Scan' as type, s.code as description, s.created_at
                FROM scans s
                ORDER BY s.created_at DESC
                LIMIT 10
            """)
            activities = cur.fetchall()
            return jsonify([dict(activity) for activity in activities])
    except Exception as e:
        print(f"Recent activity error: {e}")
        return jsonify([])

@app.route("/api/workers")
def get_workers():
    try:
        search = request.args.get('search', '')
        department = request.args.get('department', '')
        status = request.args.get('status', '')
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
            workers = cur.fetchall()
            return jsonify([dict(worker) for worker in workers])
    except Exception as e:
        print(f"Workers API error: {e}")
        return jsonify([])

@app.route("/api/operations")
def get_operations():
    try:
        search = request.args.get('search', '')
        with get_conn() as conn, conn.cursor() as cur:
            query = "SELECT * FROM operations WHERE 1=1"
            params = []
            if search:
                query += " AND (description ILIKE %s OR op_no ILIKE %s)"
                params.extend([f"%{search}%", f"%{search}%"])
            query += " ORDER BY seq_no"
            cur.execute(query, params)
            operations = cur.fetchall()
            return jsonify([dict(op) for op in operations])
    except Exception as e:
        print(f"Operations API error: {e}")
        return jsonify([])

@app.route("/api/bundles")
def get_bundles():
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM bundles ORDER BY created_at DESC")
            bundles = cur.fetchall()
            return jsonify([dict(bundle) for bundle in bundles])
    except Exception as e:
        print(f"Bundles API error: {e}")
        return jsonify([])

@app.route("/api/production-order")
def get_production_order():
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM production_orders ORDER BY created_at DESC LIMIT 1")
            order = cur.fetchone()
            return jsonify(dict(order) if order else {})
    except Exception as e:
        print(f"Production order API error: {e}")
        return jsonify({})

@app.route("/api/upload", methods=["POST"])
def upload_file():
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file uploaded"}), 400
        file = request.files['file']
        file_type = request.form.get('type', 'unknown')
        if file.filename == '':
            return jsonify({"error": "No file selected"}), 400
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            unique_filename = f"{uuid.uuid4()}_{filename}"
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
            file.save(file_path)
            with get_conn() as conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO file_uploads (filename, original_filename, file_type, file_path) VALUES (%s, %s, %s, %s) RETURNING id",
                    (unique_filename, filename, file_type, file_path)
                )
                file_id = cur.fetchone()[0]
                conn.commit()
            return jsonify({
                "success": True,
                "file_id": file_id,
                "filename": filename,
                "message": "File uploaded successfully"
            })
        return jsonify({"error": "Invalid file type"}), 400
    except Exception as e:
        print(f"File upload error: {e}")
        return jsonify({"error": "Upload failed"}), 500

@app.route("/api/scan", methods=["POST"])
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
            return jsonify({
                "ok": True,
                "id": row["id"],
                "created_at": row["created_at"]
            })
    except Exception as e:
        print(f"Scan API error: {e}")
        return jsonify({"error": "Scan failed"}), 500

@app.route("/api/scans")
def list_scans():
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT id, code, created_at FROM scans ORDER BY id DESC LIMIT 100")
            rows = cur.fetchall()
            return jsonify([dict(row) for row in rows])
    except Exception as e:
        print(f"Scans list error: {e}")
        return jsonify([])

@app.route("/api/reports/production")
def production_report():
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT
                    w.name as worker_name,
                    o.description as operation_desc,
                    COUNT(pl.id) as completed_operations,
                    SUM(pl.quantity) as total_quantity
                FROM production_logs pl
                JOIN workers w ON pl.worker_id = w.id
                JOIN operations o ON pl.operation_id = o.id
                WHERE pl.status = 'Completed'
                GROUP BY w.name, o.description
                ORDER BY total_quantity DESC NULLS LAST
                LIMIT 10
            """)
            data = cur.fetchall()
            return jsonify([dict(row) for row in data])
    except Exception as e:
        print(f"Production report error: {e}")
        return jsonify([])

# -----------------------------
# New Worker Routes
# -----------------------------
@app.route('/add_worker', methods=['GET', 'POST'])
def add_worker():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        token_id = request.form.get('token_id', '').strip()
        department = request.form.get('department', '').strip()
        line = request.form.get('line', '').strip()
        active = int(request.form.get('active', '1'))

        if not token_id:
            flash('Token ID is required.', 'error')
            return redirect(url_for('workers'))

        try:
            with get_conn() as conn, conn.cursor() as cur:
                # Check duplicate
                cur.execute("SELECT 1 FROM workers WHERE token_id = %s", (token_id,))
                if cur.fetchone():
                    flash('Duplicate Token ID not allowed.', 'error')
                    return redirect(url_for('workers'))

                # Generate QR codes
                qr_svg_path, qr_png_path = generate_and_save_qr_codes(token_id)

                cur.execute(
                    "INSERT INTO workers (name, token_id, department, line, active, qr_svg, qr_png, created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())",
                    (name, token_id, department, line, active, qr_svg_path, qr_png_path)
                )
                conn.commit()

            flash('Worker added successfully!', 'success')
            return redirect(url_for('workers'))
        except Exception as e:
            print(f"Error adding worker: {e}")
            flash('Server error. Please try again.', 'error')
            return redirect(url_for('workers'))
    return render_template('add_worker.html')

@app.route('/edit_worker/<int:worker_id>', methods=['GET', 'POST'])
def edit_worker(worker_id):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM workers WHERE id = %s", (worker_id,))
        worker = cur.fetchone()
        if not worker:
            flash('Worker not found.', 'error')
            return redirect(url_for('workers'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        department = request.form.get('department', '').strip()
        line = request.form.get('line', '').strip()
        active = int(request.form.get('active', '1'))

        try:
            with get_conn() as conn, conn.cursor() as cur:
                cur.execute(
                    "UPDATE workers SET name = %s, department = %s, line = %s, active = %s, updated_at = NOW() WHERE id = %s",
                    (name, department, line, active, worker_id)
                )
                conn.commit()
            flash('Worker updated successfully!', 'success')
            return redirect(url_for('workers'))
        except Exception as e:
            print(f"Error editing worker: {e}")
            flash('Server error. Please try again.', 'error')
            return redirect(url_for('workers'))

    return render_template('edit_worker.html', worker=worker)

@app.route('/delete_worker/<int:worker_id>', methods=['POST'])
def delete_worker(worker_id):
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT qr_svg, qr_png FROM workers WHERE id = %s", (worker_id,))
            worker = cur.fetchone()
            if not worker:
                flash('Worker not found.', 'error')
                return redirect(url_for('workers'))

            # Delete QR files
            for path in [worker['qr_svg'], worker['qr_png']]:
                if path and os.path.exists(path):
                    os.remove(path)

            cur.execute("DELETE FROM workers WHERE id = %s", (worker_id,))
            conn.commit()

        flash('Worker deleted successfully!', 'success')
        return redirect(url_for('workers'))
    except Exception as e:
        print(f"Error deleting worker: {e}")
        flash('Server error. Please try again.', 'error')
        return redirect(url_for('workers'))

@app.route('/download_qr/<int:worker_id>')
def download_qr(worker_id):
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT qr_png FROM workers WHERE id = %s", (worker_id,))
            worker = cur.fetchone()
            if not worker or not worker['qr_png']:
                flash('QR code not found.', 'error')
                return redirect(url_for('workers'))

            return send_file(worker['qr_png'], as_attachment=True, download_name=f"qr_{worker_id}.png")
    except Exception as e:
        print(f"Error downloading QR: {e}")
        flash('Error downloading QR code.', 'error')
        return redirect(url_for('workers'))

@app.route('/upload_workers', methods=['POST'])
def upload_workers():
    if 'file' not in request.files:
        flash('No file uploaded.', 'error')
        return redirect(url_for('workers'))

    file = request.files['file']
    if file.filename == '':
        flash('No file selected.', 'error')
        return redirect(url_for('workers'))

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)

        added = 0
        skipped = 0
        invalid = 0
        skipped_tokens = []

        try:
            wb = openpyxl.load_workbook(file_path)
            ws = wb.active

            # Assume first row is header
            header = [cell.value.lower() if cell.value else '' for cell in ws[1]]

            required_columns = ['name', 'token_id', 'department', 'line', 'active']
            col_indices = {col: header.index(col) for col in required_columns if col in header}

            if len(col_indices) != len(required_columns):
                flash('Excel missing required columns.', 'error')
                return redirect(url_for('workers'))

            with get_conn() as conn, conn.cursor() as cur:
                for row in ws.iter_rows(min_row=2, values_only=True):
                    try:
                        name = row[col_indices['name']]
                        token_id = row[col_indices['token_id']]
                        department = row[col_indices['department']]
                        line = row[col_indices['line']]
                        active = 1 if row[col_indices['active']] else 0

                        if not token_id:
                            invalid += 1
                            continue

                        cur.execute("SELECT 1 FROM workers WHERE token_id = %s", (token_id,))
                        if cur.fetchone():
                            skipped += 1
                            skipped_tokens.append(token_id)
                            continue

                        qr_svg_path, qr_png_path = generate_and_save_qr_codes(token_id)

                        cur.execute(
                            "INSERT INTO workers (name, token_id, department, line, active, qr_svg, qr_png, created_at, updated_at) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())",
                            (name, token_id, department, line, active, qr_svg_path, qr_png_path)
                        )

                        added += 1
                    except Exception as e:
                        print(f"Error processing row: {e}")
                        invalid += 1

                conn.commit()

            os.remove(file_path)  # Clean up uploaded file

            summary = f"Added: {added}, Skipped (duplicates): {skipped}, Invalid: {invalid}"
            if skipped_tokens:
                summary += f" Skipped tokens: {', '.join(skipped_tokens[:10])}"
            flash(summary, 'success')
            return redirect(url_for('workers'))

        except Exception as e:
            print(f"Excel processing error: {e}")
            flash('Error processing Excel file.', 'error')
            return redirect(url_for('workers'))

    flash('Invalid file type.', 'error')
    return redirect(url_for('workers'))

# QR Generation Helper
def generate_and_save_qr_codes(token_id):
    import datetime
    now_str = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    svg_filename = f'qrcode_{token_id}_{now_str}.svg'
    png_filename = f'qrcode_{token_id}_{now_str}.png'
    svg_path = os.path.join(QR_FOLDER, svg_filename)
    png_path = os.path.join(QR_FOLDER, png_filename)

    # Generate SVG
    factory = qrcode.image.svg.SvgImage
    img = qrcode.make(token_id, image_factory=factory)
    img.save(svg_path)

    # Generate PNG
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(token_id)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img.save(png_path)

    return svg_filename, png_filename  # Return relative paths for DB

# -----------------------------
# Startup
# -----------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    print("🚀 Starting Production Management System...")
    try:
        init_db()
        seed_sample_data()
        print("✅ Database initialization completed!")
    except Exception as e:
        print(f"❌ Database initialization failed: {e}")
    app.run(host="0.0.0.0", port=port, debug=True)
else:
    # On render with gunicorn
    try:
        init_db()
        seed_sample_data()
        print("✅ Database initialization completed!")
    except Exception as e:
        print(f"❌ DB init skipped: {e}")
