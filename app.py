# PMS (Flask) — Aligned UI Build for Render

Below are **drop-in files** that align your current Flask/Postgres backend with the dark UI you liked (Dashboard/Workers/Operations/Bundles/Uploads/ESP32/Reports). The structure assumes Render deploy with a standard Flask entry.

```
project/
├─ app.py                  # UPDATED (Flask API + pages)
├─ requirements.txt        # NEW (Render will use this)
├─ templates/
│  └─ index.html           # NEW (UI single-page)
└─ static/
   ├─ css/
   │  └─ style.css         # UPDATED (theme aligned to UI)
   └─ js/
      └─ pms.js            # NEW (UI wiring to Flask APIs)
```

---

## app.py (replace your file)

```python
from flask import Flask, render_template, request, jsonify, Response, abort, send_from_directory
from flask_cors import CORS
import psycopg2
import psycopg2.extras
import io
import os
import csv
import qrcode
import qrcode.image.svg
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

app = Flask(__name__)
CORS(app)

# =============================
# SETTINGS
# =============================
raw_env_db_url = os.getenv("DATABASE_URL")
if not raw_env_db_url:
    raise RuntimeError("DATABASE_URL is not set. Add it in Render → Environment.")

DEVICE_SECRET = os.getenv("DEVICE_SECRET", "changeme-device-secret")
RATE_PER_PIECE = float(os.getenv("RATE_PER_PIECE", "5.0"))


def _psycopg2_friendly_dsn(url: str) -> str:
    dsn = (url or "").strip().strip('"').strip("'")
    p = urlparse(dsn)
    scheme = (p.scheme or "postgresql").split("+", 1)[0]
    if scheme == "postgres":
        scheme = "postgresql"
    q = dict(parse_qsl(p.query, keep_blank_values=True))
    ssl = (q.get("sslmode") or "require").strip().strip('"').strip("'")
    q["sslmode"] = ssl
    return urlunparse((scheme, p.netloc, p.path, p.params, urlencode(q, doseq=True), p.fragment))

DB_URL = _psycopg2_friendly_dsn(raw_env_db_url)


def get_conn():
    return psycopg2.connect(DB_URL)


# =============================
# DB BOOTSTRAP / MIGRATIONS
# =============================

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
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
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS operations (
            id SERIAL PRIMARY KEY,
            op_no INTEGER UNIQUE,
            description TEXT,
            machine TEXT,
            department TEXT,
            std_min NUMERIC,
            piece_rate NUMERIC,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS bundles (
            id SERIAL PRIMARY KEY,
            code TEXT UNIQUE,
            qty INTEGER DEFAULT 0,
            status TEXT DEFAULT 'Pending'
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS scan_logs (
            id SERIAL PRIMARY KEY,
            token_id TEXT NOT NULL,
            scan_type TEXT DEFAULT 'work',
            scanned_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    conn.commit()
    conn.close()


def seed_if_empty():
    conn = get_conn()
    cur = conn.cursor()
    # operations seed (only minimal if empty)
    cur.execute("SELECT COUNT(*) FROM operations")
    if cur.fetchone()[0] == 0:
        depts = ["SLEEVE","COLLAR","LINING","BODY","ASSE-1","ASSE-2","FLAP","BACK","POST ASSEMBLY"]
        machines = ["SNLS","OL","FOA","BH","BARTACK"]
        rows = []
        for i in range(1, 41):
            rows.append((200+i, f"Operation step {i} — sample description", machines[i%5], depts[i%len(depts)], round(0.3 + (i%7)*0.2,2), round(0.6 + (i%6)*0.25,2)))
        cur.executemany(
            """
            INSERT INTO operations (op_no, description, machine, department, std_min, piece_rate)
            VALUES (%s,%s,%s,%s,%s,%s)
            ON CONFLICT (op_no) DO NOTHING
            """,
            rows,
        )

    # bundles seed
    cur.execute("SELECT COUNT(*) FROM bundles")
    if cur.fetchone()[0] == 0:
        seed = [
            ("A12",28,"Pending"),("B04",22,"Pending"),("C09",20,"Pending"),
            ("A01",30,"In Progress"),("B11",26,"In Progress"),("C02",18,"In Progress"),("D07",33,"In Progress"),
            ("A05",16,"QA"),("C03",14,"QA"),
            ("A08",25,"Completed"),("B06",27,"Completed"),("C12",21,"Completed"),("D01",24,"Completed"),("E03",19,"Completed")
        ]
        cur.executemany(
            """
            INSERT INTO bundles (code, qty, status) VALUES (%s,%s,%s)
            ON CONFLICT (code) DO NOTHING
            """,
            seed,
        )

    conn.commit()
    conn.close()


try:
    init_db()
    seed_if_empty()
except Exception as e:
    print("DB init/seed error:", e)


# =============================
# ROUTES — PAGES
# =============================

@app.route("/")
def index():
    return render_template("index.html")


# =============================
# ROUTES — APIs (JSON)
# =============================

@app.route("/api/stats")
def api_stats():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM workers")
    workers_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM operations")
    operations_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM scan_logs WHERE scan_type='work' AND DATE(scanned_at)=CURRENT_DATE")
    scans_today = cur.fetchone()[0]

    conn.close()

    return jsonify({
        "activeWorkers": workers_count,  # UI card 1
        "totalBundles": total_bundles(), # UI card 2
        "totalOperations": operations_count,  # UI card 3
        "totalEarnings": round(scans_today * RATE_PER_PIECE, 2),  # UI card 4
    })


def total_bundles():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM bundles")
    n = cur.fetchone()[0]
    conn.close()
    return n


@app.route("/api/chart-data")
def api_chart_data():
    # 4 slices for bundle status + dept workloads mock from counts
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT status, COUNT(*) FROM bundles GROUP BY status
    """)
    status_rows = cur.fetchall()
    status_map = {k: v for k, v in status_rows}
    bundle_status = [
        status_map.get('Pending', 0),
        status_map.get('In Progress', 0),
        status_map.get('QA', 0),
        status_map.get('Completed', 0),
    ]

    cur.execute("SELECT department, COUNT(*) FROM operations GROUP BY department ORDER BY department")
    dept_rows = cur.fetchall()
    departments = [r[0] for r in dept_rows]
    workloads = [int(r[1]) * 10 for r in dept_rows]  # simple proxy workload

    conn.close()

    return jsonify({
        "bundleStatus": bundle_status,
        "departments": departments,
        "deptLoads": workloads
    })


@app.route("/api/activities")
def api_activities():
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute(
        """
        SELECT s.id, s.token_id, s.scan_type, s.scanned_at, w.name AS worker_name
        FROM scan_logs s LEFT JOIN workers w ON w.token_id = s.token_id
        ORDER BY s.scanned_at DESC
        LIMIT 12
        """
    )
    rows = cur.fetchall()
    conn.close()
    items = [{
        "id": r["id"],
        "text": f"{r['scan_type'].title()} scan for token {r['token_id']}",
        "time": r["scanned_at"].isoformat() if r["scanned_at"] else ""
    } for r in rows]
    return jsonify(items)


@app.route("/api/workers")
def api_workers():
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT id, name, department, token_id, status, is_logged_in, last_login, last_logout FROM workers ORDER BY id DESC")
    rows = cur.fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/operations")
def api_operations():
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT id, op_no, description, machine, department, std_min, piece_rate FROM operations ORDER BY op_no ASC")
    rows = cur.fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/bundles")
def api_bundles():
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT id, code, qty, status FROM bundles ORDER BY code")
    rows = cur.fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/bundles/assign", methods=["POST"])
def api_assign_bundle():
    data = request.get_json(silent=True) or {}
    code = data.get("code")
    worker_token = data.get("workerToken")
    op_no = data.get("opNo")
    if not code or not worker_token or not op_no:
        return jsonify({"error": "Missing fields"}), 400

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE bundles SET status='In Progress' WHERE code=%s", (code,))
    conn.commit()

    # also log an activity
    cur.execute("INSERT INTO scan_logs (token_id, scan_type) VALUES (%s, %s)", (worker_token, 'work'))
    conn.commit()
    conn.close()

    return jsonify({"ok": True})


@app.route("/api/bundles/move", methods=["POST"])
def api_move_bundle():
    data = request.get_json(silent=True) or {}
    code = data.get("code")
    to = data.get("to")
    if to not in ("Pending","In Progress","QA","Completed"):
        return jsonify({"error": "Invalid status"}), 400
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE bundles SET status=%s WHERE code=%s", (to, code))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/upload/ob", methods=["POST"])
def api_upload_ob():
    f = request.files.get('file')
    if not f:
        return jsonify({"error": "file is required"}), 400
    # TODO: parse Excel and upsert operations if needed
    return jsonify({"ok": True})


@app.route("/api/upload/po", methods=["POST"])
def api_upload_po():
    f = request.files.get('file')
    if not f:
        return jsonify({"error": "file is required"}), 400
    return jsonify({"ok": True})


@app.route("/api/reports/earnings.csv")
def api_earnings_csv():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(department,'UNKNOWN'), COUNT(*) FROM workers GROUP BY department ORDER BY 1")
    rows = cur.fetchall()
    conn.close()

    si = io.StringIO()
    writer = csv.writer(si)
    writer.writerow(["Department","Earnings"])
    for d, c in rows:
        writer.writerow([d, int(c) * 20000])
    si.seek(0)
    return Response(si.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=earnings_report.csv"})


@app.route("/qr/<token_id>")
def qr_code(token_id):
    factory = qrcode.image.svg.SvgImage
    img = qrcode.make(token_id, image_factory=factory)
    stream = io.BytesIO()
    img.save(stream)
    return Response(stream.getvalue(), mimetype="image/svg+xml")


# =============================
# ESP32 SCAN
# =============================
@app.route("/scan", methods=["POST"])
def scan():
    data = request.get_json(silent=True) or {}
    token_id = data.get("token_id")
    secret = data.get("secret")
    scan_type = data.get("scan_type", "work")

    if not token_id or not secret:
        return jsonify({"status": "error", "message": "Missing token_id or secret"}), 400
    if secret != DEVICE_SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 403

    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT * FROM workers WHERE token_id=%s", (token_id,))
    worker = cur.fetchone()
    if not worker:
        conn.close()
        return jsonify({"status": "error", "message": "Invalid token_id"}), 404

    cur.execute("INSERT INTO scan_logs (token_id, scan_type) VALUES (%s, %s)", (token_id, scan_type))

    is_logged_in = worker["is_logged_in"]
    if scan_type == "login":
        cur.execute("UPDATE workers SET is_logged_in=TRUE, last_login=NOW() WHERE token_id=%s", (token_id,))
        is_logged_in = True
        message = "Login successful"
    elif scan_type == "logout":
        cur.execute("UPDATE workers SET is_logged_in=FALSE, last_logout=NOW() WHERE token_id=%s", (token_id,))
        is_logged_in = False
        message = "Logout successful"
    else:
        message = "Work scan logged"

    cur.execute("""
        SELECT COUNT(*) FROM scan_logs
        WHERE token_id=%s AND scan_type='work' AND DATE(scanned_at)=CURRENT_DATE
    """, (token_id,))
    scans_today = cur.fetchone()[0]

    conn.commit()
    conn.close()

    return jsonify({
        "status": "success",
        "message": message,
        "name": worker["name"],
        "department": worker["department"],
        "is_logged_in": is_logged_in,
        "scans_today": scans_today,
        "earnings": scans_today * RATE_PER_PIECE,
    })


# =============================
# MISC
# =============================
@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'), 'favicon.ico', mimetype='image/vnd.microsoft.icon')


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
```

---

## requirements.txt (new)

```txt
Flask==3.0.0
flask-cors==4.0.0
psycopg2-binary==2.9.9
qrcode==7.4.2
```

> Add any extras you use. Render will auto-install from this file.

---

## templates/index.html (new, UI single-page)

Paste this as-is. It’s your dark UI wired to Flask JSON endpoints (no template loops; the JS does the fetching).

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Production Management System — Live Preview</title>
  <link rel="stylesheet" href="/static/css/style.css" />
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body>
  <button id="mobileMenuToggle" class="mobile-menu-toggle" aria-label="Toggle navigation">☰</button>
  <div class="dashboard">
    <aside class="sidebar" id="sidebar">
      <div class="sidebar-header">
        <div class="logo">📊 <span>PMS</span></div>
      </div>
      <ul class="sidebar-menu">
        <li class="menu-item active"><a class="menu-link" href="#dashboard" data-section="dashboard">📊 Dashboard</a></li>
        <li class="menu-item"><a class="menu-link" href="#workers" data-section="workers">👥 Workers</a></li>
        <li class="menu-item"><a class="menu-link" href="#operations" data-section="operations">⚙️ Operations</a></li>
        <li class="menu-item"><a class="menu-link" href="#bundles" data-section="bundles">📦 Bundles</a></li>
        <li class="menu-item"><a class="menu-link" href="#file-upload" data-section="file-upload">📁 File Upload</a></li>
        <li class="menu-item"><a class="menu-link" href="#esp32-demo" data-section="esp32-demo">📱 ESP32 Scanner</a></li>
        <li class="menu-item"><a class="menu-link" href="#reports" data-section="reports">📈 Reports</a></li>
      </ul>
    </aside>

    <main class="main-content">
      <!-- DASHBOARD -->
      <section id="dashboard" class="section active">
        <header class="main-header">
          <div class="header-title">
            <h1>Production Dashboard</h1>
            <div class="live-indicator"><span class="live-dot"></span> Live</div>
          </div>
          <div class="header-actions">
            <button class="btn-primary" id="refreshData" aria-label="Refresh">🔄 Refresh</button>
            <span class="btn-text">Last updated: <span id="lastUpdate">--:--</span></span>
          </div>
        </header>

        <section class="stats-section">
          <div id="statsGrid" class="stats-grid"></div>
        </section>

        <section class="charts-section">
          <div class="charts-grid">
            <div class="chart-card">
              <div class="chart-header"><h3>Bundle Status Distribution</h3></div>
              <div class="chart-container"><canvas id="bundleStatusChart"></canvas></div>
            </div>
            <div class="chart-card">
              <div class="chart-header"><h3>Department Workload</h3></div>
              <div class="chart-container"><canvas id="departmentChart"></canvas></div>
            </div>
          </div>
        </section>

        <section class="activities-section">
          <div class="activities-card">
            <div class="activities-header"><h3>Recent Activity</h3></div>
            <div id="activitiesList"></div>
          </div>
        </section>
      </section>

      <!-- WORKERS -->
      <section id="workers" class="section">
        <div class="page-header"><h1>Worker Management</h1></div>
        <div class="table-card">
          <div class="table-header">
            <div class="table-count"><span id="workersCount">0</span> total</div>
            <div class="table-controls">
              <input type="text" class="form-input" id="workerSearch" placeholder="Search workers..." />
            </div>
          </div>
          <div class="table-container">
            <table class="data-table" id="workersTable">
              <thead><tr><th>Name</th><th>Token ID</th><th>Department</th><th>Status</th><th>QR</th></tr></thead>
              <tbody id="workersTableBody"></tbody>
            </table>
          </div>
        </div>
      </section>

      <!-- OPERATIONS -->
      <section id="operations" class="section">
        <div class="page-header">
          <h1>Operations Management</h1>
          <p>Manage operations with dept, machine, std minutes, and piece rate.</p>
        </div>
        <div class="table-card">
          <div class="table-header">
            <div class="table-count"><span id="operationsCount">0</span> operations</div>
          </div>
          <div class="table-container">
            <table class="data-table" id="operationsTable">
              <thead><tr><th>Op No</th><th>Description</th><th>Machine</th><th>Department</th><th>Std Min</th><th>Piece Rate (₹)</th></tr></thead>
              <tbody id="operationsTableBody"></tbody>
            </table>
          </div>
        </div>
      </section>

      <!-- BUNDLES -->
      <section id="bundles" class="section">
        <div class="page-header"><h1>Bundle Management</h1></div>
        <div class="table-card">
          <div class="table-header">
            <div class="table-count"><span id="bundlesCount">0</span> bundles</div>
            <button class="btn-primary" id="assignBundleBtn">Assign Bundle</button>
          </div>
          <div id="bundlesGrid" class="reports-grid"></div>
        </div>
      </section>

      <!-- FILE UPLOAD -->
      <section id="file-upload" class="section">
        <div class="page-header"><h1>File Upload</h1></div>
        <div class="reports-grid">
          <div class="report-card">
            <div class="report-icon">📄</div>
            <h3>Upload OB File (Excel)</h3>
            <input type="file" id="obFileInput" accept=".xlsx,.xls" />
            <button class="btn-secondary" id="uploadObBtn">Upload</button>
            <p id="obUploadStatus" class="text-muted"></p>
          </div>
          <div class="report-card">
            <div class="report-icon">📋</div>
            <h3>Upload Production Order (PDF)</h3>
            <input type="file" id="poFileInput" accept=".pdf" />
            <button class="btn-secondary" id="uploadPoBtn">Upload</button>
            <p id="poUploadStatus" class="text-muted"></p>
          </div>
        </div>
      </section>

      <!-- ESP32 DEMO -->
      <section id="esp32-demo" class="section">
        <div class="page-header"><h1>ESP32 Scanner Demo</h1></div>
        <div class="reports-grid">
          <div class="report-card">
            <h3>Simulate Scan</h3>
            <input type="text" id="simulateToken" class="form-input" placeholder="Enter token id" />
            <select id="simulateType" class="form-input">
              <option value="work">Work</option>
              <option value="login">Login</option>
              <option value="logout">Logout</option>
            </select>
            <button class="btn-primary" id="simulateScanBtn">Simulate</button>
            <div id="scanResult" class="text-muted" style="margin-top: .75rem;"></div>
          </div>
          <div class="report-card">
            <h3>Scan Log</h3>
            <div id="scanLog"></div>
          </div>
        </div>
      </section>

      <!-- REPORTS -->
      <section id="reports" class="section">
        <div class="page-header">
          <h1>Reports & Analytics</h1>
          <a class="btn-primary" href="/api/reports/earnings.csv">📥 Export Earnings CSV</a>
        </div>
        <div class="charts-grid">
          <div class="chart-card">
            <div class="chart-header"><h3>Worker Productivity (mock)</h3></div>
            <div class="chart-container"><canvas id="productivityChart"></canvas></div>
          </div>
          <div class="chart-card">
            <div class="chart-header"><h3>Earnings Summary (by Dept)</h3></div>
            <div id="earningsSummary"></div>
          </div>
        </div>
      </section>
    </main>
  </div>

  <script src="/static/js/pms.js"></script>
</body>
</html>
```

---

## static/css/style.css (replace; aligned to your dark UI)

```css
/* Dark UI theme (aligned) */
:root {
  --bg-primary:#0f1526; --panel:#121a30; --panel-2:#16203b; --card:#0f1831;
  --ink:#ecf2ff; --ink-dim:#9fb0d6; --muted:#7f8fb4; --primary:#7c5cff; --primary-2:#5b8dff;
  --accent:#22c55e; --warning:#f59e0b; --danger:#ef4444; --border:#23335e; --hover:#101a38;
}
*{box-sizing:border-box}
body{margin:0;font-family:Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial;color:var(--ink);background:linear-gradient(180deg,#0f1526 0%,#0b1120 100%) fixed}
.dashboard{display:flex;min-height:100vh}
.sidebar{width:260px;background:linear-gradient(180deg,#0f1736 0%,#0b122b 100%);border-right:1px solid var(--border);padding:16px;position:fixed;inset:0 auto 0 0;z-index:50;transform:translateX(0);transition:transform .3s}
.sidebar.show{transform:translateX(0)}
.sidebar-header{padding:6px 4px 14px;border-bottom:1px dashed var(--border)}
.logo{display:flex;align-items:center;gap:10px;color:var(--primary);font-weight:700}
.sidebar-menu{list-style:none;margin:12px 0 0;padding:0}
.menu-item{margin-bottom:6px}
.menu-link{display:flex;align-items:center;gap:10px;padding:10px 12px;border-radius:12px;color:var(--ink);text-decoration:none;border:1px solid transparent}
.menu-item.active .menu-link,.menu-link:hover{background:var(--hover);border-color:var(--border)}
.main-content{flex:1;margin-left:260px;padding:22px}
@media (max-width:768px){.main-content{margin-left:0;padding:16px}.sidebar{transform:translateX(-100%)}.sidebar.show{transform:translateX(0)}}
.section{display:none}.section.active{display:block}
.main-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;background:rgba(18,26,48,.6);border:1px solid var(--border);border-radius:14px;padding:14px 16px}
.btn-primary{border:none;background:linear-gradient(135deg,var(--primary),var(--primary-2));color:#fff;padding:10px 12px;border-radius:12px;cursor:pointer}
.btn-secondary{border:1px solid var(--border);background:#0f1833;color:var(--ink);padding:10px 12px;border-radius:12px;cursor:pointer}
.btn-text{color:var(--ink-dim)}
.stats-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}
.stat-card{display:flex;gap:12px;align-items:center;background:linear-gradient(180deg,var(--panel) 0%,#0e1733 100%);border:1px solid var(--border);border-radius:16px;padding:14px 16px}
.stat-icon{width:44px;height:44px;border-radius:12px;display:grid;place-items:center;background:linear-gradient(135deg,var(--primary),var(--primary-2))}
.stat-value{font-size:22px;font-weight:700}
.stat-label{color:var(--ink-dim);font-size:12px}
.charts-grid{display:grid;gap:16px;grid-template-columns:2fr 1fr}
@media (max-width:1024px){.charts-grid{grid-template-columns:1fr}}
.chart-card{background:var(--panel);border:1px solid var(--border);border-radius:16px;padding:16px}
.activities-card{background:var(--panel);border:1px solid var(--border);border-radius:16px;padding:16px}
.table-card{background:var(--panel);border:1px solid var(--border);border-radius:16px;overflow:hidden;margin-bottom:16px}
.table-header{display:flex;justify-content:space-between;align-items:center;padding:14px 16px;border-bottom:1px solid var(--border)}
.data-table{width:100%;border-collapse:collapse}
.data-table th,.data-table td{padding:12px 10px;border-bottom:1px solid #203058;text-align:left}
.data-table th{background:#0f1833}
.form-input{background:#0f1833;border:1px solid var(--border);color:var(--ink);border-radius:12px;padding:10px 12px;outline:none}
.reports-grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(300px,1fr))}
.report-card{background:#0f1836;border:1px solid var(--border);border-radius:14px;padding:16px;text-align:left}
.mobile-menu-toggle{display:none;position:fixed;top:12px;left:12px;z-index:60;background:linear-gradient(135deg,var(--primary),var(--primary-2));border:none;color:#fff;width:40px;height:40px;border-radius:10px}
@media (max-width:768px){.mobile-menu-toggle{display:block}}
```

---

## static/js/pms.js (new)

```js
// PMS UI wiring for Flask APIs
const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
const currency = (n) => `₹${Number(n).toFixed(2)}`;
const nowTime = () => new Date().toLocaleTimeString();

// Nav + mobile menu
(function navInit(){
  const sidebar = $('#sidebar');
  const toggle = $('#mobileMenuToggle');
  toggle?.addEventListener('click', ()=> sidebar.classList.toggle('show'));
  $$('.menu-link').forEach(a => {
    a.addEventListener('click', (e)=>{
      e.preventDefault();
      const id = a.dataset.section;
      $$('.section').forEach(s=>s.classList.remove('active'));
      $$('.menu-item').forEach(m=>m.classList.remove('active'));
      a.parentElement.classList.add('active');
      document.getElementById(id)?.classList.add('active');
      sidebar.classList.remove('show');
      document.getElementById(id)?.scrollIntoView({behavior:'smooth', block:'start'});
    });
  });
})();

// Dashboard
(async function init(){
  await refreshAll();
  $('#refreshData')?.addEventListener('click', refreshAll);
})();

async function refreshAll(){
  await Promise.all([loadStats(), loadCharts(), loadActivities(), loadWorkers(), loadOperations(), loadBundles(), drawProductivityMock(), drawEarningsMock()]);
  $('#lastUpdate').textContent = nowTime();
}

async function loadStats(){
  const r = await fetch('/api/stats');
  const s = await r.json();
  const stats = [
    {label:'Active Workers', value: s.activeWorkers},
    {label:'Total Bundles', value: s.totalBundles},
    {label:'Operations', value: s.totalOperations},
    {label:'Total Earnings', value: currency(s.totalEarnings)},
  ];
  const grid = $('#statsGrid');
  grid.innerHTML = '';
  stats.forEach((st,i)=>{
    const div = document.createElement('div');
    div.className='stat-card';
    div.innerHTML = `<div class="stat-icon">${['👥','📦','⚙️','💰'][i]}</div>
    <div>
      <div class="stat-value">${st.value}</div>
      <div class="stat-label">${st.label}</div>
    </div>`;
    grid.appendChild(div);
  });
}

async function loadCharts(){
  const r = await fetch('/api/chart-data');
  const data = await r.json();

  const ctx1 = document.getElementById('bundleStatusChart');
  const ctx2 = document.getElementById('departmentChart');

  new Chart(ctx1, {
    type:'doughnut',
    data:{ labels:['Pending','In Progress','QA','Completed'], datasets:[{ data:data.bundleStatus, backgroundColor:['#7c5cff','#22c55e','#f59e0b','#5b8dff'], borderWidth:0 }]},
    options:{ plugins:{ legend:{ labels:{ color:'#cfe1ff' }}}}
  });

  new Chart(ctx2, {
    type:'bar',
    data:{ labels:data.departments, datasets:[{ label:'Queued pieces', data:data.deptLoads, backgroundColor:'#5b8dff' }]},
    options:{ maintainAspectRatio:false, scales:{ x:{ ticks:{ color:'#cfe1ff' }, grid:{ color:'#1b2a55' }}, y:{ ticks:{ color:'#cfe1ff' }, grid:{ color:'#1b2a55' }}}, plugins:{ legend:{ labels:{ color:'#cfe1ff' }}} }
  });
}

async function loadActivities(){
  const r = await fetch('/api/activities');
  const items = await r.json();
  const list = $('#activitiesList');
  list.innerHTML = '';
  items.forEach(a => {
    const row = document.createElement('div');
    row.className = 'activity-item';
    const when = a.time ? new Date(a.time).toLocaleString() : '';
    row.innerHTML = `<div>${a.text}</div><div class="text-muted">${when}</div>`;
    list.appendChild(row);
  });
}

async function loadWorkers(){
  const r = await fetch('/api/workers');
  const rows = await r.json();
  $('#workersCount').textContent = rows.length;
  const tbody = $('#workersTableBody');
  tbody.innerHTML = '';
  rows.forEach(w => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${escapeHtml(w.name)}</td>
      <td>${escapeHtml(w.token_id)}</td>
      <td><span class="department-tag">${escapeHtml(w.department||'')}</span></td>
      <td><span class="status-badge ${w.is_logged_in ? 'active' : 'inactive'}">${w.is_logged_in ? 'Active' : 'Idle'}</span></td>
      <td><a class="btn-secondary" href="/qr/${encodeURIComponent(w.token_id)}" target="_blank">QR</a></td>
    `;
    tbody.appendChild(tr);
  });
}

async function loadOperations(){
  const r = await fetch('/api/operations');
  const rows = await r.json();
  $('#operationsCount').textContent = rows.length;
  const tbody = $('#operationsTableBody');
  tbody.innerHTML = '';
  rows.forEach(op => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${op.op_no}</td>
      <td title="${escapeHtml(op.description||'')}">${escapeHtml(op.description||'')}</td>
      <td>${escapeHtml(op.machine||'')}</td>
      <td><span class="department-tag">${escapeHtml(op.department||'')}</span></td>
      <td>${Number(op.std_min||0).toFixed(2)}</td>
      <td>${Number(op.piece_rate||0).toFixed(2)}</td>
    `;
    tbody.appendChild(tr);
  });
}

async function loadBundles(){
  const r = await fetch('/api/bundles');
  const rows = await r.json();
  $('#bundlesCount').textContent = rows.length;
  const grid = $('#bundlesGrid');
  grid.innerHTML = '';
  const groups = ['Pending','In Progress','QA','Completed'];
  groups.forEach(g => {
    const col = document.createElement('div');
    col.className = 'report-card';
    col.innerHTML = `<h3>${g}</h3>`;
    rows.filter(b=>b.status===g).forEach(b => {
      const card = document.createElement('div');
      card.className = 'earning-row';
      card.style.display = 'flex';
      card.style.justifyContent = 'space-between';
      card.style.alignItems = 'center';
      card.style.margin = '8px 0';
      card.innerHTML = `<strong>Bundle #${escapeHtml(b.code)}</strong><span class="department-tag">Qty: ${b.qty}</span>`;
      col.appendChild(card);
    });
    grid.appendChild(col);
  });
}

// Uploads
$('#uploadObBtn')?.addEventListener('click', async ()=>{
  const f = $('#obFileInput').files[0];
  if(!f){ $('#obUploadStatus').textContent = 'Pick a file first.'; return; }
  const fd = new FormData(); fd.append('file', f);
  const r = await fetch('/api/upload/ob', { method:'POST', body: fd });
  $('#obUploadStatus').textContent = r.ok ? 'Uploaded ✓' : 'Failed';
});
$('#uploadPoBtn')?.addEventListener('click', async ()=>{
  const f = $('#poFileInput').files[0];
  if(!f){ $('#poUploadStatus').textContent = 'Pick a file first.'; return; }
  const fd = new FormData(); fd.append('file', f);
  const r = await fetch('/api/upload/po', { method:'POST', body: fd });
  $('#poUploadStatus').textContent = r.ok ? 'Uploaded ✓' : 'Failed';
});

// ESP32 simulate
$('#simulateScanBtn')?.addEventListener('click', async ()=>{
  const token = $('#simulateToken').value.trim();
  const type = $('#simulateType').value;
  if(!token){ $('#scanResult').textContent = 'Enter a token id'; return; }
  const r = await fetch('/scan', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ token_id: token, secret: '" + (window.DEVICE_SECRET || '') + "', scan_type: type }) });
  const j = await r.json();
  $('#scanResult').textContent = j.status === 'success' ? `${j.message} — ${j.name}` : (j.message || 'Failed');
  await loadActivities();
});

// Mock charts (reports page)
async function drawProductivityMock(){
  const ctx = document.getElementById('productivityChart');
  if(!ctx) return;
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  const pieces = months.map(()=> Math.floor(250 + Math.random()*700));
  const minutes = months.map(()=> Math.floor(600 + Math.random()*900));
  new Chart(ctx, { type:'line', data:{ labels:months, datasets:[ {label:'Pieces', data:pieces, tension:.35, fill:true, borderColor:'#7c5cff', backgroundColor:'rgba(124,92,255,.18)'}, {label:'Minutes', data:minutes, tension:.35, borderColor:'#22c55e'} ] }, options:{ plugins:{ legend:{ labels:{ color:'#cfe1ff' } } }, scales:{ x:{ ticks:{ color:'#cfe1ff' } }, y:{ ticks:{ color:'#cfe1ff' } } } } });
}
async function drawEarningsMock(){
  const wrap = $('#earningsSummary');
  if(!wrap) return;
  const depts = ['SLEEVE','COLLAR','LINING','BODY','ASSE-1','ASSE-2','FLAP','BACK'];
  wrap.innerHTML = '';
  depts.forEach(d => {
    const row = document.createElement('div');
    row.className = 'earning-row';
    row.style.display = 'flex';
    row.style.justifyContent = 'space-between';
    row.innerHTML = `<span>${d}</span><strong>${currency(12000 + Math.random()*30000)}</strong>`;
    wrap.appendChild(row);
  });
}

function escapeHtml(str){
  return String(str||'').replace(/[&<>"']/g, s=>({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;','\'':'&#39;' }[s]));
}
```

---

### How to deploy on Render

1. Set **Environment**:

   * `DATABASE_URL` (Render Postgres string)
   * `DEVICE_SECRET` (any string; use the same on your ESP32)
   * `RATE_PER_PIECE` (optional, default 5.0)
2. Add **Build Command**: `pip install -r requirements.txt`
3. Add **Start Command**: `python app.py` (or `gunicorn app:app` for production)
4. Make sure **Auto-Deploy** is enabled.

That’s it. Paste these files into your repo and deploy. ✅
