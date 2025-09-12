import os
import io
import sqlite3
from datetime import datetime, timedelta
from typing import Tuple, Optional
from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, send_file
from flask_cors import CORS
import segno
import json

# -----------------------------------------------------------------------------
# App config
# -----------------------------------------------------------------------------
APP_BRAND = os.getenv("APP_BRAND", "Production Scanner")
DEVICE_SECRET = os.getenv("DEVICE_SECRET", "u38fh39fh28fh92hf928hfh92hF9H2hf92h3f9h2F")
RATE_PER_PIECE = float(os.getenv("RATE_PER_PIECE", "2.00"))
DATABASE_PATH = "production.db"

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "dev-secret-key-change-in-production")
CORS(app)

# -----------------------------------------------------------------------------
# Database helpers
# -----------------------------------------------------------------------------
def get_db():
    """Get database connection"""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize database with all required tables"""
    conn = get_db()
    cursor = conn.cursor()

    # Workers table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS workers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            token_id TEXT UNIQUE NOT NULL,
            department TEXT DEFAULT '',
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Operations table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS operations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            operation_code TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Scans table (for barcode scans)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_id INTEGER NOT NULL,
            barcode TEXT,
            operation_code TEXT,
            scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (worker_id) REFERENCES workers(id)
        )
    ''')

    # Production logs table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS production_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_id INTEGER NOT NULL,
            operation_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'completed',
            FOREIGN KEY (worker_id) REFERENCES workers(id),
            FOREIGN KEY (operation_id) REFERENCES operations(id)
        )
    ''')

    # App state table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS app_state (
            id INTEGER PRIMARY KEY,
            current_worker_id INTEGER NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (current_worker_id) REFERENCES workers(id)
        )
    ''')

    # Insert default app state if not exists
    cursor.execute("INSERT OR IGNORE INTO app_state (id) VALUES (1)")

    # Insert sample operations if empty
    cursor.execute("SELECT COUNT(*) FROM operations")
    if cursor.fetchone()[0] == 0:
        sample_ops = [
            ("Cutting", "Fabric cutting operation", "CUT"),
            ("Sewing", "Sewing operation", "SEW"),
            ("Quality Check", "Quality inspection", "QC"),
            ("Packing", "Final packing", "PACK")
        ]
        cursor.executemany(
            "INSERT INTO operations (name, description, operation_code) VALUES (?, ?, ?)",
            sample_ops
        )

    conn.commit()
    conn.close()

def get_active_worker():
    """Get currently active worker"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT w.id, w.name, w.token_id, w.department, w.status
        FROM app_state a
        LEFT JOIN workers w ON w.id = a.current_worker_id
        WHERE a.id = 1
    ''')
    result = cursor.fetchone()
    conn.close()
    return dict(result) if result and result[0] else None

def set_active_worker(worker_id):
    """Set active worker"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE app_state 
        SET current_worker_id = ?, updated_at = CURRENT_TIMESTAMP 
        WHERE id = 1
    ''', (worker_id,))
    conn.commit()
    conn.close()

# Initialize database on startup
init_db()

# -----------------------------------------------------------------------------
# Template globals
# -----------------------------------------------------------------------------
@app.context_processor
def inject_globals():
    return {
        'brand': APP_BRAND,
        'rate_per_piece': RATE_PER_PIECE,
        'now': datetime.now
    }

# -----------------------------------------------------------------------------
# Routes - Main Pages
# -----------------------------------------------------------------------------
@app.route('/')
def dashboard():
    """Main dashboard page"""
    return render_template('dashboard.html')

@app.route('/workers')
def workers():
    """Workers management page"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM workers ORDER BY created_at DESC")
    workers = cursor.fetchall()
    active_worker = get_active_worker()
    conn.close()

    return render_template('workers.html', 
                         workers=workers, 
                         active_worker=active_worker)

@app.route('/operations')
def operations():
    """Operations management page"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM operations ORDER BY created_at DESC")
    operations = cursor.fetchall()
    conn.close()

    return render_template('operations.html', operations=operations)

@app.route('/production')
def production():
    """Production logging page"""
    conn = get_db()
    cursor = conn.cursor()

    # Get production logs with worker and operation names
    cursor.execute('''
        SELECT pl.id, w.name as worker_name, o.name as operation_name,
               pl.quantity, pl.timestamp, pl.status
        FROM production_logs pl
        JOIN workers w ON w.id = pl.worker_id
        JOIN operations o ON o.id = pl.operation_id
        ORDER BY pl.timestamp DESC
        LIMIT 50
    ''')
    production_logs = cursor.fetchall()

    # Get workers and operations for form dropdowns
    cursor.execute("SELECT * FROM workers WHERE status = 'active' ORDER BY name")
    workers = cursor.fetchall()

    cursor.execute("SELECT * FROM operations ORDER BY name")
    operations = cursor.fetchall()

    conn.close()

    return render_template('production.html', 
                         production_logs=production_logs,
                         workers=workers,
                         operations=operations)

@app.route('/reports')
def reports():
    """Reports and analytics page"""
    return render_template('reports.html')

@app.route('/settings')
def settings():
    """System settings page"""
    return render_template('settings.html',
                         device_secret=DEVICE_SECRET,
                         rate_per_piece=RATE_PER_PIECE,
                         brand=APP_BRAND)

# -----------------------------------------------------------------------------
# Worker Management Routes
# -----------------------------------------------------------------------------
@app.route('/add_worker', methods=['POST'])
def add_worker():
    """Add new worker"""
    name = request.form.get('name', '').strip()
    token_id = request.form.get('token_id', '').strip()
    department = request.form.get('department', '').strip()

    if not name or not token_id:
        flash('Name and Token ID are required', 'error')
        return redirect(url_for('workers'))

    conn = get_db()
    cursor = conn.cursor()

    try:
        cursor.execute('''
            INSERT INTO workers (name, token_id, department)
            VALUES (?, ?, ?)
        ''', (name, token_id, department))
        conn.commit()
        flash(f'Worker {name} added successfully', 'success')
    except sqlite3.IntegrityError:
        flash('Token ID already exists', 'error')
    finally:
        conn.close()

    return redirect(url_for('workers'))

@app.route('/toggle_worker/<int:worker_id>')
def toggle_worker(worker_id):
    """Toggle worker active status"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT status FROM workers WHERE id = ?", (worker_id,))
    current_status = cursor.fetchone()[0]
    new_status = 'inactive' if current_status == 'active' else 'active'

    cursor.execute("UPDATE workers SET status = ? WHERE id = ?", (new_status, worker_id))
    conn.commit()
    conn.close()

    flash(f'Worker status updated to {new_status}', 'success')
    return redirect(url_for('workers'))

# -----------------------------------------------------------------------------
# Operation Management Routes
# -----------------------------------------------------------------------------
@app.route('/add_operation', methods=['POST'])
def add_operation():
    """Add new operation"""
    name = request.form.get('name', '').strip()
    operation_code = request.form.get('operation_code', '').strip()
    description = request.form.get('description', '').strip()

    if not name or not operation_code:
        flash('Name and Operation Code are required', 'error')
        return redirect(url_for('operations'))

    conn = get_db()
    cursor = conn.cursor()

    try:
        cursor.execute('''
            INSERT INTO operations (name, operation_code, description)
            VALUES (?, ?, ?)
        ''', (name, operation_code, description))
        conn.commit()
        flash(f'Operation {name} added successfully', 'success')
    except sqlite3.IntegrityError:
        flash('Operation Code already exists', 'error')
    finally:
        conn.close()

    return redirect(url_for('operations'))

# -----------------------------------------------------------------------------
# Production Management Routes
# -----------------------------------------------------------------------------
@app.route('/add_production', methods=['POST'])
def add_production():
    """Add production log entry"""
    worker_id = request.form.get('worker_id')
    operation_id = request.form.get('operation_id')
    quantity = request.form.get('quantity', '1')

    if not worker_id or not operation_id:
        flash('Worker and Operation are required', 'error')
        return redirect(url_for('production'))

    try:
        quantity = int(quantity)
        if quantity <= 0:
            raise ValueError()
    except ValueError:
        flash('Quantity must be a positive number', 'error')
        return redirect(url_for('production'))

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        INSERT INTO production_logs (worker_id, operation_id, quantity)
        VALUES (?, ?, ?)
    ''', (worker_id, operation_id, quantity))
    conn.commit()
    conn.close()

    flash(f'Production entry added: {quantity} pieces', 'success')
    return redirect(url_for('production'))

# -----------------------------------------------------------------------------
# QR Code Generation
# -----------------------------------------------------------------------------
@app.route('/workers/<int:worker_id>/qr.png')
def worker_qr(worker_id):
    """Generate QR code for worker"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT token_id FROM workers WHERE id = ?", (worker_id,))
    result = cursor.fetchone()
    conn.close()

    if not result:
        return "Worker not found", 404

    # Create QR code with worker token
    qr_data = f"W:{result[0]}"
    qr = segno.make(qr_data)

    # Create in-memory file
    img_buffer = io.BytesIO()
    qr.save(img_buffer, kind='png', scale=8)
    img_buffer.seek(0)

    return send_file(img_buffer, mimetype='image/png')

# -----------------------------------------------------------------------------
# API Routes for Dashboard
# -----------------------------------------------------------------------------
@app.route('/api/stats')
def api_stats():
    """API endpoint for dashboard stats"""
    conn = get_db()
    cursor = conn.cursor()
    today = datetime.now().strftime('%Y-%m-%d')

    # Get today's stats
    cursor.execute("SELECT COUNT(*) FROM scans WHERE DATE(scanned_at) = ?", (today,))
    pieces_today = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT worker_id) FROM scans WHERE DATE(scanned_at) = ?", (today,))
    workers_today = cursor.fetchone()[0]

    earnings_today = pieces_today * RATE_PER_PIECE

    cursor.execute("SELECT COUNT(*) FROM workers WHERE status = 'active'")
    total_workers = cursor.fetchone()[0]

    # Get active worker
    active_worker = get_active_worker()

    conn.close()

    return jsonify({
        'pieces_today': pieces_today,
        'workers_today': workers_today,
        'earnings_today': round(earnings_today, 2),
        'total_workers': total_workers,
        'active_worker': active_worker['name'] if active_worker else None
    })

@app.route('/api/activities')
def api_activities():
    """API endpoint for recent activities"""
    limit = min(int(request.args.get('limit', 10)), 50)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT w.name, w.department, s.barcode, s.scanned_at, s.operation_code
        FROM scans s
        JOIN workers w ON w.id = s.worker_id
        ORDER BY s.scanned_at DESC
        LIMIT ?
    ''', (limit,))
    results = cursor.fetchall()
    conn.close()

    activities = [{
        'worker': row[0],
        'department': row[1] or '',
        'barcode': row[2] or '',
        'timestamp': row[3],
        'operation_code': row[4] or ''
    } for row in results]

    return jsonify({'activities': activities})

# -----------------------------------------------------------------------------
# ESP32 Unified Scan Endpoint
# -----------------------------------------------------------------------------
@app.route('/scan', methods=['POST'])
def scan_unified():
    """Unified endpoint for ESP32 barcode scanning"""
    payload = request.get_json(force=True, silent=True) or {}

    # Verify secret
    if payload.get('secret') != DEVICE_SECRET:
        return jsonify({
            'ok': False,
            'error': 'forbidden',
            'message': 'Invalid device secret'
        }), 403

    token_id = payload.get('token_id', '').strip()
    worker_name = payload.get('worker_name', '').strip()
    barcode = payload.get('barcode', '').strip()

    # Remove prefixes if present
    if token_id.upper().startswith('W:'):
        token_id = token_id[2:]
    if barcode.upper().startswith('B:'):
        barcode = barcode[2:]

    conn = get_db()
    cursor = conn.cursor()

    try:
        # Find worker by token_id or name
        worker = None
        if token_id:
            cursor.execute("SELECT * FROM workers WHERE token_id = ? AND status = 'active'", (token_id,))
            worker = cursor.fetchone()

        if not worker and worker_name:
            cursor.execute("SELECT * FROM workers WHERE name = ? AND status = 'active'", (worker_name,))
            worker = cursor.fetchone()

        if not worker:
            return jsonify({
                'ok': False,
                'status': 'error',
                'message': 'Worker not found or inactive'
            })

        worker = dict(worker)

        # CASE 1: Worker QR scan (toggle login/logout)
        if not barcode:
            active_worker = get_active_worker()
            if active_worker and active_worker['id'] == worker['id']:
                # Same worker -> logout
                set_active_worker(None)
                status = 'logged_out'
                effective_worker = None
                message = f"Worker {worker['name']} logged out"
            else:
                # Different worker -> login
                set_active_worker(worker['id'])
                status = 'logged_in'
                effective_worker = worker
                message = f"Worker {worker['name']} logged in"

        # CASE 2: Barcode scan (save piece)
        else:
            active_worker = get_active_worker()
            effective_worker = active_worker if active_worker else worker

            # Extract operation code from barcode if present
            operation_code = None
            if '-' in barcode:
                parts = barcode.split('-')
                if len(parts) >= 2:
                    operation_code = parts[0]

            # Save scan
            cursor.execute('''
                INSERT INTO scans (worker_id, barcode, operation_code)
                VALUES (?, ?, ?)
            ''', (effective_worker['id'], barcode, operation_code))

            status = 'saved'
            message = f"Barcode {barcode} scanned for {effective_worker['name']}"

        # Get today's stats for the effective worker
        today = datetime.now().strftime('%Y-%m-%d')
        pieces_count = 0
        if effective_worker:
            cursor.execute('''
                SELECT COUNT(*) FROM scans 
                WHERE worker_id = ? AND DATE(scanned_at) = ?
            ''', (effective_worker['id'], today))
            pieces_count = cursor.fetchone()[0]

        earnings = pieces_count * RATE_PER_PIECE

        conn.commit()
        conn.close()

        return jsonify({
            'ok': True,
            'status': status,
            'message': message,
            'active_worker': effective_worker or {},
            'today_pieces': pieces_count,
            'today_earn': round(earnings, 2),
            'rate_per_piece': RATE_PER_PIECE
        })

    except Exception as e:
        conn.close()
        return jsonify({
            'ok': False,
            'status': 'error',
            'message': f'Database error: {str(e)}'
        }), 500

# -----------------------------------------------------------------------------
# Data Export Routes
# -----------------------------------------------------------------------------
@app.route('/export/workers')
def export_workers():
    """Export workers data as CSV"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM workers ORDER BY name")
    workers = cursor.fetchall()
    conn.close()

    output = io.StringIO()
    output.write("ID,Name,Token ID,Department,Status,Created At\n")
    for worker in workers:
        output.write(f"{worker[0]},{worker[1]},{worker[2]},{worker[3]},{worker[4]},{worker[5]}\n")

    mem = io.BytesIO()
    mem.write(output.getvalue().encode('utf-8'))
    mem.seek(0)
    output.close()

    return send_file(mem, mimetype='text/csv', as_attachment=True, download_name='workers.csv')

@app.route('/export/scans')
def export_scans():
    """Export scans data as CSV"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT s.id, w.name, s.barcode, s.operation_code, s.scanned_at
        FROM scans s
        JOIN workers w ON w.id = s.worker_id
        ORDER BY s.scanned_at DESC
    ''')
    scans = cursor.fetchall()
    conn.close()

    output = io.StringIO()
    output.write("ID,Worker,Barcode,Operation Code,Scanned At\n")
    for scan in scans:
        output.write(f"{scan[0]},{scan[1]},{scan[2]},{scan[3]},{scan[4]}\n")

    mem = io.BytesIO()
    mem.write(output.getvalue().encode('utf-8'))
    mem.seek(0)
    output.close()

    return send_file(mem, mimetype='text/csv', as_attachment=True, download_name='scans.csv')

@app.route('/export/production')
def export_production():
    """Export production data as CSV"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT pl.id, w.name as worker_name, o.name as operation_name,
               pl.quantity, pl.timestamp, pl.status
        FROM production_logs pl
        JOIN workers w ON w.id = pl.worker_id
        JOIN operations o ON o.id = pl.operation_id
        ORDER BY pl.timestamp DESC
    ''')
    logs = cursor.fetchall()
    conn.close()

    output = io.StringIO()
    output.write("ID,Worker,Operation,Quantity,Timestamp,Status\n")
    for log in logs:
        output.write(f"{log[0]},{log[1]},{log[2]},{log[3]},{log[4]},{log[5]}\n")

    mem = io.BytesIO()
    mem.write(output.getvalue().encode('utf-8'))
    mem.seek(0)
    output.close()

    return send_file(mem, mimetype='text/csv', as_attachment=True, download_name='production.csv')

# -----------------------------------------------------------------------------
# Error Handlers
# -----------------------------------------------------------------------------
@app.errorhandler(404)
def not_found(error):
    return render_template('dashboard.html'), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('dashboard.html'), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
