from flask import Flask, render_template, redirect, url_for, request, jsonify, Response, abort
from flask_cors import CORS
import psycopg2
import psycopg2.extras
import io
import os
from datetime import datetime
import qrcode
import qrcode.image.svg

# ---------------- APP & CORS ---------------- #
app = Flask(__name__)
CORS(app)

# ---------------- CONFIG ---------------- #
DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    raise RuntimeError("DATABASE_URL is not set. Add it in Render → Environment.")

DEVICE_SECRET = os.getenv("DEVICE_SECRET", "u38fh39fh28fh92hf928hfh92hF9H2hf92h3f9h2F")
RATE_PER_PIECE = float(os.getenv("RATE_PER_PIECE", "5.0"))

def get_conn():
    # Render Postgres typically requires SSL
    return psycopg2.connect(DB_URL, sslmode="require")

# ---------------- INIT & MIGRATE DB ---------------- #
def init_db():
    """Create tables if they do not exist."""
    conn = get_conn()
    cur = conn.cursor()
    # workers
    cur.execute("""
        CREATE TABLE IF NOT EXISTS workers (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            department TEXT,
            token_id TEXT UNIQUE,
            status TEXT DEFAULT 'active',
            is_logged_in BOOLEAN DEFAULT FALSE,
            last_login TIMESTAMPTZ,
            last_logout TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # operations
    cur.execute("""
        CREATE TABLE IF NOT EXISTS operations (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # production_logs
    cur.execute("""
        CREATE TABLE IF NOT EXISTS production_logs (
            id SERIAL PRIMARY KEY,
            worker_id INTEGER REFERENCES workers(id),
            operation_id INTEGER REFERENCES operations(id),
            quantity INTEGER DEFAULT 1,
            timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'completed'
        )
    """)
    # scan_logs
    cur.execute("""
        CREATE TABLE IF NOT EXISTS scan_logs (
            id SERIAL PRIMARY KEY,
            token_id TEXT NOT NULL,
            scan_type TEXT DEFAULT 'work',
            scanned_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def migrate_db():
    """Add columns that might be missing from older deployments."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("ALTER TABLE workers ADD COLUMN IF NOT EXISTS is_logged_in BOOLEAN DEFAULT FALSE;")
    cur.execute("ALTER TABLE workers ADD COLUMN IF NOT EXISTS last_login TIMESTAMPTZ;")
    cur.execute("ALTER TABLE workers ADD COLUMN IF NOT EXISTS last_logout TIMESTAMPTZ;")
    cur.execute("ALTER TABLE scan_logs ADD COLUMN IF NOT EXISTS scan_type TEXT DEFAULT 'work';")
    conn.commit()
    conn.close()

# Initialize + attempt migration on import
try:
    init_db()
    migrate_db()
except Exception as e:
    # Don't crash the import; logs will show the error
    print("DB init/migrate error:", e)

# ---------------- ROUTES ---------------- #

# Dashboard
@app.route('/')
def dashboard():
    return render_template('dashboard.html')

# Simple health endpoint for uptime pings
@app.route('/healthz')
def healthz():
    return "ok", 200

# Workers
@app.route('/workers')
def workers():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, department, token_id, status, is_logged_in, last_login, last_logout, created_at
        FROM workers ORDER BY created_at DESC
    """)
    rows = cur.fetchall()
    conn.close()
    return render_template('workers.html', workers=rows)

@app.route('/add_worker', methods=['POST'])
def add_worker():
    name = request.form.get('name', '').strip()
    department = request.form.get('department', '').strip()
    token_id = request.form.get('token_id', '').strip()
    if not name or not token_id:
        return "Name and Token ID are required", 400

    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            'INSERT INTO workers (name, department, token_id) VALUES (%s, %s, %s)',
            (name, department, token_id)
        )
        conn.commit()
    except psycopg2.IntegrityError:
        conn.rollback()
        return "Error: Token ID must be unique", 400
    finally:
        conn.close()

    return redirect(url_for('workers'))

# Operations
@app.route('/operations')
def operations():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, description, created_at
        FROM operations ORDER BY created_at DESC
    """)
    rows = cur.fetchall()
    conn.close()
    return render_template('operations.html', operations=rows)

@app.route('/add_operation', methods=['POST'])
def add_operation():
    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    if not name:
        return "Name is required", 400

    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            'INSERT INTO operations (name, description) VALUES (%s, %s)',
            (name, description)
        )
        conn.commit()
    except psycopg2.IntegrityError:
        conn.rollback()
        return "Error: Operation already exists", 400
    finally:
        conn.close()

    return redirect(url_for('operations'))

# Production: page + add_production handler
@app.route('/production')
def production():
    # (You can fill this page later; just render the template for now)
    return render_template('production.html')

@app.route('/add_production', methods=['POST'])
def add_production():
    """Create a production log entry."""
    try:
        worker_id = int(request.form.get('worker_id', '0'))
        operation_id = int(request.form.get('operation_id', '0'))
        quantity = int(request.form.get('quantity', '1') or '1')
    except ValueError:
        return "Invalid numeric values", 400

    if worker_id <= 0 or operation_id <= 0:
        return "worker_id and operation_id are required", 400

    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO production_logs (worker_id, operation_id, quantity)
            VALUES (%s, %s, %s)
        """, (worker_id, operation_id, quantity))
        conn.commit()
    except Exception as e:
        conn.rollback()
        return f"Failed to add production log: {e}", 500
    finally:
        conn.close()

    return redirect(url_for('production'))

# Reports
@app.route('/reports')
def reports():
    return render_template('reports.html')

# ---------------- QR CODE ---------------- #
@app.route('/qr/<token_id>')
def qr_code(token_id):
    factory = qrcode.image.svg.SvgImage
    img = qrcode.make(token_id, image_factory=factory)
    stream = io.BytesIO()
    img.save(stream)
    return Response(stream.getvalue(), mimetype='image/svg+xml')

# ---------------- SCAN API ---------------- #
@app.route('/scan', methods=['POST'])
def scan():
    data = request.get_json(silent=True) or {}
    token_id = data.get('token_id')
    secret = data.get('secret')
    scan_type = data.get('scan_type', 'work')

    # --- Validation ---
    if not token_id or not secret:
        return jsonify({'status': 'error', 'message': 'Missing token_id or secret'}), 400
    if secret != DEVICE_SECRET:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403

    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute('SELECT * FROM workers WHERE token_id = %s', (token_id,))
    worker = cur.fetchone()

    if not worker:
        conn.close()
        return jsonify({'status': 'error', 'message': 'Invalid token_id'}), 404

    # --- Always log scan ---
    try:
        cur.execute(
            'INSERT INTO scan_logs (token_id, scan_type) VALUES (%s, %s)',
            (token_id, scan_type)
        )
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'status': 'error', 'message': f'scan log failed: {e}'}), 500

    message = ""
    is_logged_in = worker['is_logged_in']

    if scan_type == "login":
        cur.execute(
            "UPDATE workers SET is_logged_in = TRUE, last_login = NOW() WHERE token_id = %s",
            (token_id,)
        )
        message = "Login successful"
        is_logged_in = True

    elif scan_type == "logout":
        cur.execute(
            "UPDATE workers SET is_logged_in = FALSE, last_logout = NOW() WHERE token_id = %s",
            (token_id,)
        )
        message = "Logout successful"
        is_logged_in = False

    else:  # work scan
        message = "Work scan logged"

    # --- Count today’s work scans ---
    cur.execute("""
        SELECT COUNT(*) 
        FROM scan_logs 
        WHERE token_id = %s AND scan_type = 'work'
          AND DATE(scanned_at) = CURRENT_DATE
    """, (token_id,))
    scans_today = cur.fetchone()[0]

    earnings = scans_today * RATE_PER_PIECE

    conn.commit()
    conn.close()

    # --- Response aligned with ESP32 expectations ---
    return jsonify({
        'status': 'success',
        'message': message,
        'name': worker['name'],
        'department': worker['department'],
        'is_logged_in': is_logged_in,
        'scans_today': scans_today,
        'earnings': earnings
    })

# ---------------- DASHBOARD JSON APIs ---------------- #
@app.route('/api/stats')
def api_stats():
    conn = get_conn()
    cur = conn.cursor()
    # total workers
    cur.execute("SELECT COUNT(*) FROM workers")
    workers_count = cur.fetchone()[0]
    # total operations
    cur.execute("SELECT COUNT(*) FROM operations")
    operations_count = cur.fetchone()[0]
    # today scans (work)
    cur.execute("""
        SELECT COUNT(*) FROM scan_logs
        WHERE scan_type = 'work' AND DATE(scanned_at) = CURRENT_DATE
    """)
    scans_today = cur.fetchone()[0]
    conn.close()

    return jsonify({
        "workers": workers_count,
        "operations": operations_count,
        "scans_today": scans_today,
        "estimated_earnings_today_total": scans_today * RATE_PER_PIECE
    })

@app.route('/api/chart-data')
def api_chart_data():
    """
    Return last 7 days of work scans for a simple chart.
    labels: list of ISO dates
    values: parallel list of counts
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        WITH days AS (
            SELECT generate_series(CURRENT_DATE - INTERVAL '6 days', CURRENT_DATE, INTERVAL '1 day')::date AS d
        )
        SELECT d AS day,
               COALESCE((
                    SELECT COUNT(*) FROM scan_logs s
                    WHERE DATE(s.scanned_at) = d AND s.scan_type = 'work'
                ), 0) AS cnt
        FROM days
        ORDER BY day
    """)
    rows = cur.fetchall()
    conn.close()

    labels = [r[0].isoformat() for r in rows]
    values = [int(r[1]) for r in rows]
    return jsonify({"labels": labels, "values": values})

@app.route('/api/activities')
def api_activities():
    """
    Return recent scans with worker name.
    """
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("""
        SELECT s.id, s.token_id, s.scan_type, s.scanned_at, w.name AS worker_name, w.department
        FROM scan_logs s
        LEFT JOIN workers w ON w.token_id = s.token_id
        ORDER BY s.scanned_at DESC
        LIMIT 20
    """)
    rows = cur.fetchall()
    conn.close()

    items = []
    for r in rows:
        items.append({
            "id": r["id"],
            "token_id": r["token_id"],
            "scan_type": r["scan_type"],
            "scanned_at": r["scanned_at"].isoformat() if r["scanned_at"] else None,
            "worker_name": r["worker_name"],
            "department": r["department"]
        })
    return jsonify(items)

# ---------------- ONE-TIME DB MIGRATION (protected) ---------------- #
@app.route('/admin/migrate')
def admin_migrate():
    """
    Call once: https://your-domain/admin/migrate?secret=DEVICE_SECRET
    """
    secret = request.args.get("secret")
    if secret != DEVICE_SECRET:
        abort(403)
    try:
        migrate_db()
        return "Migration complete ✅", 200
    except Exception as e:
        return f"Migration error: {e}", 500

# ---------------- RUN (for local dev) ---------------- #
if __name__ == "__main__":
    # In Render, gunicorn runs this; local dev can run: python app.py
    app.run(host="0.0.0.0", port=5000, debug=True)
