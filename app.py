#!/usr/bin/env python3
"""
Complete Garment Manufacturing ERP System
Render.com Deployment Ready - All calculations in Rupees (₹)
"""

import os
import io
import sqlite3
import json
import csv
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from flask import Flask, request, jsonify, render_template_string, redirect, url_for, flash, send_file
from flask_cors import CORS
import segno

# Try to import pandas for Excel processing
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

from werkzeug.utils import secure_filename

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
APP_BRAND = os.getenv("APP_BRAND", "Garment Manufacturing ERP")
DEVICE_SECRET = os.getenv("DEVICE_SECRET", "garment_erp_2024_secret")
BASE_RATE_PER_MINUTE = float(os.getenv("BASE_RATE_PER_MINUTE", "0.50"))  # ₹0.50 per minute
DATABASE_URL = os.getenv("DATABASE_URL", "garment_erp.db")
UPLOAD_FOLDER = 'uploads'

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "garment-erp-secret-key-change-in-production")
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
CORS(app)

# Create upload folder
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# -----------------------------------------------------------------------------
# Database Functions
# -----------------------------------------------------------------------------
def get_db_connection():
    """Get database connection"""
    conn = sqlite3.connect(DATABASE_URL)
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    """Initialize database with all required tables"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Workers table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS workers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_id TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            department TEXT DEFAULT '',
            skill_level TEXT DEFAULT 'MEDIUM',
            hourly_rate REAL DEFAULT 30.0,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Operation Breakdown table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS operation_breakdown (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            seq_no INTEGER,
            op_no TEXT,
            description TEXT,
            machine TEXT,
            subsection TEXT,
            std_min REAL,
            product TEXT,
            skill TEXT,
            grade TEXT,
            style_no TEXT,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Production Orders table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS production_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_no TEXT UNIQUE NOT NULL,
            style_no TEXT NOT NULL,
            style_name TEXT,
            buyer TEXT,
            order_qty INTEGER,
            delivery_date DATE,
            status TEXT DEFAULT 'active',
            color_size_breakdown TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Bundles table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bundles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bundle_no TEXT UNIQUE NOT NULL,
            order_no TEXT NOT NULL,
            style_no TEXT NOT NULL,
            color TEXT,
            size_range TEXT,
            bundle_qty INTEGER,
            current_operation TEXT,
            status TEXT DEFAULT 'created',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Production Lines table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS production_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            line_no TEXT UNIQUE NOT NULL,
            line_name TEXT,
            supervisor_id TEXT,
            capacity INTEGER DEFAULT 50,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Worker Operations Assignment table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS worker_operations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_id TEXT NOT NULL,
            line_no TEXT NOT NULL,
            op_no TEXT NOT NULL,
            style_no TEXT NOT NULL,
            assigned_date DATE DEFAULT (date('now')),
            status TEXT DEFAULT 'active'
        )
    ''')

    # Bundle Operations Scanning table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bundle_operations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bundle_no TEXT NOT NULL,
            worker_id TEXT NOT NULL,
            op_no TEXT NOT NULL,
            operation_desc TEXT,
            std_min REAL,
            actual_min REAL,
            pieces_completed INTEGER,
            start_time TIMESTAMP,
            end_time TIMESTAMP,
            earnings REAL DEFAULT 0.0,
            status TEXT DEFAULT 'completed',
            scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # System Settings table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS system_settings (
            id INTEGER PRIMARY KEY,
            setting_name TEXT UNIQUE,
            setting_value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Insert default settings
    cursor.execute('INSERT OR IGNORE INTO system_settings (id, setting_name, setting_value) VALUES (1, "base_rate_per_minute", ?)', (str(BASE_RATE_PER_MINUTE),))
    cursor.execute('INSERT OR IGNORE INTO system_settings (id, setting_name, setting_value) VALUES (2, "efficiency_target", "100")')
    cursor.execute('INSERT OR IGNORE INTO system_settings (id, setting_name, setting_value) VALUES (3, "quality_target", "95")')

    # Insert sample data
    cursor.execute("SELECT COUNT(*) FROM workers")
    if cursor.fetchone()[0] == 0:
        sample_workers = [
            ('W001', 'Rajesh Kumar', 'SLEEVE', 'HIGH', 35.0),
            ('W002', 'Priya Sharma', 'BODY', 'MEDIUM', 30.0),
            ('W003', 'Amit Singh', 'COLLAR', 'HIGH', 32.0),
            ('W004', 'Sunita Devi', 'LINING', 'MEDIUM', 28.0),
            ('W005', 'Ravi Patel', 'ASSE-1', 'HIGH', 40.0)
        ]
        cursor.executemany('INSERT INTO workers (worker_id, name, department, skill_level, hourly_rate) VALUES (?, ?, ?, ?, ?)', sample_workers)

    cursor.execute("SELECT COUNT(*) FROM production_lines")
    if cursor.fetchone()[0] == 0:
        sample_lines = [
            ('LINE-01', 'Main Production Line A', 'SUP001', 60),
            ('LINE-02', 'Main Production Line B', 'SUP002', 50),
            ('LINE-03', 'Finishing Line', 'SUP003', 40)
        ]
        cursor.executemany('INSERT INTO production_lines (line_no, line_name, supervisor_id, capacity) VALUES (?, ?, ?, ?)', sample_lines)

    conn.commit()
    conn.close()

# Initialize database on startup
init_database()

# -----------------------------------------------------------------------------
# HTML Templates
# -----------------------------------------------------------------------------
BASE_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ brand }}</title>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        :root {
            --bg-primary: #0f1419;
            --bg-secondary: #1e2936;
            --text-primary: #f8fafc;
            --text-secondary: #cbd5e1;
            --text-muted: #64748b;
            --accent-blue: #3b82f6;
            --accent-green: #10b981;
            --accent-orange: #f59e0b;
            --accent-red: #ef4444;
            --border-color: #374151;
        }

        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            font-family: -apple-system, BlinkMacSystemFont, sans-serif;
            background: linear-gradient(135deg, #0f1419 0%, #1e2936 100%);
            color: var(--text-primary);
            min-height: 100vh;
        }

        .dashboard { display: flex; min-height: 100vh; }

        .sidebar {
            width: 280px;
            background: rgba(30, 41, 54, 0.9);
            border-right: 1px solid var(--border-color);
            padding: 2rem 0;
            position: fixed;
            height: 100vh;
            overflow-y: auto;
            z-index: 1000;
        }

        .sidebar-header {
            padding: 0 2rem 2rem;
            border-bottom: 1px solid var(--border-color);
            margin-bottom: 2rem;
        }

        .logo {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            font-size: 1.1rem;
            font-weight: 700;
            color: var(--accent-blue);
        }

        .sidebar-menu { list-style: none; padding: 0 1rem; }

        .menu-item { margin-bottom: 0.5rem; }

        .menu-link {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            padding: 0.875rem 1rem;
            color: var(--text-secondary);
            text-decoration: none;
            border-radius: 0.5rem;
            transition: all 0.2s ease;
        }

        .menu-link:hover {
            background: rgba(59, 130, 246, 0.1);
            color: var(--text-primary);
        }

        .menu-item.active .menu-link {
            background: var(--accent-blue);
            color: white;
        }

        .main-content {
            flex: 1;
            margin-left: 280px;
            padding: 2rem;
            min-height: 100vh;
        }

        .card {
            background: rgba(30, 41, 54, 0.7);
            border: 1px solid var(--border-color);
            border-radius: 1rem;
            padding: 2rem;
            margin-bottom: 2rem;
        }

        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }

        .stat-card {
            background: rgba(30, 41, 54, 0.8);
            border: 1px solid var(--border-color);
            border-radius: 1rem;
            padding: 1.5rem;
            text-align: center;
        }

        .stat-value {
            font-size: 2.5rem;
            font-weight: 700;
            color: var(--accent-blue);
            margin-bottom: 0.5rem;
        }

        .stat-label {
            color: var(--text-secondary);
            font-size: 0.875rem;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 1rem;
        }

        th, td {
            padding: 0.875rem;
            text-align: left;
            border-bottom: 1px solid var(--border-color);
        }

        th {
            background: rgba(15, 20, 25, 0.8);
            font-weight: 600;
            color: var(--text-secondary);
            font-size: 0.875rem;
        }

        .btn {
            display: inline-block;
            padding: 0.75rem 1.5rem;
            border: none;
            border-radius: 0.5rem;
            text-decoration: none;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s ease;
            margin-right: 0.5rem;
            margin-bottom: 0.5rem;
        }

        .btn-primary { background: var(--accent-blue); color: white; }
        .btn-success { background: var(--accent-green); color: white; }
        .btn-warning { background: var(--accent-orange); color: white; }
        .btn-danger { background: var(--accent-red); color: white; }

        .form-group {
            margin-bottom: 1.5rem;
        }

        .form-group label {
            display: block;
            margin-bottom: 0.5rem;
            font-weight: 500;
            color: var(--text-secondary);
        }

        .form-group input, .form-group select, .form-group textarea {
            width: 100%;
            background: rgba(15, 20, 25, 0.7);
            border: 1px solid var(--border-color);
            border-radius: 0.5rem;
            padding: 0.875rem;
            color: var(--text-primary);
        }

        .form-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 1.5rem;
        }

        .alert {
            padding: 1rem;
            border-radius: 0.5rem;
            margin-bottom: 1rem;
        }

        .alert-success {
            background: rgba(16, 185, 129, 0.2);
            border: 1px solid var(--accent-green);
            color: var(--accent-green);
        }

        .alert-error {
            background: rgba(239, 68, 68, 0.2);
            border: 1px solid var(--accent-red);
            color: var(--accent-red);
        }

        .badge {
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 1rem;
            font-size: 0.75rem;
            font-weight: 600;
        }

        .badge-success { background: rgba(16, 185, 129, 0.2); color: var(--accent-green); }
        .badge-warning { background: rgba(245, 158, 11, 0.2); color: var(--accent-orange); }
        .badge-danger { background: rgba(239, 68, 68, 0.2); color: var(--accent-red); }

        @media (max-width: 768px) {
            .sidebar { transform: translateX(-100%); }
            .main-content { margin-left: 0; padding: 1rem; }
        }
    </style>
</head>
<body>
    <div class="dashboard">
        <nav class="sidebar">
            <div class="sidebar-header">
                <div class="logo">
                    <i class="fas fa-industry"></i>
                    {{ brand }}
                </div>
            </div>
            <ul class="sidebar-menu">
                <li class="menu-item {% if request.endpoint == 'dashboard' %}active{% endif %}">
                    <a href="/" class="menu-link">
                        <i class="fas fa-chart-line"></i> Dashboard
                    </a>
                </li>
                <li class="menu-item {% if 'ob' in request.endpoint %}active{% endif %}">
                    <a href="/ob-management" class="menu-link">
                        <i class="fas fa-file-excel"></i> OB Management
                    </a>
                </li>
                <li class="menu-item {% if 'production_orders' in request.endpoint %}active{% endif %}">
                    <a href="/production-orders" class="menu-link">
                        <i class="fas fa-clipboard-list"></i> Production Orders
                    </a>
                </li>
                <li class="menu-item {% if 'bundles' in request.endpoint %}active{% endif %}">
                    <a href="/bundles" class="menu-link">
                        <i class="fas fa-boxes"></i> Bundles
                    </a>
                </li>
                <li class="menu-item {% if 'workers' in request.endpoint %}active{% endif %}">
                    <a href="/workers" class="menu-link">
                        <i class="fas fa-users"></i> Workers
                    </a>
                </li>
                <li class="menu-item {% if 'scanning' in request.endpoint %}active{% endif %}">
                    <a href="/scanning" class="menu-link">
                        <i class="fas fa-qrcode"></i> Live Scanning
                    </a>
                </li>
                <li class="menu-item {% if 'reports' in request.endpoint %}active{% endif %}">
                    <a href="/reports" class="menu-link">
                        <i class="fas fa-chart-bar"></i> Reports
                    </a>
                </li>
            </ul>
        </nav>

        <main class="main-content">
            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, message in messages %}
                        <div class="alert alert-{{ 'success' if category == 'success' else 'error' }}">
                            {{ message }}
                        </div>
                    {% endfor %}
                {% endif %}
            {% endwith %}

            {% block content %}{% endblock %}
        </main>
    </div>
</body>
</html>
'''

# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------

@app.route('/')
def dashboard():
    """Main dashboard with live statistics"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get statistics
    cursor.execute("SELECT COUNT(*) FROM production_orders WHERE status='active'")
    active_orders = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM bundles WHERE status IN ('in_progress', 'created')")
    active_bundles = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM workers WHERE status='active'")
    active_workers = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM bundle_operations WHERE DATE(scanned_at) = DATE('now')")
    today_scans = cursor.fetchone()[0]

    cursor.execute("SELECT COALESCE(SUM(earnings), 0) FROM bundle_operations WHERE DATE(scanned_at) = DATE('now')")
    today_earnings = cursor.fetchone()[0]

    # Recent activities
    cursor.execute("""
        SELECT bo.bundle_no, w.name, bo.operation_desc, bo.pieces_completed, 
               bo.earnings, bo.scanned_at
        FROM bundle_operations bo
        JOIN workers w ON w.worker_id = bo.worker_id
        ORDER BY bo.scanned_at DESC
        LIMIT 10
    """)
    recent_activities = cursor.fetchall()

    conn.close()

    template = BASE_TEMPLATE + '''
    {% block content %}
    <div class="card">
        <h1><i class="fas fa-chart-line"></i> Production Dashboard</h1>
        <p>Real-time production monitoring - All earnings in Rupees (₹)</p>
    </div>

    <div class="stats-grid">
        <div class="stat-card">
            <div class="stat-value">{{ active_orders }}</div>
            <div class="stat-label">Active Orders</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{{ active_bundles }}</div>
            <div class="stat-label">Active Bundles</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{{ active_workers }}</div>
            <div class="stat-label">Active Workers</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{{ today_scans }}</div>
            <div class="stat-label">Today's Scans</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">₹{{ "%.2f"|format(today_earnings) }}</div>
            <div class="stat-label">Today's Earnings</div>
        </div>
    </div>

    <div class="card">
        <h2><i class="fas fa-clock"></i> Recent Activities</h2>
        {% if recent_activities %}
            <table>
                <thead>
                    <tr>
                        <th>Bundle</th>
                        <th>Worker</th>
                        <th>Operation</th>
                        <th>Pieces</th>
                        <th>Earnings (₹)</th>
                        <th>Time</th>
                    </tr>
                </thead>
                <tbody>
                    {% for activity in recent_activities %}
                    <tr>
                        <td><strong>{{ activity[0] }}</strong></td>
                        <td>{{ activity[1] }}</td>
                        <td>{{ activity[2][:40] }}...</td>
                        <td>{{ activity[3] }}</td>
                        <td style="color: var(--accent-green);">₹{{ "%.2f"|format(activity[4]) }}</td>
                        <td>{{ activity[5] }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        {% else %}
            <p>No recent activities</p>
        {% endif %}
    </div>
    {% endblock %}
    '''

    return render_template_string(template,
                                brand=APP_BRAND,
                                active_orders=active_orders,
                                active_bundles=active_bundles,
                                active_workers=active_workers,
                                today_scans=today_scans,
                                today_earnings=today_earnings,
                                recent_activities=recent_activities)

@app.route('/ob-management')
def ob_management():
    """Operation Breakdown management"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT style_no, COUNT(*) as op_count, SUM(std_min) as total_time,
               MIN(uploaded_at) as uploaded_date
        FROM operation_breakdown 
        GROUP BY style_no
        ORDER BY uploaded_date DESC
    """)
    ob_styles = cursor.fetchall()

    conn.close()

    template = BASE_TEMPLATE + '''
    {% block content %}
    <div class="card">
        <h1><i class="fas fa-file-excel"></i> Operation Breakdown Management</h1>
        <p>Upload and manage operation breakdowns (Excel .xlsx files)</p>

        <form method="POST" action="/upload-ob" enctype="multipart/form-data" style="margin-top: 2rem;">
            <div class="form-grid">
                <div class="form-group">
                    <label>Select Excel File (.xlsx)</label>
                    <input type="file" name="ob_file" accept=".xlsx,.xls" required>
                </div>
                <div class="form-group">
                    <label>Style Number</label>
                    <input type="text" name="style_no" placeholder="e.g., SAINTX MENS BLAZER" required>
                </div>
            </div>
            <button type="submit" class="btn btn-primary">
                <i class="fas fa-upload"></i> Upload OB
            </button>
        </form>
    </div>

    <div class="card">
        <h2>Uploaded Operation Breakdowns</h2>
        {% if ob_styles %}
            <table>
                <thead>
                    <tr>
                        <th>Style Number</th>
                        <th>Operations</th>
                        <th>Total Time (Min)</th>
                        <th>Rate per Piece (₹)</th>
                        <th>Uploaded</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {% for style in ob_styles %}
                    <tr>
                        <td><strong>{{ style[0] }}</strong></td>
                        <td>{{ style[1] }}</td>
                        <td>{{ "%.2f"|format(style[2]) }}</td>
                        <td style="color: var(--accent-green);">₹{{ "%.2f"|format(style[2] * 0.50) }}</td>
                        <td>{{ style[3] }}</td>
                        <td>
                            <a href="/view-ob/{{ style[0] }}" class="btn btn-primary">View Details</a>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        {% else %}
            <p>No OB files uploaded yet. Upload your Excel operation breakdown to get started.</p>
        {% endif %}
    </div>
    {% endblock %}
    '''

    return render_template_string(template, brand=APP_BRAND, ob_styles=ob_styles)

@app.route('/upload-ob', methods=['POST'])
def upload_ob():
    """Upload OB Excel file"""
    if not PANDAS_AVAILABLE:
        flash('Excel processing not available. Please install pandas and openpyxl.', 'error')
        return redirect('/ob-management')

    if 'ob_file' not in request.files:
        flash('No file selected', 'error')
        return redirect('/ob-management')

    file = request.files['ob_file']
    style_no = request.form.get('style_no', '').strip()

    if not file.filename or not style_no:
        flash('File and Style Number are required', 'error')
        return redirect('/ob-management')

    try:
        # Read Excel file directly from memory
        df = pd.read_excel(file)

        # Validate columns
        required_cols = ['SeqNo', 'OpNo', 'Description', 'Machine', 'SubSection', 'StdMin']
        missing_cols = [col for col in required_cols if col not in df.columns]

        if missing_cols:
            flash(f'Missing columns: {", ".join(missing_cols)}', 'error')
            return redirect('/ob-management')

        # Insert into database
        conn = get_db_connection()
        cursor = conn.cursor()

        # Clear existing OB for this style
        cursor.execute("DELETE FROM operation_breakdown WHERE style_no = ?", (style_no,))

        # Insert new data
        total_time = 0
        for _, row in df.iterrows():
            std_min = float(row.get('StdMin', 0))
            total_time += std_min
            cursor.execute("""
                INSERT INTO operation_breakdown 
                (seq_no, op_no, description, machine, subsection, std_min, 
                 product, skill, grade, style_no) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                int(row.get('SeqNo', 0)),
                str(row.get('OpNo', '')),
                str(row.get('Description', '')),
                str(row.get('Machine', '')),
                str(row.get('SubSection', '')),
                std_min,
                str(row.get('Product', '')),
                str(row.get('Skill', 'MEDIUM')),
                str(row.get('Grade', 'Operator')),
                style_no
            ))

        conn.commit()
        conn.close()

        total_earnings = total_time * BASE_RATE_PER_MINUTE
        flash(f'OB uploaded successfully for {style_no} - {len(df)} operations, {total_time:.2f} minutes total, ₹{total_earnings:.2f} per piece', 'success')

    except Exception as e:
        flash(f'Error processing file: {str(e)}', 'error')

    return redirect('/ob-management')

@app.route('/production-orders')
def production_orders():
    """Production Orders page"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT order_no, style_no, style_name, buyer, order_qty, delivery_date, 
               status, created_at
        FROM production_orders 
        ORDER BY created_at DESC
    """)
    orders = cursor.fetchall()

    conn.close()

    template = BASE_TEMPLATE + '''
    {% block content %}
    <div class="card">
        <h1><i class="fas fa-clipboard-list"></i> Production Orders</h1>
        <a href="/create-production-order" class="btn btn-primary">
            <i class="fas fa-plus"></i> Create New Order
        </a>
    </div>

    <div class="card">
        <h2>All Production Orders</h2>
        {% if orders %}
            <table>
                <thead>
                    <tr>
                        <th>Order No</th>
                        <th>Style</th>
                        <th>Buyer</th>
                        <th>Quantity</th>
                        <th>Status</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {% for order in orders %}
                    <tr>
                        <td><strong>{{ order[0] }}</strong></td>
                        <td>{{ order[1] }}</td>
                        <td>{{ order[3] or '-' }}</td>
                        <td>{{ order[4] }} pieces</td>
                        <td><span class="badge badge-success">{{ order[6] }}</span></td>
                        <td>
                            <a href="/create-bundles/{{ order[0] }}" class="btn btn-success">Create Bundles</a>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        {% else %}
            <p>No production orders created yet</p>
        {% endif %}
    </div>
    {% endblock %}
    '''

    return render_template_string(template, brand=APP_BRAND, orders=orders)

@app.route('/create-production-order', methods=['GET', 'POST'])
def create_production_order():
    """Create production order"""
    if request.method == 'POST':
        order_no = request.form.get('order_no', '').strip()
        style_no = request.form.get('style_no', '').strip()
        style_name = request.form.get('style_name', '').strip()
        buyer = request.form.get('buyer', '').strip()
        order_qty = int(request.form.get('order_qty', 0))
        delivery_date = request.form.get('delivery_date', '')

        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO production_orders 
                (order_no, style_no, style_name, buyer, order_qty, delivery_date)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (order_no, style_no, style_name, buyer, order_qty, delivery_date))

            conn.commit()
            conn.close()

            flash(f'Production order {order_no} created successfully with {order_qty} pieces', 'success')
            return redirect('/production-orders')

        except sqlite3.IntegrityError:
            flash('Order number already exists', 'error')
        except Exception as e:
            flash(f'Error creating order: {str(e)}', 'error')

    template = BASE_TEMPLATE + '''
    {% block content %}
    <div class="card">
        <h1><i class="fas fa-plus"></i> Create Production Order</h1>

        <form method="POST" style="margin-top: 2rem;">
            <div class="form-grid">
                <div class="form-group">
                    <label>Order Number *</label>
                    <input type="text" name="order_no" required placeholder="650010011410">
                </div>
                <div class="form-group">
                    <label>Style Number *</label>
                    <input type="text" name="style_no" required placeholder="SAINTX MENS BLAZER">
                </div>
                <div class="form-group">
                    <label>Style Name</label>
                    <input type="text" name="style_name" placeholder="Men's Partially Lined Blazer">
                </div>
                <div class="form-group">
                    <label>Buyer</label>
                    <input type="text" name="buyer" placeholder="BANSWARA GARMENTS">
                </div>
                <div class="form-group">
                    <label>Total Quantity *</label>
                    <input type="number" name="order_qty" required min="1" placeholder="1119">
                </div>
                <div class="form-group">
                    <label>Delivery Date</label>
                    <input type="date" name="delivery_date">
                </div>
            </div>

            <button type="submit" class="btn btn-primary">Create Order</button>
            <a href="/production-orders" class="btn btn-secondary">Cancel</a>
        </form>
    </div>
    {% endblock %}
    '''

    return render_template_string(template, brand=APP_BRAND)

@app.route('/bundles')
def bundles():
    """Bundles management page"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT b.bundle_no, b.order_no, b.style_no, b.color, b.bundle_qty, 
               b.current_operation, b.status
        FROM bundles b
        ORDER BY b.created_at DESC
    """)
    bundles_list = cursor.fetchall()

    conn.close()

    template = BASE_TEMPLATE + '''
    {% block content %}
    <div class="card">
        <h1><i class="fas fa-boxes"></i> Bundle Management</h1>
        <p>Manage production bundles and generate QR codes</p>
    </div>

    <div class="card">
        <h2>All Bundles</h2>
        {% if bundles_list %}
            <table>
                <thead>
                    <tr>
                        <th>Bundle No</th>
                        <th>Order No</th>
                        <th>Style</th>
                        <th>Color</th>
                        <th>Qty</th>
                        <th>Status</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {% for bundle in bundles_list %}
                    <tr>
                        <td><strong>{{ bundle[0] }}</strong></td>
                        <td>{{ bundle[1] }}</td>
                        <td>{{ bundle[2] }}</td>
                        <td>{{ bundle[3] or '-' }}</td>
                        <td>{{ bundle[4] }} pieces</td>
                        <td><span class="badge badge-success">{{ bundle[6] }}</span></td>
                        <td>
                            <a href="/bundle-qr/{{ bundle[0] }}" class="btn btn-success" target="_blank">
                                <i class="fas fa-qrcode"></i> QR Code
                            </a>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        {% else %}
            <p>No bundles created yet. Create production orders first.</p>
        {% endif %}
    </div>
    {% endblock %}
    '''

    return render_template_string(template, brand=APP_BRAND, bundles_list=bundles_list)

@app.route('/workers')
def workers():
    """Workers management"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT worker_id, name, department, skill_level, hourly_rate, status
        FROM workers 
        ORDER BY name
    """)
    workers_list = cursor.fetchall()

    conn.close()

    template = BASE_TEMPLATE + '''
    {% block content %}
    <div class="card">
        <h1><i class="fas fa-users"></i> Workers Management</h1>
        <p>Manage workers and generate QR codes for scanning</p>

        <form method="POST" action="/add-worker" style="margin-top: 2rem;">
            <div class="form-grid">
                <div class="form-group">
                    <label>Worker ID *</label>
                    <input type="text" name="worker_id" required placeholder="W006">
                </div>
                <div class="form-group">
                    <label>Name *</label>
                    <input type="text" name="name" required placeholder="Worker Name">
                </div>
                <div class="form-group">
                    <label>Department</label>
                    <select name="department">
                        <option value="SLEEVE">SLEEVE</option>
                        <option value="BODY">BODY</option>
                        <option value="COLLAR">COLLAR</option>
                        <option value="LINING">LINING</option>
                        <option value="ASSE-1">ASSE-1</option>
                        <option value="ASSE-2">ASSE-2</option>
                        <option value="FLAP">FLAP</option>
                        <option value="BACK">BACK</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>Skill Level</label>
                    <select name="skill_level">
                        <option value="MEDIUM">MEDIUM</option>
                        <option value="HIGH">HIGH</option>
                        <option value="LOW">LOW</option>
                    </select>
                </div>
            </div>
            <button type="submit" class="btn btn-primary">Add Worker</button>
        </form>
    </div>

    <div class="card">
        <h2>All Workers</h2>
        <table>
            <thead>
                <tr>
                    <th>Worker ID</th>
                    <th>Name</th>
                    <th>Department</th>
                    <th>Skill Level</th>
                    <th>Rate (₹/hr)</th>
                    <th>Status</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>
                {% for worker in workers_list %}
                <tr>
                    <td><strong>{{ worker[0] }}</strong></td>
                    <td>{{ worker[1] }}</td>
                    <td><span class="badge badge-success">{{ worker[2] }}</span></td>
                    <td>{{ worker[3] }}</td>
                    <td style="color: var(--accent-green);">₹{{ "%.2f"|format(worker[4]) }}</td>
                    <td><span class="badge badge-success">{{ worker[5] }}</span></td>
                    <td>
                        <a href="/worker-qr/{{ worker[0] }}" class="btn btn-success" target="_blank">
                            <i class="fas fa-qrcode"></i> QR
                        </a>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    {% endblock %}
    '''

    return render_template_string(template, brand=APP_BRAND, workers_list=workers_list)

@app.route('/add-worker', methods=['POST'])
def add_worker():
    """Add new worker"""
    worker_id = request.form.get('worker_id', '').strip()
    name = request.form.get('name', '').strip()
    department = request.form.get('department', '')
    skill_level = request.form.get('skill_level', 'MEDIUM')

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO workers (worker_id, name, department, skill_level)
            VALUES (?, ?, ?, ?)
        """, (worker_id, name, department, skill_level))
        conn.commit()
        conn.close()
        flash(f'Worker {worker_id} ({name}) added successfully', 'success')
    except sqlite3.IntegrityError:
        flash('Worker ID already exists', 'error')

    return redirect('/workers')

@app.route('/scanning')
def scanning():
    """Live scanning dashboard"""
    template = BASE_TEMPLATE + '''
    {% block content %}
    <div class="card">
        <h1><i class="fas fa-qrcode"></i> Live Scanning Dashboard</h1>
        <p>Real-time production scanning monitoring</p>
    </div>

    <div class="card">
        <h2><i class="fas fa-mobile-alt"></i> Mobile Scanning Instructions</h2>
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 2rem;">
            <div>
                <h3>For Workers:</h3>
                <ol>
                    <li>Scan your worker QR code to login</li>
                    <li>Scan bundle QR code to complete operation</li>
                    <li>System calculates earnings in ₹ automatically</li>
                    <li>Check your daily earnings in real-time</li>
                </ol>

                <h3 style="margin-top: 2rem;">Rate Calculation:</h3>
                <p><strong>Formula:</strong> Earnings = Standard Minutes × ₹0.50 × Efficiency</p>
                <p><strong>Example:</strong> Loading Sleeve (0.28 min) = ₹0.14 per piece</p>
            </div>
            <div>
                <h3>API Endpoint:</h3>
                <code style="background: rgba(0,0,0,0.3); padding: 1rem; border-radius: 0.5rem; display: block;">POST /api/scan</code>
                <pre style="margin-top: 1rem; padding: 1rem; background: rgba(0,0,0,0.3); border-radius: 0.5rem; font-size: 0.8rem;">
{
  "secret": "garment_erp_2024_secret",
  "scan_data": "WORKER:W001|Name",
  "worker_id": "W001"
}

Response:
{
  "ok": true,
  "type": "bundle_scanned",
  "earnings": 7.70,
  "message": "Bundle completed! Earned ₹7.70"
}
                </pre>
            </div>
        </div>
    </div>

    <div class="card">
        <h2><i class="fas fa-info-circle"></i> QR Code Formats</h2>
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 2rem;">
            <div>
                <h3>Worker QR Code:</h3>
                <code>WORKER:W001|Rajesh Kumar</code>
                <p style="margin-top: 1rem; color: var(--text-secondary);">Used for worker login/logout</p>
            </div>
            <div>
                <h3>Bundle QR Code:</h3>
                <code>BUNDLE:650010011410-001|650010011410|SAINTX</code>
                <p style="margin-top: 1rem; color: var(--text-secondary);">Used for operation completion</p>
            </div>
        </div>
    </div>
    {% endblock %}
    '''

    return render_template_string(template, brand=APP_BRAND)

@app.route('/reports')
def reports():
    """Reports dashboard"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Worker performance summary
    cursor.execute("""
        SELECT w.worker_id, w.name, w.department, 
               COUNT(bo.id) as operations, SUM(bo.pieces_completed) as pieces,
               SUM(bo.earnings) as earnings
        FROM workers w
        LEFT JOIN bundle_operations bo ON bo.worker_id = w.worker_id AND bo.status = 'completed'
        WHERE w.status = 'active'
        GROUP BY w.worker_id, w.name, w.department
        ORDER BY earnings DESC
        LIMIT 10
    """)
    worker_performance = cursor.fetchall()

    conn.close()

    template = BASE_TEMPLATE + '''
    {% block content %}
    <div class="card">
        <h1><i class="fas fa-chart-bar"></i> Reports & Analytics</h1>
        <p>Production reports and analytics - All values in Rupees (₹)</p>

        <div style="margin-top: 2rem;">
            <a href="/export-workers" class="btn btn-primary">
                <i class="fas fa-download"></i> Export Workers CSV
            </a>
            <a href="/export-operations" class="btn btn-success">
                <i class="fas fa-download"></i> Export Operations CSV
            </a>
            <a href="/export-earnings" class="btn btn-warning">
                <i class="fas fa-download"></i> Export Earnings CSV
            </a>
        </div>
    </div>

    <div class="card">
        <h2>Worker Performance Summary</h2>
        {% if worker_performance %}
            <table>
                <thead>
                    <tr>
                        <th>Worker</th>
                        <th>Department</th>
                        <th>Operations</th>
                        <th>Pieces</th>
                        <th>Total Earnings (₹)</th>
                    </tr>
                </thead>
                <tbody>
                    {% for worker in worker_performance %}
                    <tr>
                        <td>
                            <div><strong>{{ worker[0] }}</strong></div>
                            <div style="font-size: 0.875rem; color: var(--text-secondary);">{{ worker[1] }}</div>
                        </td>
                        <td><span class="badge badge-success">{{ worker[2] }}</span></td>
                        <td>{{ worker[3] or 0 }}</td>
                        <td>{{ worker[4] or 0 }}</td>
                        <td style="color: var(--accent-green); font-weight: bold;">₹{{ "%.2f"|format(worker[5] or 0) }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        {% else %}
            <p>No performance data available yet.</p>
        {% endif %}
    </div>
    {% endblock %}
    '''

    return render_template_string(template, brand=APP_BRAND, worker_performance=worker_performance)

# API Routes
@app.route('/api/scan', methods=['POST'])
def api_scan():
    """Mobile scanning API endpoint - All earnings in Rupees"""
    try:
        payload = request.get_json(force=True, silent=True) or {}

        # Verify device secret
        if payload.get('secret') != DEVICE_SECRET:
            return jsonify({
                'ok': False,
                'error': 'forbidden',
                'message': 'Invalid device secret'
            }), 403

        scan_data = payload.get('scan_data', '').strip()
        worker_id = payload.get('worker_id', '').strip()

        if not scan_data:
            return jsonify({
                'ok': False,
                'error': 'missing_data',
                'message': 'Scan data is required'
            }), 400

        conn = get_db_connection()
        cursor = conn.cursor()

        # Parse scan data
        if scan_data.startswith('WORKER:'):
            # Worker QR scan
            worker_data = scan_data.replace('WORKER:', '').split('|')
            scanned_worker_id = worker_data[0] if worker_data else ''

            cursor.execute("SELECT worker_id, name, department FROM workers WHERE worker_id = ?", (scanned_worker_id,))
            worker = cursor.fetchone()

            if not worker:
                return jsonify({
                    'ok': False,
                    'error': 'worker_not_found',
                    'message': 'Worker not found'
                })

            conn.close()
            return jsonify({
                'ok': True,
                'type': 'worker_login',
                'worker': {
                    'worker_id': worker[0],
                    'name': worker[1],
                    'department': worker[2]
                },
                'message': f'Worker {worker[1]} logged in successfully'
            })

        elif scan_data.startswith('BUNDLE:'):
            # Bundle QR scan
            bundle_data = scan_data.replace('BUNDLE:', '').split('|')
            bundle_no = bundle_data[0] if bundle_data else ''

            if not worker_id:
                return jsonify({
                    'ok': False,
                    'error': 'worker_required',
                    'message': 'Worker ID required for bundle scanning'
                }), 400

            # Verify bundle exists
            cursor.execute("SELECT bundle_no, bundle_qty FROM bundles WHERE bundle_no = ?", (bundle_no,))
            bundle = cursor.fetchone()

            if not bundle:
                return jsonify({
                    'ok': False,
                    'error': 'bundle_not_found',
                    'message': 'Bundle not found'
                })

            # Calculate earnings (simplified - using bundle qty * base rate)
            pieces = bundle[1]
            earnings_per_piece = BASE_RATE_PER_MINUTE * 0.5  # Simplified calculation
            total_earnings = pieces * earnings_per_piece

            cursor.execute("""
                INSERT INTO bundle_operations 
                (bundle_no, worker_id, op_no, operation_desc, pieces_completed, earnings)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (bundle_no, worker_id, 'OP001', 'Bundle Operation Completed', pieces, total_earnings))

            conn.commit()
            conn.close()

            return jsonify({
                'ok': True,
                'type': 'bundle_scanned',
                'bundle_no': bundle_no,
                'pieces_completed': pieces,
                'earnings': round(total_earnings, 2),
                'message': f'Bundle completed! Earned ₹{total_earnings:.2f}'
            })

        else:
            return jsonify({
                'ok': False,
                'error': 'invalid_scan',
                'message': 'Invalid QR code format'
            }), 400

    except Exception as e:
        return jsonify({
            'ok': False,
            'error': 'internal_error',
            'message': f'Server error: {str(e)}'
        }), 500

# Utility routes
@app.route('/bundle-qr/<bundle_no>')
def bundle_qr(bundle_no):
    """Generate QR code for bundle"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT bundle_no, order_no, style_no FROM bundles WHERE bundle_no = ?", (bundle_no,))
    bundle = cursor.fetchone()
    conn.close()

    if not bundle:
        return "Bundle not found", 404

    qr_text = f"BUNDLE:{bundle[0]}|{bundle[1]}|{bundle[2]}"
    qr = segno.make(qr_text, error='M')

    buf = io.BytesIO()
    qr.save(buf, kind='png', scale=10, border=2)
    buf.seek(0)

    return send_file(buf, mimetype='image/png', 
                    download_name=f'bundle_{bundle_no}_qr.png')

@app.route('/worker-qr/<worker_id>')
def worker_qr(worker_id):
    """Generate QR code for worker"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT worker_id, name FROM workers WHERE worker_id = ?", (worker_id,))
    worker = cursor.fetchone()
    conn.close()

    if not worker:
        return "Worker not found", 404

    qr_payload = f"WORKER:{worker[0]}|{worker[1]}"
    qr = segno.make(qr_payload, error='M')
    buf = io.BytesIO()
    qr.save(buf, kind='png', scale=10, border=2)
    buf.seek(0)

    return send_file(buf, mimetype='image/png',
                    download_name=f'worker_{worker_id}_qr.png')

@app.route('/create-bundles/<order_no>')
def create_bundles(order_no):
    """Create bundles for production order"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT style_no, order_qty FROM production_orders WHERE order_no = ?", (order_no,))
    order = cursor.fetchone()

    if not order:
        flash('Order not found', 'error')
        return redirect('/production-orders')

    try:
        # Create bundles (50 pieces each)
        bundle_size = 50
        total_qty = order[1]
        num_bundles = (total_qty + bundle_size - 1) // bundle_size  # Ceiling division

        for i in range(1, num_bundles + 1):
            bundle_qty = min(bundle_size, total_qty - (i-1) * bundle_size)
            bundle_no = f"{order_no}-{i:03d}"
            cursor.execute("""
                INSERT OR IGNORE INTO bundles 
                (bundle_no, order_no, style_no, bundle_qty)
                VALUES (?, ?, ?, ?)
            """, (bundle_no, order_no, order[0], bundle_qty))

        conn.commit()
        conn.close()
        flash(f'Created {num_bundles} bundles for order {order_no} ({total_qty} pieces total)', 'success')
    except Exception as e:
        flash(f'Error creating bundles: {str(e)}', 'error')

    return redirect('/bundles')

@app.route('/export-workers')
def export_workers():
    """Export workers as CSV"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM workers")
    workers = cursor.fetchall()
    conn.close()

    # Create CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Worker ID', 'Name', 'Department', 'Skill Level', 'Hourly Rate (₹)', 'Status'])

    for worker in workers:
        writer.writerow([worker[1], worker[2], worker[3], worker[4], worker[5], worker[6]])

    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'workers_{datetime.now().strftime("%Y%m%d")}.csv'
    )

# Template globals
@app.context_processor
def inject_globals():
    return {
        'brand': APP_BRAND
    }

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
