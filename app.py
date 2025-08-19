from flask import Flask, render_template, redirect, url_for, request, jsonify, make_response
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

# Get DB URL from Render environment variables
DB_URL = os.getenv("DATABASE_URL")

QR_DIR = os.path.join("static", "qrcodes")
os.makedirs(QR_DIR, exist_ok=True)

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

@app.route('/')
def dashboard():
    return render_template('dashboard.html')

@app.route('/workers')
def workers():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute('SELECT id, name, department, token_id FROM workers ORDER BY created_at DESC')
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

        # Generate QR code as SVG
        factory = qrcode.image.svg.SvgImage
        img = qrcode.make(token_id, image_factory=factory)
        svg_path = os.path.join(QR_DIR, f"{token_id}.svg")
        with open(svg_path, "wb") as f:
            img.save(f)

    except psycopg2.IntegrityError:
        conn.rollback()
        return "Error: Token ID must be unique", 400
    finally:
        conn.close()

    return redirect(url_for('workers'))

@app.route('/scan', methods=['POST'])
def scan():
    data = request.get_json()
    token_id = data.get('token_id')

    if not token_id:
        return jsonify({'status': 'error', 'message': 'Missing token_id'}), 400

    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM workers WHERE token_id = %s', (token_id,))
    worker = cursor.fetchone()

    if worker:
        cursor.execute('INSERT INTO scan_logs (token_id) VALUES (%s)', (token_id,))
        conn.commit()
        conn.close()
        return jsonify({'status': 'success', 'message': 'Scan logged'})
    else:
        conn.close()
        return jsonify({'status': 'error', 'message': 'Invalid token_id'}), 404

# (the rest of your routes stay the same — just replace sqlite3 with get_conn())

@app.route('/health')
def health_check():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(debug=False, host='0.0.0.0', port=port)
