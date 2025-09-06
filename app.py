# app.py
from flask import Flask, render_template, redirect, url_for, request, jsonify, Response, abort
from flask_cors import CORS
import psycopg2
import psycopg2.extras
import io
import os
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal
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
RATE_PER_PIECE = Decimal(os.getenv("RATE_PER_PIECE", "5.0"))

def get_conn():
    return psycopg2.connect(DB_URL, sslmode="require")

# ---------------- HELPERS ---------------- #
def _require_secret(data):
    if (data or {}).get("secret") != DEVICE_SECRET:
        abort(403, description="Unauthorized")

def _strip_prefix(val, prefix):
    return val[len(prefix):] if val and val.startswith(prefix) else val

def _today_range(d: date):
    start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)

def _rate_sql_literal() -> str:
    # We will use this string inside f-strings; pass the default as a python float to keep SQL happy.
    return f"COALESCE(ops.rate_per_piece, {float(RATE_PER_PIECE)})"

# ---------------- INIT & MIGRATIONS ---------------- #
def init_db():
    conn = get_conn()
    cur = conn.cursor()

    # Workers
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

    # Assignments (legacy + extended)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_operations (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES workers(id) ON DELETE CASCADE,
            operation_name TEXT NOT NULL,
            barcode_value TEXT UNIQUE NOT NULL,
            assigned_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Scans
    cur.execute("""
        CREATE TABLE IF NOT EXISTS scans (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES workers(id) ON DELETE CASCADE,
            operation_id INTEGER REFERENCES user_operations(id) ON DELETE CASCADE,
            scanned_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            bundle_id INTEGER
        )
    """)

    # (Optional) manual production entries
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

    # Normalized order data (Pro-X style)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            order_no TEXT NOT NULL,
            style_no TEXT,
            color TEXT,
            size TEXT,
            qty INTEGER,
            line TEXT,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS operations (
            id SERIAL PRIMARY KEY,
            order_id INTEGER REFERENCES orders(id) ON DELETE CASCADE,
            operation_name TEXT NOT NULL,
            process TEXT,
            rate_per_piece NUMERIC(10,2) DEFAULT %s,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
    """, (RATE_PER_PIECE,))

    cur.execute("""
        CREATE TABLE IF NOT EXISTS bundles (
            id SERIAL PRIMARY KEY,
            order_id INTEGER REFERENCES orders(id) ON DELETE CASCADE,
            size TEXT,
            qty INTEGER,
            barcode_value TEXT UNIQUE NOT NULL,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Ensure new columns exist on older DBs
    cur.execute("ALTER TABLE IF EXISTS user_operations ADD COLUMN IF NOT EXISTS operation_id INTEGER REFERENCES operations(id) ON DELETE SET NULL")
    cur.execute("ALTER TABLE IF EXISTS user_operations ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE")
    # THIS fixes your UndefinedColumn error on old DBs:
    cur.execute("ALTER TABLE IF EXISTS operations ADD COLUMN IF NOT EXISTS rate_per_piece NUMERIC(10,2) DEFAULT %s", (RATE_PER_PIECE,))

    conn.commit()
    conn.close()

try:
    init_db()
except Exception as e:
    print("DB init/migrate error:", e)

# ---------------- BASIC PAGES ---------------- #
@app.route("/healthz")
def healthz():
    return "ok", 200

@app.route('/')
def dashboard():
    return render_template('dashboard.html')

# These names match what your templates are calling (to avoid BuildError)
@app.route('/operations')
def operations_page():
    # Render your existing template if you have one; otherwise a thin placeholder.
    try:
        return render_template('operations.html')
    except:
        return render_template('blank.html', title="Operations")

@app.route('/production')
def production():
    try:
        return render_template('production.html')
    except:
        return render_template('blank.html', title="Production")

@app.route('/assign_operations')
def assign_operations():
    try:
        return render_template('assign_operation.html')
    except:
        return render_template('blank.html', title="Assign Operations")

# Workers management UI (kept from your app)
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
    name = request.form.get('name','').strip()
    department = request.form.get('department','').strip()
    token_id = request.form.get('token_id','').strip()
    if not name or not token_id:
        return "Name and Token ID required", 400
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("INSERT INTO workers (name, department, token_id) VALUES (%s,%s,%s)", (name, department, token_id))
        conn.commit()
    except Exception as e:
        conn.rollback(); conn.close(); return f"Error: {e}", 400
    conn.close()
    return redirect(url_for('workers'))

# ---------------- QR (Worker & Bundle) ---------------- #
@app.get('/qr/worker/<token_id>')
def worker_qr(token_id):
    # Encode W:<token> so the scanner knows it's a worker card
    payload = f"W:{token_id}"
    factory = qrcode.image.svg.SvgImage
    img = qrcode.make(payload, image_factory=factory)
    stream = io.BytesIO(); img.save(stream)
    return Response(stream.getvalue(), mimetype='image/svg+xml')

@app.get('/qr/bundle/<barcode>')
def bundle_qr(barcode):
    # Encode B:<barcode> for bundle scans
    payload = f"B:{barcode}"
    factory = qrcode.image.svg.SvgImage
    img = qrcode.make(payload, image_factory=factory)
    stream = io.BytesIO(); img.save(stream)
    return Response(stream.getvalue(), mimetype='image/svg+xml')

# ---------------- ADMIN JSON APIS ---------------- #
@app.post("/orders")
def create_order():
    d = request.get_json(silent=True) or {}
    if not d.get("order_no"):
        return jsonify({"status":"error","message":"order_no required"}), 400
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""INSERT INTO orders (order_no, style_no, color, size, qty, line)
                   VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
                   (d.get("order_no"), d.get("style_no"), d.get("color"), d.get("size"), d.get("qty"), d.get("line")))
    oid = cur.fetchone()[0]; conn.commit(); conn.close()
    return jsonify({"status":"ok","id":oid})

@app.post("/operations_json")
def create_operation_json():
    d = request.get_json(silent=True) or {}
    if not d.get("order_id") or not d.get("operation_name"):
        return jsonify({"status":"error","message":"order_id and operation_name required"}), 400
    rate = Decimal(str(d.get("rate_per_piece") or RATE_PER_PIECE))
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""INSERT INTO operations (order_id, operation_name, process, rate_per_piece)
                   VALUES (%s,%s,%s,%s) RETURNING id""",
                   (d.get("order_id"), d.get("operation_name"), d.get("process"), rate))
    opid = cur.fetchone()[0]; conn.commit(); conn.close()
    return jsonify({"status":"ok","id":opid})

@app.post("/bundles")
def create_bundle():
    d = request.get_json(silent=True) or {}
    if not d.get("order_id") or not d.get("barcode_value"):
        return jsonify({"status":"error","message":"order_id and barcode_value required"}), 400
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""INSERT INTO bundles (order_id, size, qty, barcode_value)
                   VALUES (%s,%s,%s,%s) RETURNING id""",
                   (d.get("order_id"), d.get("size"), d.get("qty"), d.get("barcode_value")))
    bid = cur.fetchone()[0]; conn.commit(); conn.close()
    return jsonify({"status":"ok","id":bid})

@app.post("/assign_operation_json")
def assign_operation_json():
    d = request.get_json(silent=True) or {}
    if not d.get("user_id"):
        return jsonify({"status":"error","message":"user_id required"}), 400
    user_id = d.get("user_id")
    operation_id = d.get("operation_id")  # optional
    operation_name = d.get("operation_name") or "Operation"
    barcode_value = f"{user_id}-{operation_name}-{int(datetime.now().timestamp())}"

    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("UPDATE user_operations SET is_active=FALSE WHERE user_id=%s AND is_active=TRUE", (user_id,))
        cur.execute("""INSERT INTO user_operations (user_id, operation_name, barcode_value, operation_id, is_active)
                       VALUES (%s,%s,%s,%s,TRUE) RETURNING id""",
                    (user_id, operation_name, barcode_value, operation_id))
        uoid = cur.fetchone()[0]; conn.commit()
    except Exception as e:
        conn.rollback(); conn.close(); return jsonify({"status":"error","message":str(e)}), 500
    conn.close()
    return jsonify({"status":"ok","id":uoid,"barcode_value":barcode_value})

# ---------------- ESP32 APIs ---------------- #
@app.post('/scan')
def scan_login():
    data = request.get_json(silent=True) or {}
    _require_secret(data)
    token_id = _strip_prefix(data.get('token_id'), "W:")
    if not token_id:
        return jsonify({'status':'error','message':'Missing token'}), 400

    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT id,name,department FROM workers WHERE token_id=%s", (token_id,))
    worker = cur.fetchone()
    if not worker:
        conn.close()
        return jsonify({'status':'error','message':'Worker not found'}), 404

    cur.execute("UPDATE workers SET is_logged_in=TRUE, last_login=CURRENT_TIMESTAMP WHERE id=%s", (worker['id'],))

    # today totals
    start, end = _today_range(date.today())
    rate_sql = _rate_sql_literal()
    cur.execute(f"""
        SELECT COUNT(s.id) AS pcs, COALESCE(SUM({rate_sql}), 0) AS earn
        FROM scans s
        LEFT JOIN user_operations uo ON s.operation_id = uo.id
        LEFT JOIN operations ops ON uo.operation_id = ops.id
        WHERE s.user_id=%s AND s.scanned_at >= %s AND s.scanned_at < %s
    """, (worker['id'], start, end))
    row = cur.fetchone()
    conn.commit(); conn.close()

    return jsonify({'status':'success',
                    'name': worker['name'],
                    'department': worker['department'],
                    'scans_today': int(row['pcs'] or 0),
                    'earnings': float(row['earn'] or 0.0)})

@app.post('/logout')
def logout():
    data = request.get_json(silent=True) or {}
    _require_secret(data)
    token_id = _strip_prefix(data.get('token_id'), "W:")
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE workers SET is_logged_in=FALSE, last_logout=CURRENT_TIMESTAMP WHERE token_id=%s", (token_id,))
    conn.commit(); conn.close()
    return jsonify({'status':'success'})

@app.post('/scan_operation')
def scan_operation():
    data = request.get_json(silent=True) or {}
    _require_secret(data)

    token_id = _strip_prefix(data.get('token_id'), "W:")
    barcode_value = _strip_prefix(data.get('barcode'), "B:")
    if not token_id or not barcode_value:
        return jsonify({'status':'error','message':'Missing fields'}), 400

    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    # worker
    cur.execute("SELECT id,name,department FROM workers WHERE token_id=%s", (token_id,))
    worker = cur.fetchone()
    if not worker:
        conn.close()
        return jsonify({'status':'error','message':'Worker not found'}), 404

    # active assignment
    cur.execute("""SELECT id, operation_id FROM user_operations
                   WHERE user_id=%s AND is_active=TRUE
                   ORDER BY assigned_at DESC LIMIT 1""", (worker['id'],))
    uo = cur.fetchone()
    if not uo:
        # fallback: legacy assignment QR scan (if someone scanned the assignment QR directly)
        cur.execute("""SELECT id, operation_id FROM user_operations
                       WHERE barcode_value=%s ORDER BY assigned_at DESC LIMIT 1""", (barcode_value,))
        uo = cur.fetchone()
        if not uo:
            conn.close()
            return jsonify({'status':'error','message':'No active operation assigned or invalid barcode'}), 400

    # optional: look up bundle id by bundle barcode
    cur.execute("SELECT id FROM bundles WHERE barcode_value=%s", (barcode_value,))
    b = cur.fetchone()
    bundle_id = b['id'] if b else None

    # record scan
    cur.execute("""INSERT INTO scans (user_id, operation_id, scanned_at, bundle_id)
                   VALUES (%s,%s,CURRENT_TIMESTAMP,%s)""",
                   (worker['id'], uo['id'], bundle_id))

    # new totals
    start, end = _today_range(date.today())
    rate_sql = _rate_sql_literal()
    cur.execute(f"""
        SELECT COUNT(s.id) AS pcs, COALESCE(SUM({rate_sql}), 0) AS earn
        FROM scans s
        LEFT JOIN user_operations u ON s.operation_id=u.id
        LEFT JOIN operations ops ON u.operation_id=ops.id
        WHERE s.user_id=%s AND s.scanned_at >= %s AND s.scanned_at < %s
    """, (worker['id'], start, end))
    row = cur.fetchone()
    conn.commit(); conn.close()

    return jsonify({'status':'success',
                    'name': worker['name'],
                    'department': worker['department'],
                    'scans_today': int(row['pcs'] or 0),
                    'earnings': float(row['earn'] or 0.0)})

# ---------------- DASHBOARD APIS ---------------- #
@app.get("/api/stats")
def api_stats():
    d_str = request.args.get("date")
    d = date.fromisoformat(d_str) if d_str else date.today()
    start, end = _today_range(d)
    line = request.args.get("line")
    order_no = request.args.get("order")

    conn = get_conn(); cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    filters = ["s.scanned_at >= %s AND s.scanned_at < %s"]
    params = [start, end]
    join_order = ""

    if line and line != "all":
        filters.append("w.department=%s"); params.append(line)

    if order_no and order_no != "all":
        join_order = """
            LEFT JOIN user_operations uo2 ON s.operation_id = uo2.id
            LEFT JOIN operations ops2 ON uo2.operation_id = ops2.id
            LEFT JOIN orders ord2 ON ops2.order_id = ord2.id
        """
        filters.append("ord2.order_no=%s"); params.append(order_no)

    where = " AND ".join(filters)
    rate_sql = _rate_sql_literal()

    cur.execute(f"SELECT COUNT(s.id) AS pieces FROM scans s JOIN workers w ON s.user_id=w.id {join_order} WHERE {where}", params)
    total_pieces = int(cur.fetchone()["pieces"] or 0)

    cur.execute(f"""SELECT COALESCE(SUM({rate_sql}),0) AS earn
                    FROM scans s
                    LEFT JOIN user_operations uo ON s.operation_id = uo.id
                    LEFT JOIN operations ops ON uo.operation_id = ops.id
                    JOIN workers w ON s.user_id=w.id
                    {join_order} WHERE {where}""", params)
    total_earnings = float(cur.fetchone()["earn"] or 0.0)

    cur.execute("SELECT COUNT(*) FROM workers WHERE is_logged_in=TRUE")
    active_workers = int(cur.fetchone()[0])

    cur.execute(f"""SELECT COALESCE(AVG({rate_sql}), {float(RATE_PER_PIECE)}) AS avg_rate
                    FROM scans s
                    LEFT JOIN user_operations uo ON s.operation_id=uo.id
                    LEFT JOIN operations ops ON uo.operation_id=ops.id
                    WHERE s.scanned_at >= %s AND s.scanned_at < %s""", (start, end))
    average_rate = float(cur.fetchone()["avg_rate"] or float(RATE_PER_PIECE))

    cur.execute(f"""SELECT date_trunc('hour', s.scanned_at) AS h,
                           COUNT(s.id) AS pcs,
                           COALESCE(SUM({rate_sql}),0) AS earn
                    FROM scans s
                    LEFT JOIN user_operations uo ON s.operation_id=uo.id
                    LEFT JOIN operations ops ON uo.operation_id=ops.id
                    JOIN workers w ON s.user_id=w.id
                    {join_order} WHERE {where}
                    GROUP BY h ORDER BY h""", params)
    by_hour = [{"hour": r["h"].strftime("%H:00"), "pieces": int(r["pcs"]), "earnings": float(r["earn"])} for r in cur.fetchall()]

    cur.execute(f"""SELECT w.name AS worker, COUNT(s.id) AS pcs, COALESCE(SUM({rate_sql}),0) AS earn
                    FROM scans s
                    LEFT JOIN user_operations uo ON s.operation_id=uo.id
                    LEFT JOIN operations ops ON uo.operation_id=ops.id
                    JOIN workers w ON s.user_id=w.id
                    {join_order} WHERE {where}
                    GROUP BY w.name ORDER BY pcs DESC LIMIT 10""", params)
    top_workers = [{"name": r["worker"], "pieces": int(r["pcs"]), "earnings": float(r["earn"])} for r in cur.fetchall()]
    conn.close()

    return jsonify({
        "totalPiecesToday": total_pieces,
        "totalEarningsToday": total_earnings,
        "activeWorkers": active_workers,
        "averageRate": average_rate,
        "byHour": by_hour,
        "topWorkers": top_workers
    })

@app.get("/api/activities")
def api_activities():
    d_str = request.args.get("date")
    d = date.fromisoformat(d_str) if d_str else date.today()
    start, end = _today_range(d)
    line = request.args.get("line")
    order_no = request.args.get("order")

    conn = get_conn(); cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    filters = ["s.scanned_at >= %s AND s.scanned_at < %s"]
    params = [start, end]
    join_order = ""
    if line and line != "all":
        filters.append("w.department=%s"); params.append(line)
    if order_no and order_no != "all":
        join_order = """
            LEFT JOIN user_operations uo2 ON s.operation_id = uo2.id
            LEFT JOIN operations ops2 ON uo2.operation_id = ops2.id
            LEFT JOIN orders ord2 ON ops2.order_id = ord2.id
        """
        filters.append("ord2.order_no=%s"); params.append(order_no)
    where = " AND ".join(filters)
    rate_sql = _rate_sql_literal()

    cur.execute(f"""
        SELECT s.scanned_at AS ts, w.name AS worker, w.department AS line,
               ord.order_no AS order_no, ops.operation_name AS op,
               b.barcode_value AS bundle_code, {rate_sql} AS earn
        FROM scans s
        JOIN workers w ON s.user_id = w.id
        LEFT JOIN user_operations uo ON s.operation_id = uo.id
        LEFT JOIN operations ops ON uo.operation_id = ops.id
        LEFT JOIN bundles b ON s.bundle_id = b.id
        LEFT JOIN orders ord ON ops.order_id = ord.id
        {join_order}
        WHERE {where}
        ORDER BY s.scanned_at DESC
        LIMIT 100
    """, params)
    rows = cur.fetchall(); conn.close()

    data = [{"time": r["ts"].isoformat(), "worker": r["worker"], "line": r["line"],
             "order": r["order_no"], "operation": r["op"], "bundle": r["bundle_code"],
             "pieces": 1, "earnings": float(r["earn"])} for r in rows]
    return jsonify(data)

# ---------------- RUN ---------------- #
if __name__ == "__main__":
    # Local dev
    app.run(host="0.0.0.0", port=5000, debug=True)
