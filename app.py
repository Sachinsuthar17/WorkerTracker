from flask import Flask, render_template, redirect, url_for, request, jsonify, make_response
from flask_cors import CORS
import sqlite3
import csv
import io
import os
from datetime import datetime
import qrcode.image.svg

app = Flask(__name__)
CORS(app)

DB_FILE = "production_data.db"
QR_DIR = os.path.join("static", "qrcodes")
os.makedirs(QR_DIR, exist_ok=True)

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Workers table with token_id for QR
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS workers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            department TEXT,
            token_id TEXT UNIQUE,
            status TEXT DEFAULT 'active',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Operations table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS operations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Production logs table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS production_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_id INTEGER,
            operation_id INTEGER,
            quantity INTEGER DEFAULT 1,
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'completed',
            FOREIGN KEY (worker_id) REFERENCES workers(id),
            FOREIGN KEY (operation_id) REFERENCES operations(id)
        )
    """)

    # Scan logs for QR login
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scan_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token_id TEXT NOT NULL,
            scanned_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()

init_db()

@app.route('/')
def dashboard():
    return render_template('dashboard.html')

# Workers
@app.route('/workers')
def workers():
    conn = sqlite3.connect(DB_FILE)
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

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO workers (name, department, token_id) VALUES (?, ?, ?)',
                       (name, department, token_id))
        conn.commit()

        # Generate QR code as SVG (no Pillow needed)
        factory = qrcode.image.svg.SvgImage
        img = qrcode.make(token_id, image_factory=factory)
        qr_path = os.path.join(QR_DIR, f"{token_id}.svg")
        with open(qr_path, 'w') as f:
            img.save(f)

    except sqlite3.IntegrityError:
        return "Error: Token ID must be unique", 400
    finally:
        conn.close()

    return redirect(url_for('workers'))

# QR SCAN endpoint for ESP32
@app.route('/scan', methods=['POST'])
def scan():
    data = request.get_json()
    token_id = data.get('token_id')

    if not token_id:
        return jsonify({'status': 'error', 'message': 'Missing token_id'}), 400

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM workers WHERE token_id = ?', (token_id,))
    worker = cursor.fetchone()

    if worker:
        cursor.execute('INSERT INTO scan_logs (token_id) VALUES (?)', (token_id,))
        conn.commit()
        conn.close()
        return jsonify({'status': 'success', 'message': 'Scan logged'})
    else:
        conn.close()
        return jsonify({'status': 'error', 'message': 'Invalid token_id'}), 404

# Operations
@app.route('/operations')
def operations():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM operations ORDER BY created_at DESC')
    operations = cursor.fetchall()
    conn.close()
    return render_template('operations.html', operations=operations)

@app.route('/add_operation', methods=['POST'])
def add_operation():
    name = request.form['name']
    description = request.form.get('description', '')

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO operations (name, description) VALUES (?, ?)', (name, description))
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()

    return redirect(url_for('operations'))

# Production
@app.route('/production')
def production():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('SELECT id, name FROM workers WHERE status = "active"')
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

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO production_logs (worker_id, operation_id, quantity) VALUES (?, ?, ?)', 
                   (worker_id, operation_id, quantity))
    conn.commit()
    conn.close()

    return redirect(url_for('production'))

# Reports
@app.route('/reports')
def reports():
    return render_template('reports.html')

@app.route('/download_report')
def download_report():
    conn = sqlite3.connect(DB_FILE)
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
    response.headers['Content-Disposition'] = f'attachment; filename=production_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv'

    return response

# Settings
@app.route('/settings')
def settings():
    return render_template('settings.html')

# API
@app.route('/api/stats')
def get_stats():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('SELECT COUNT(*) FROM production_logs')
    total_production = cursor.fetchone()[0] or 0

    cursor.execute('SELECT COUNT(*) FROM workers WHERE status = "active"')
    active_workers = cursor.fetchone()[0] or 0

    conn.close()

    stats = {
        "totalProduction": {"value": total_production, "change": -2.2, "label": "Total Production"},
        "activeWorkers": {"value": active_workers, "change": 2, "label": "Active Workers"},
        "efficiency": {"value": 85.3, "change": 1.8, "label": "Overall Efficiency"},
        "dailyEarnings": {"value": 19283, "change": 3.1, "label": "Daily Earnings"}
    }
    return jsonify(stats)

@app.route('/api/chart-data')
def get_chart_data():
    chart_data = {
        "dailyProduction": {
            "labels": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            "data": [12000, 19000, 15000, 22000, 18000, 25000, 24426]
        },
        "workerPerformance": {
            "labels": ["John", "Alice", "Bob", "Carol", "David"],
            "data": [92, 87, 94, 89, 91]
        }
    }
    return jsonify(chart_data)

@app.route('/api/activities')
def get_recent_activities():
    activities = [
        {"worker": "John Doe", "action": "Completed", "operation": "Cutting", "time": "2 min ago"},
        {"worker": "Alice Smith", "action": "Started", "operation": "Sewing", "time": "5 min ago"},
        {"worker": "Bob Johnson", "action": "Completed", "operation": "Quality Check", "time": "8 min ago"},
        {"worker": "Carol Brown", "action": "Started", "operation": "Packing", "time": "12 min ago"}
    ]
    return jsonify(activities)

@app.route('/health')
def health_check():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(debug=False, host='0.0.0.0', port=port)
