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

DB_URL = os.getenv("DATABASE_URL")
DEVICE_SECRET = os.getenv("DEVICE_SECRET", "u38fh39fh28fh92hf928hfh92hF9H2hf92h3f9h2F")

def get_conn():
    return psycopg2.connect(DB_URL, sslmode="require")

def init_db():
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
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

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS operations (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
    """)

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

@app.route('/')
def dashboard():
    return render_template('dashboard.html')

@app.route('/workers')
def workers():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute('SELECT id, name, department, token_id, status, is_logged_in, last_login, last_logout, created_at FROM workers ORDER BY created_at DESC')
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

@app.route('/qr/<token_id>')
def qr_code(token_id):
    factory = qrcode.image.svg.SvgImage
    img = qrcode.make(token_id, image_factory=factory)
    stream = io.BytesIO()
    img.save(stream)
    return Response(stream.getvalue(), mimetype='image/svg+xml')

# ---- Scans with login/logout ----
@app.route('/scan', methods=['POST'])
def scan():
    data = request.get_json()
    token_id = data.get('token_id')
    secret = data.get('secret')
    scan_type = data.get('scan_type', 'work')  # default: work

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

    # Log scan
    cursor.execute('INSERT INTO scan_logs (token_id, scan_type) VALUES (%s, %s)', (token_id, scan_type))

    if scan_type == "login":
        cursor.execute("UPDATE workers SET is_logged_in = TRUE, last_login = NOW() WHERE token_id = %s", (token_id,))
        message = "Login successful"
    elif scan_type == "logout":
        cursor.execute("UPDATE workers SET is_logged_in = FALSE, last_logout = NOW() WHERE token_id = %s", (token_id,))
        message = "Logout successful"
    else:  # work
        message = "Work scan logged"

    # Count today's work scans
    cursor.execute("""
        SELECT COUNT(*) 
        FROM scan_logs 
        WHERE token_id = %s AND scan_type = 'work'
          AND DATE(scanned_at) = CURRENT_DATE
    """, (token_id,))
    scans_today = cursor.fetchone()[0]

    rate_per_piece = 5.0
    earnings = scans_today * rate_per_piece

    conn.commit()
    conn.close()

    return jsonify({
        'status': 'success',
        'message': message,
        'name': worker['name'],
        'department': worker['department'],
        'is_logged_in': worker['is_logged_in'],
        'scans_today': scans_today,
        'earnings': earnings
    })
