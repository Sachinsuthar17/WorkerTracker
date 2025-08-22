from flask import Flask, render_template, redirect, url_for, request, jsonify, Response
from flask_cors import CORS
import psycopg2
import psycopg2.extras
import io
import os
from datetime import datetime
import qrcode
import qrcode.image.svg

app = Flask(__name__)
CORS(app)

# ---------------- CONFIG ---------------- #
DB_URL = os.getenv("DATABASE_URL")
DEVICE_SECRET = os.getenv("DEVICE_SECRET", "u38fh39fh28fh92hf928hfh92hF9H2hf92h3f9h2F")

def get_conn():
    return psycopg2.connect(DB_URL, sslmode="require")

# ---------------- INIT DB + MIGRATION ---------------- #
def init_db():
    conn = get_conn()
    cursor = conn.cursor()

    # Workers table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS workers (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            department TEXT,
            token_id TEXT UNIQUE,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Ensure new columns exist (safe migrations)
    cursor.execute("ALTER TABLE workers ADD COLUMN IF NOT EXISTS is_logged_in BOOLEAN DEFAULT FALSE;")
    cursor.execute("ALTER TABLE workers ADD COLUMN IF NOT EXISTS last_login TIMESTAMPTZ;")
    cursor.execute("ALTER TABLE workers ADD COLUMN IF NOT EXISTS last_logout TIMESTAMPTZ;")

    # Operations table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS operations (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Production logs
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS production_logs (
            id SERIAL PRIMARY KEY,
            worker_id INTEGER REFERENCES workers(id),
            operation_id INTEGER REFERENCES operations(id),
            quantity INTEGER DEFAULT 1,
            timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'completed'
        )
    """)

    # Scan logs
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scan_logs (
            id SERIAL PRIMARY KEY,
            token_id TEXT NOT NULL,
            scan_type TEXT DEFAULT 'work',
            scanned_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()

init_db()

# ---------------- ROUTES ---------------- #

# Dashboard
@app.route('/')
def dashboard():
    return render_template('dashboard.html')

# Workers
@app.route('/workers')
def workers():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, department, token_id, status, is_logged_in, last_login, last_logout, created_at
        FROM workers ORDER BY created_at DESC
    """)
    workers = cursor.fetchall()
    conn.close()
    return render_template('workers.html', workers=workers)

@app.route('/add_worker', methods=['POST'])
def add_worker():
    name = request.form['name']
    department = request.form['department']
    token_id = request.form['token_id']

    conn = get_conn()
    cursor = conn.cursor()
    try:
        cursor.execute(
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
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, description, created_at
        FROM operations ORDER BY created_at DESC
    """)
    operations = cursor.fetchall()
    conn.close()
    return render_template('operations.html', operations=operations)

@app.route('/add_operation', methods=['POST'])
def add_operation():
    name = request.form['name']
    description = request.form['description']

    conn = get_conn()
    cursor = conn.cursor()
    try:
        cursor.execute(
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

# Production (placeholder for now)
@app.route('/production')
def production():
    return render_template('production.html')

# Reports (placeholder for now)
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
    data = request.get_json()
    token_id = data.get('token_id')
    secret = data.get('secret')
    scan_type = data.get('scan_type', 'work')

    # --- Validation ---
    if not token_id or not secret:
        return jsonify({'status': 'error', 'message': 'Missing token_id or secret'}), 400
    if secret != DEVICE_SECRET:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403

    conn = get_conn()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cursor.execute('SELECT * FROM workers WHERE token_id = %s', (token_id,))
    worker = cursor.fetchone()

    if not worker:
        conn.close()
        return jsonify({'status': 'error', 'message': 'Invalid token_id'}), 404

    # --- Always log scan ---
    cursor.execute(
        'INSERT INTO scan_logs (token_id, scan_type) VALUES (%s, %s)',
        (token_id, scan_type)
    )

    message = ""
    is_logged_in = worker['is_logged_in']

    if scan_type == "login":
        cursor.execute(
            "UPDATE workers SET is_logged_in = TRUE, last_login = NOW() WHERE token_id = %s",
            (token_id,)
        )
        message = "Login successful"
        is_logged_in = True

    elif scan_type == "logout":
        cursor.execute(
            "UPDATE workers SET is_logged_in = FALSE, last_logout = NOW() WHERE token_id = %s",
            (token_id,)
        )
        message = "Logout successful"
        is_logged_in = False

    else:  # work scan
        message = "Work scan logged"

    # --- Count today’s work scans ---
    cursor.execute("""
        SELECT COUNT(*) 
        FROM scan_logs 
        WHERE token_id = %s AND scan_type = 'work'
          AND DATE(scanned_at) = CURRENT_DATE
    """, (token_id,))
    scans_today = cursor.fetchone()[0]

    rate_per_piece = 5.0  # 💰 change as needed
    earnings = scans_today * rate_per_piece

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

# ---------------- RUN ---------------- #
if __name__ == "__main__":
    app.run(debug=True)
