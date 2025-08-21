from flask import Flask, render_template, redirect, url_for, request, jsonify, make_response, Response
from flask_cors import CORS
import psycopg2
import psycopg2.extras
import csv
import io
import os
from datetime import datetime
import qrcode
import qrcode.image.svg

app = Flask(__name__)
CORS(app)

# Database connection string (from Render environment)
DB_URL = os.getenv("DATABASE_URL")

# Device shared secret for ESP32 authentication
DEVICE_SECRET = os.getenv("DEVICE_SECRET", "u38fh39fh28fh92hf928hfh92hF9H2hf92h3f9h2F")

def get_conn():
    return psycopg2.connect(DB_URL, sslmode="require")

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

    # Operations table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS operations (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Production logs table
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
            scanned_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()

init_db()

# ---------------- ROUTES ---------------- #

@app.route('/')
def dashboard():
    return render_template('dashboard.html')

# ---- Workers ----
@app.route('/workers')
def workers():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute('SELECT id, name, department, token_id, status, created_at FROM workers ORDER BY created_at DESC')
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
        cursor.execute('INSERT INTO workers (name, department, token_id) VALUES (%s, %s, %s)',
                       (name, department, token_id))
        conn.commit()
    except psycopg2.IntegrityError:
        conn.rollback()
        return "Error: Token ID must be unique", 400
    finally:
        conn.close()

    return redirect(url_for('workers'))

# ---- Dynamic QR code ----
@app.route('/qr/<token_id>')
def qr_code(token_id):
    factory = qrcode.image.svg.SvgImage
    img = qrcode.make(token_id, image_factory=factory)
    stream = io.BytesIO()
    img.save(stream)
    return Response(stream.getvalue(), mimetype='image/svg+xml')

# ---- Scans ----
@app.route('/scan', methods=['POST'])
def scan():
    data = request.get_json()
    token_id = data.get('token_id')
    secret = data.get('secret')

    if not token_id or not secret:
        return jsonify({
            'status': 'error',
            'message': 'Missing token_id or secret',
            'name': '',
            'department': '',
            'scans_today': 0,
            'earnings': 0.0
        }), 400

    if secret != DEVICE_SECRET:
        return jsonify({
            'status': 'error',
            'message': 'Unauthorized',
            'name': '',
            'department': '',
            'scans_today': 0,
            'earnings': 0.0
        }), 403

    conn = get_conn()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cursor.execute('SELECT * FROM workers WHERE token_id = %s', (token_id,))
    worker = cursor.fetchone()

    if worker:
        # Log the scan
        cursor.execute('INSERT INTO scan_logs (token_id) VALUES (%s)', (token_id,))
        conn.commit()

        # Count today's scans
        cursor.execute("""
            SELECT COUNT(*) 
            FROM scan_logs 
            WHERE token_id = %s 
              AND DATE(scanned_at) = CURRENT_DATE
        """, (token_id,))
        scans_today = cursor.fetchone()[0]

        # Example per piece rate — can be made dynamic later
        rate_per_piece = 5.0
        earnings = scans_today * rate_per_piece

        conn.close()
        return jsonify({
            'status': 'success',
            'message': 'Scan logged',
            'name': worker['name'],
            'department': worker['department'],
            'scans_today': scans_today,
            'earnings': earnings
        })

    else:
        conn.close()
        return jsonify({
            'status': 'error',
            'message': 'Invalid token_id',
            'name': '',
            'department': '',
            'scans_today': 0,
            'earnings': 0.0
        }), 404

# ---- Operations ----
@app.route('/operations')
def operations():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute('SELECT id, name, description, created_at FROM operations ORDER BY created_at DESC')
    operations = cursor.fetchall()
    conn.close()
    return render_template('operations.html', operations=operations)

@app.route('/add_operation', methods=['POST'])
def add_operation():
    name = request.form['name']
    description = request.form.get('description', '')

    conn = get_conn()
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO operations (name, description) VALUES (%s, %s)', (name, description))
        conn.commit()
    except psycopg2.IntegrityError:
        conn.rollback()
    conn.close()

    return redirect(url_for('operations'))

# ---- Production ----
@app.route('/production')
def production():
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute('SELECT id, name FROM workers WHERE status = %s', ('active',))
    workers = cursor.fetchall()

    cursor.execute('SELECT id, name FROM operations')
    operations = cursor.fetchall()

    cursor.execute("""
        SELECT pl.id, w.name, o.name, pl.quantity, pl.timestamp, pl.status
        FROM production_logs pl
        JOIN workers w ON pl.worker_id = w.id
        JOIN operations o ON pl.operation_id = o.id
        ORDER BY pl.timestamp DESC
        LIMIT 50
    """)
    logs = cursor.fetchall()

    conn.close()
    return render_template('production.html', workers=workers, operations=operations, logs=logs)

@app.route('/add_production', methods=['POST'])
def add_production():
    worker_id = request.form['worker_id']
    operation_id = request.form['operation_id']
    quantity = request.form.get('quantity', 1)

    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO production_logs (worker_id, operation_id, quantity) VALUES (%s, %s, %s)', 
                   (worker_id, operation_id, quantity))
    conn.commit()
    conn.close()

    return redirect(url_for('production'))

# ---- Reports ----
@app.route('/reports')
def reports():
    return render_template('reports.html')

@app.route('/download_report')
def download_report():
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT w.name, w.department, o.name, 
               pl.quantity, pl.timestamp, pl.status
        FROM production_logs pl
        JOIN workers w ON pl.worker_id = w.id
        JOIN operations o ON pl.operation_id = o.id
        ORDER BY pl.timestamp DESC
    """)

    logs = cursor.fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Worker Name', 'Department', 'Operation', 'Quantity', 'Timestamp', 'Status'])
    writer.writerows(logs)

    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=production_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'

    return response

# ---- Health Check ----
@app.route('/health')
def health_check():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

# ---------------- RUN ---------------- #
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(debug=False, host='0.0.0.0', port=port)
