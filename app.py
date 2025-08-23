from flask import Flask, render_template, redirect, url_for, request, jsonify, Response, abort
from flask_cors import CORS
import psycopg2
import psycopg2.extras
import io
import os
import csv
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
    return psycopg2.connect(DB_URL, sslmode="require")

# ---------------- INIT & MIGRATE DB ---------------- #
def init_db():
    conn = get_conn()
    cur = conn.cursor()

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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_operations (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES workers(id) ON DELETE CASCADE,
            operation_name TEXT NOT NULL,
            barcode_value TEXT UNIQUE NOT NULL,
            assigned_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS scans (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES workers(id) ON DELETE CASCADE,
            operation_id INTEGER REFERENCES user_operations(id) ON DELETE CASCADE,
            scanned_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS production_logs (
            id SERIAL PRIMARY KEY,
            worker_id INTEGER REFERENCES workers(id) ON DELETE CASCADE,
            operation_id INTEGER REFERENCES user_operations(id) ON DELETE CASCADE,
            quantity INTEGER NOT NULL,
            status TEXT DEFAULT 'completed',
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()

def migrate_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("ALTER TABLE workers ADD COLUMN IF NOT EXISTS is_logged_in BOOLEAN DEFAULT FALSE;")
    cur.execute("ALTER TABLE workers ADD COLUMN IF NOT EXISTS last_login TIMESTAMPTZ;")
    cur.execute("ALTER TABLE workers ADD COLUMN IF NOT EXISTS last_logout TIMESTAMPTZ;")
    conn.commit()
    conn.close()

try:
    init_db()
    migrate_db()
except Exception as e:
    print("DB init/migrate error:", e)

# ---------------- ROUTES ---------------- #

@app.route("/healthz")
def healthz():
    return "ok", 200

@app.route('/')
def dashboard():
    return render_template('dashboard.html')

# --- Workers --- #
@app.route('/workers')
def workers():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, department, token_id, status, is_logged_in, last_login, last_logout, created_at
        FROM workers
        ORDER BY created_at DESC
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
        return "Name and Token ID required", 400

    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO workers (name, department, token_id) VALUES (%s, %s, %s)",
            (name, department, token_id)
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        return f"Error: {e}", 400
    finally:
        conn.close()
    return redirect(url_for('workers'))

# --- Worker QR --- #
@app.route('/qr/worker/<token_id>')
def worker_qr(token_id):
    factory = qrcode.image.svg.SvgImage
    img = qrcode.make(token_id, image_factory=factory)
    stream = io.BytesIO()
    img.save(stream)
    return Response(stream.getvalue(), mimetype='image/svg+xml')

# --- Sidebar pages --- #
@app.route('/operations')
def operations():
    return render_template('operations.html', operations=[])

@app.route('/production', methods=['GET', 'POST'])
def production():
    conn = get_conn()
    cur = conn.cursor()

    if request.method == 'POST':
        worker_id = request.form.get('worker_id')
        operation_id = request.form.get('operation_id')
        quantity = request.form.get('quantity')

        if not worker_id or not operation_id or not quantity:
            conn.close()
            return "All fields are required", 400

        try:
            cur.execute("""
                INSERT INTO production_logs (worker_id, operation_id, quantity)
                VALUES (%s, %s, %s)
            """, (worker_id, operation_id, quantity))
            conn.commit()
        except Exception as e:
            conn.rollback()
            conn.close()
            return f"Failed to log production: {e}", 500

    cur.execute("SELECT id, name FROM workers ORDER BY name")
    workers = cur.fetchall()
    cur.execute("SELECT id, operation_name FROM user_operations ORDER BY operation_name")
    operations = cur.fetchall()
    cur.execute("""
        SELECT pl.id, w.name, uo.operation_name, pl.quantity, pl.created_at, pl.status
        FROM production_logs pl
        JOIN workers w ON pl.worker_id = w.id
        JOIN user_operations uo ON pl.operation_id = uo.id
        ORDER BY pl.created_at DESC
        LIMIT 50
    """)
    logs = cur.fetchall()
    conn.close()
    return render_template('production.html', workers=workers, operations=operations, logs=logs)

@app.route('/reports')
def reports():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT w.name, w.department, COUNT(s.id) as total_scans
        FROM workers w
        LEFT JOIN scans s ON s.user_id = w.id
        GROUP BY w.id
        ORDER BY w.name
    """)
    rows = cur.fetchall()
    conn.close()
    return render_template('reports.html', reports=rows)

# --- Assign operations --- #
@app.route('/assign_operations', methods=['GET', 'POST'])
def assign_operations():
    conn = get_conn()
    cur = conn.cursor()
    if request.method == 'POST':
        user_id = request.form.get('user_id')
        operation_name = request.form.get('operation_name')
        if not user_id or not operation_name:
            conn.close()
            return "User and Operation Name required", 400
        barcode_value = f"{user_id}-{operation_name}-{int(datetime.now().timestamp())}"
        try:
            cur.execute("""
                INSERT INTO user_operations (user_id, operation_name, barcode_value)
                VALUES (%s, %s, %s)
            """, (user_id, operation_name, barcode_value))
            conn.commit()
        except Exception as e:
            conn.rollback()
            conn.close()
            return f"Failed: {e}", 500

    cur.execute("SELECT id, name, department FROM workers ORDER BY name")
    workers = cur.fetchall()
    cur.execute("""
        SELECT uo.id, w.name, uo.operation_name, uo.barcode_value, uo.assigned_at
        FROM user_operations uo
        JOIN workers w ON uo.user_id = w.id
        ORDER BY uo.assigned_at DESC
    """)
    assigned = cur.fetchall()
    conn.close()
    return render_template('assign_operation.html', workers=workers, assigned=assigned)

# --- QR for operation barcode --- #
@app.route('/qr/operation/<barcode_value>')
def operation_qr(barcode_value):
    factory = qrcode.image.svg.SvgImage
    img = qrcode.make(barcode_value, image_factory=factory)
    stream = io.BytesIO()
    img.save(stream)
    return Response(stream.getvalue(), mimetype='image/svg+xml')

# --- Login / Scan API --- #
@app.route('/scan', methods=['POST'])
def scan_login():
    data = request.get_json(silent=True) or {}
    token_id = data.get('token_id')
    secret = data.get('secret')
    if not token_id or not secret:
        return jsonify({'status':'error','message':'Missing token or secret'}),400
    if secret != DEVICE_SECRET:
        return jsonify({'status':'error','message':'Unauthorized'}),403

    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT id, name, department FROM workers WHERE token_id=%s", (token_id,))
    worker = cur.fetchone()
    if not worker:
        conn.close()
        return jsonify({'status':'error','message':'Worker not found'}),404

    # Log user in
    cur.execute("UPDATE workers SET is_logged_in=TRUE, last_login=CURRENT_TIMESTAMP WHERE id=%s", (worker['id'],))
    conn.commit()
    conn.close()

    return jsonify({
        'status':'success',
        'name': worker['name'],
        'department': worker['department'],
        'scans_today': 0,
        'earnings': 0.0
    })

# --- Logout API --- #
@app.route('/logout', methods=['POST'])
def logout():
    data = request.get_json(silent=True) or {}
    token_id = data.get('token_id')
    secret = data.get('secret')
    if secret != DEVICE_SECRET:
        return jsonify({'status':'error','message':'Unauthorized'}),403

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE workers SET is_logged_in=FALSE, last_logout=CURRENT_TIMESTAMP WHERE token_id=%s", (token_id,))
    conn.commit()
    conn.close()
    return jsonify({'status':'success'})

# --- Operation Scan API --- #
@app.route('/scan_operation', methods=['POST'])
def scan_operation():
    data = request.get_json(silent=True) or {}
    barcode_value = data.get('barcode')
    token_id = data.get('token_id')
    secret = data.get('secret')
    if not barcode_value or not token_id or not secret:
        return jsonify({'status':'error','message':'Missing fields'}),400
    if secret != DEVICE_SECRET:
        return jsonify({'status':'error','message':'Unauthorized'}),403

    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("""
        SELECT uo.id AS op_id, u.id AS user_id, u.name, u.department
        FROM user_operations uo
        JOIN workers u ON uo.user_id = u.id
        WHERE uo.barcode_value=%s AND u.token_id=%s
    """,(barcode_value, token_id))
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({'status':'error','message':'Invalid barcode'}),404

    cur.execute("INSERT INTO scans (user_id, operation_id) VALUES (%s,%s)",(row['user_id'],row['op_id']))
    cur.execute("SELECT COUNT(*) FROM scans WHERE user_id=%s AND DATE(scanned_at)=CURRENT_DATE",(row['user_id'],))
    scans_today = cur.fetchone()[0]
    earnings = scans_today * RATE_PER_PIECE
    conn.commit()
    conn.close()

    return jsonify({
        'status':'success',
        'name': row['name'],
        'department': row['department'],
        'scans_today': scans_today,
        'earnings': earnings
    })

# ---------------- RUN ---------------- #
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
