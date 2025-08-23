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
    # Render Postgres typically requires SSL
    return psycopg2.connect(DB_URL, sslmode="require")

# ---------------- INIT & MIGRATE DB ---------------- #
def init_db():
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

    # per-user assigned operations (barcode per user+operation)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_operations (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES workers(id) ON DELETE CASCADE,
            operation_name TEXT NOT NULL,
            barcode_value TEXT UNIQUE NOT NULL,
            assigned_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # scans of those barcodes
    cur.execute("""
        CREATE TABLE IF NOT EXISTS scans (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES workers(id) ON DELETE CASCADE,
            operation_id INTEGER REFERENCES user_operations(id) ON DELETE CASCADE,
            scanned_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
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
    # ensure tables exist (idempotent)
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
    conn.commit()
    conn.close()

# Initialize + attempt migration on import
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
    except psycopg2.IntegrityError:
        conn.rollback()
        return "Token ID must be unique", 400
    finally:
        conn.close()
    return redirect(url_for('workers'))

# --- Simple pages to satisfy sidebar links --- #
@app.route('/operations')
def operations():
    # Your existing operations.html expects `operations`.
    # Since we aren't using a separate 'operations' table now,
    # pass an empty list to keep the template happy.
    # (You can later populate this if you add a global operations table.)
    return render_template('operations.html', operations=[])

@app.route('/production')
def production():
    return render_template('production.html')

@app.route('/reports')
def reports():
    # Aggregate per worker for the reports page you already have
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

# --- Assign operations (create per-user barcodes) --- #
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

        # unique barcode value (user-operation-timestamp)
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

    # page data
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

# --- Scan API (device calls this) --- #
@app.route('/scan_operation', methods=['POST'])
def scan_operation():
    data = request.get_json(silent=True) or {}
    barcode_value = data.get('barcode')
    secret = data.get('secret')

    if not barcode_value or not secret:
        return jsonify({'status': 'error', 'message': 'Missing barcode or secret'}), 400
    if secret != DEVICE_SECRET:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403

    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute("""
        SELECT uo.id AS op_id, u.id AS user_id, u.name, u.department
        FROM user_operations uo
        JOIN workers u ON uo.user_id = u.id
        WHERE uo.barcode_value = %s
    """, (barcode_value,))
    row = cur.fetchone()

    if not row:
        conn.close()
        return jsonify({'status': 'error', 'message': 'Invalid barcode'}), 404

    cur.execute(
        "INSERT INTO scans (user_id, operation_id) VALUES (%s, %s)",
        (row['user_id'], row['op_id'])
    )

    cur.execute("""
        SELECT COUNT(*) FROM scans
        WHERE user_id = %s AND DATE(scanned_at) = CURRENT_DATE
    """, (row['user_id'],))
    scans_today = cur.fetchone()[0]
    earnings = scans_today * RATE_PER_PIECE

    conn.commit()
    conn.close()

    return jsonify({
        'status': 'success',
        'message': f"Scan recorded for {row['name']}",
        'user': row['name'],
        'department': row['department'],
        'scans_today': scans_today,
        'earnings': earnings
    })

# --- CSV reports --- #
@app.route('/download_report/<int:user_id>')
def download_report(user_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT u.name, u.department, COUNT(s.id) AS total_scans
        FROM workers u
        LEFT JOIN scans s ON s.user_id = u.id
        WHERE u.id = %s
        GROUP BY u.id
    """, (user_id,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return "User not found", 404

    si = io.StringIO()
    writer = csv.writer(si)
    writer.writerow(["Name", "Department", "Total Scans"])
    writer.writerow(row)
    si.seek(0)

    return Response(
        si.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename=report_user_{user_id}.csv"}
    )

# --- Admin migration --- #
@app.route('/admin/migrate')
def admin_migrate():
    secret = request.args.get("secret")
    if secret != DEVICE_SECRET:
        abort(403)
    try:
        migrate_db()
        return "Migration complete ✅", 200
    except Exception as e:
        return f"Migration error: {e}", 500

# ---------------- MAIN ---------------- #
if __name__ == "__main__":
    # On Render, the port is usually provided via PORT env, but your Procfile likely handles it.
    app.run(host="0.0.0.0", port=5000, debug=True)
