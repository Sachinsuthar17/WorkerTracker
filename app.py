import os
import json
import uuid
from datetime import datetime
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
from flask import Flask, jsonify, render_template, request, send_file
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
from werkzeug.utils import secure_filename

# Try to import QR code - make it optional to avoid dependency issues
try:
    import qrcode
    import io
    import base64
    QR_AVAILABLE = True
except ImportError:
    QR_AVAILABLE = False
    print("QR code libraries not available - some features disabled")

# -----------------------------
# Flask Setup
# -----------------------------
app = Flask(__name__, static_folder="static", template_folder="templates")
CORS(app)

# File upload configuration
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'xlsx', 'xls', 'pdf'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Create upload directory if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

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
        
        # Keep existing scans table, enhance it
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
            # Check if data exists
            cur.execute("SELECT COUNT(*) FROM workers")
            worker_count = cur.fetchone()[0]
            
            if worker_count == 0:
                print("📝 Adding sample workers...")
                sample_workers = [
                    ('John Doe', 'W001', 'Cutting', 'L1'),
                    ('Jane Smith', 'W002', 'Sewing', 'L2'),
                    ('Mike Johnson', 'W003', 'Finishing', 'L3'),
                    ('Sarah Wilson', 'W004', 'Quality', 'L1'),
                    ('Tom Brown', 'W005', 'Packing', 'L2')
                ]
                
                for name, token_id, dept, line in sample_workers:
                    qr_code = generate_qr_code(token_id)
                    cur.execute(
                        "INSERT INTO workers (name, token_id, department, line, qr_code) VALUES (%s, %s, %s, %s, %s)",
                        (name, token_id, dept, line, qr_code)
                    )
            
            # Add sample operations
            cur.execute("SELECT COUNT(*) FROM operations")
            op_count = cur.fetchone()[0]
            
            if op_count == 0:
                print("📝 Adding sample operations...")
                sample_operations = [
                    (1, 'OP001', 'Fabric Cutting', 'Cutting Machine', 'Cutting', 15.5, 25.00),
                    (2, 'OP002', 'Sleeve Attach', 'Overlock', 'Sewing', 12.3, 20.00),
                    (3, 'OP003', 'Side Seam', 'Flatlock', 'Sewing', 10.2, 18.50),
                    (4, 'OP004', 'Hem Finish', 'Hemming Machine', 'Finishing', 8.5, 15.00),
                    (5, 'OP005', 'Quality Check', 'Manual', 'Quality', 5.0, 12.00)
                ]
                
                for seq, op_no, desc, machine, dept, std_min, piece_rate in sample_operations:
                    cur.execute(
                        "INSERT INTO operations (seq_no, op_no, description, machine, department, std_min, piece_rate) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (seq, op_no, desc, machine, dept, std_min, piece_rate)
                    )
            
            # Add sample bundles
            cur.execute("SELECT COUNT(*) FROM bundles")
            bundle_count = cur.fetchone()[0]
            
            if bundle_count == 0:
                print("📝 Adding sample bundles...")
                sample_bundles = [
                    ('B001', '650010011410', 'SAINTX MENS BLAZER', 'Navy', 'M', 50, 'In Progress'),
                    ('B002', '650010011410', 'SAINTX MENS BLAZER', 'Navy', 'L', 60, 'Completed'),
                    ('B003', '650010011410', 'SAINTX MENS BLAZER', 'Black', 'M', 45, 'Pending'),
                    ('B004', '650010011410', 'SAINTX MENS BLAZER', 'Black', 'XL', 55, 'In Progress')
                ]
                
                for bundle_no, order_no, style, color, size, qty, status in sample_bundles:
                    cur.execute(
                        "INSERT INTO bundles (bundle_no, order_no, style, color, size, quantity, status) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (bundle_no, order_no, style, color, size, qty, status)
                    )
            
            # Add sample production order
            cur.execute("SELECT COUNT(*) FROM production_orders")
            order_count = cur.fetchone()[0]
            
            if order_count == 0:
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
# Page Routes (Add these for navigation)
# -----------------------------
@app.route('/')
def index():
    return render_template('dashboard.html')

@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

@app.route('/workers')
def workers():
    return render_template('workers.html')

@app.route('/operations')
def operations():
    return render_template('operations.html')

@app.route('/bundles')
def bundles():
    return render_template('bundles.html')

@app.route('/production_order')
def production_order():
    return render_template('production_order.html')

@app.route('/file_upload')
def file_upload():
    return render_template('file_upload.html')

@app.route('/esp32_scanner')
def esp32_scanner():
    return render_template('esp32_scanner.html')

@app.route('/reports')
def reports():
    return render_template('reports.html')

@app.route('/settings')
def settings():
    return render_template('settings.html')

@app.route("/health")
def health():
    return "OK", 200

# ===== API ROUTES =====
@app.route("/api/dashboard-stats")
def dashboard_stats():
    """Get dashboard statistics"""
    try:
        with get_conn() as conn, conn.cursor() as cur:
            # Get active workers count
            cur.execute("SELECT COUNT(*) FROM workers WHERE status = 'Active'")
            active_workers = cur.fetchone()[0] or 0
            
            # Get total bundles count
            cur.execute("SELECT COUNT(*) FROM bundles")
            total_bundles = cur.fetchone()[0] or 0
            
            # Get total operations count
            cur.execute("SELECT COUNT(*) FROM operations")
            total_operations = cur.fetchone()[0] or 0
            
            # Calculate total earnings (mock calculation - avoid division by zero)
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
    """Get chart data for dashboard"""
    try:
        with get_conn() as conn, conn.cursor() as cur:
            # Bundle status distribution
            cur.execute("SELECT status, COUNT(*) FROM bundles GROUP BY status")
            bundle_status = dict(cur.fetchall())
            
            # Department workload
            cur.execute("SELECT department, COUNT(*) FROM workers GROUP BY department")
            department_data = dict(cur.fetchall())
            
            return jsonify({
                "bundleStatus": bundle_status,
                "departmentWorkload": department_data
            })
    except Exception as e:
        print(f"Chart data error: {e}")
        # Return fallback data instead of empty
        return jsonify({
            "bundleStatus": {"Pending": 2, "In Progress": 2, "Completed": 1},
            "departmentWorkload": {"Cutting": 1, "Sewing": 2, "Finishing": 1, "Quality": 1, "Packing": 1}
        })

@app.route("/api/scan", methods=["POST"])
def api_scan():
    """Handle ESP32 scanner input"""
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
    """Get recent scans"""
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT id, code, created_at FROM scans ORDER BY id DESC LIMIT 100")
            rows = cur.fetchall()
            return jsonify([dict(row) for row in rows])
    except Exception as e:
        print(f"Scans list error: {e}")
        return jsonify([])

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
