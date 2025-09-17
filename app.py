import os
import uuid
import sqlite3
from datetime import datetime
from pathlib import Path

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, jsonify, send_file
)
from werkzeug.utils import secure_filename

# QR
import qrcode
import qrcode.image.svg
from PIL import Image  # required by qrcode for PNG

# Excel
import openpyxl


# -------------------------------------------------------------------
# Paths & Flask
# -------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "attendance.db"            # keep using your SQLite DB
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"
QR_DIR = STATIC_DIR / "qrcodes"
UPLOADS_DIR = BASE_DIR / "uploads"

QR_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__, static_folder=str(STATIC_DIR), template_folder=str(TEMPLATES_DIR))
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-dev-dev")  # set an env var in prod

# uploads
MAX_UPLOAD_MB = 5
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
ALLOWED_XLSX_EXT = {".xlsx"}


# -------------------------------------------------------------------
# Database helpers
# -------------------------------------------------------------------
def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """
    Creates tables we need. This aligns with your requirements:
    id, name, token_id (UNIQUE), department, line, active, qrcode_path, created_at, updated_at
    """
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS workers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            token_id TEXT NOT NULL UNIQUE,
            department TEXT NOT NULL,
            line TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            qrcode_path TEXT,
            qrcode_svg_path TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        """)
        # optional tables your UI already references — harmless if empty
        cur.execute("""
        CREATE TABLE IF NOT EXISTS operations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            seq_no INTEGER,
            op_no TEXT,
            description TEXT,
            machine TEXT,
            department TEXT,
            std_min REAL,
            piece_rate REAL,
            created_at TEXT DEFAULT (datetime('now'))
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS bundles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bundle_no TEXT UNIQUE,
            order_no TEXT,
            style TEXT,
            color TEXT,
            size TEXT,
            quantity INTEGER,
            status TEXT DEFAULT 'Pending',
            created_at TEXT DEFAULT (datetime('now'))
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS production_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_no TEXT UNIQUE,
            style TEXT,
            quantity INTEGER,
            buyer TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            worker_id INTEGER,
            bundle_id INTEGER,
            created_at TEXT DEFAULT (datetime('now'))
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS file_uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            file_type TEXT NOT NULL,
            file_path TEXT NOT NULL,
            uploaded_at TEXT DEFAULT (datetime('now'))
        );
        """)
        conn.commit()


def touch_updated_at(conn, worker_id: int):
    conn.execute("UPDATE workers SET updated_at = datetime('now') WHERE id = ?", (worker_id,))


# -------------------------------------------------------------------
# QR helpers (SVG + PNG)
# -------------------------------------------------------------------
def generate_qr_files(token_id: str, worker_id: int) -> tuple[str, str]:
    """
    Create PNG + SVG QR for token_id under static/qrcodes/.
    Filenames include token_id + id + timestamp to avoid collisions.
    Returns (png_rel_path, svg_rel_path) relative to the /static root.
    """
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    base = f"qrcode_{token_id}_{worker_id}_{ts}"
    png_path = QR_DIR / f"{base}.png"
    svg_path = QR_DIR / f"{base}.svg"

    # SVG
    svg_factory = qrcode.image.svg.SvgImage
    svg_img = qrcode.make(token_id, image_factory=svg_factory)
    svg_img.save(str(svg_path))

    # PNG
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(token_id)
    qr.make(fit=True)
    png_img = qr.make_image(fill_color="black", back_color="white")
    png_img.save(str(png_path), format="PNG")

    return f"qrcodes/{png_path.name}", f"qrcodes/{svg_path.name}"


def delete_qr_files(qr_png_rel: str | None, qr_svg_rel: str | None):
    for rel in (qr_png_rel, qr_svg_rel):
        if not rel:
            continue
        p = STATIC_DIR / rel
        try:
            if p.exists():
                p.unlink()
        except Exception as e:
            app.logger.error("Failed to delete QR file %s: %s", p, e)


# -------------------------------------------------------------------
# UI (keeps your layout; we only pass workers for the table loop)
# -------------------------------------------------------------------
@app.get("/")
def index():
    with get_db() as conn:
        workers = conn.execute("SELECT * FROM workers ORDER BY created_at DESC").fetchall()
    return render_template("index.html", workers=workers)


# -------------------------------------------------------------------
# API endpoints already used by your dashboard sections
# -------------------------------------------------------------------
@app.get("/api/dashboard-stats")
def api_dashboard_stats():
    try:
        with get_db() as conn:
            active_workers = conn.execute("SELECT COUNT(*) FROM workers WHERE active=1").fetchone()[0]
            total_bundles = conn.execute("SELECT COUNT(*) FROM bundles").fetchone()[0]
            total_operations = conn.execute("SELECT COUNT(*) FROM operations").fetchone()[0]
            # demo earnings: piece_rate * 5
            total_earnings = float(conn.execute("SELECT COALESCE(SUM(piece_rate*5),0) FROM operations").fetchone()[0] or 0)
        return jsonify({
            "activeWorkers": active_workers,
            "totalBundles": total_bundles,
            "totalOperations": total_operations,
            "totalEarnings": total_earnings
        })
    except Exception as e:
        app.logger.error("dashboard-stats error: %s", e)
        return jsonify({"activeWorkers": 0, "totalBundles": 0, "totalOperations": 0, "totalEarnings": 0})


@app.get("/api/chart-data")
def api_chart_data():
    try:
        with get_db() as conn:
            bs = conn.execute("SELECT status, COUNT(*) c FROM bundles GROUP BY status").fetchall()
            bundle_status = {r["status"]: r["c"] for r in bs}
            dw = conn.execute("SELECT department, COUNT(*) c FROM workers GROUP BY department").fetchall()
            dept = {r["department"] or "Unknown": r["c"] for r in dw}
        return jsonify({"bundleStatus": bundle_status, "departmentWorkload": dept})
    except Exception as e:
        app.logger.error("chart-data error: %s", e)
        return jsonify({"bundleStatus": {}, "departmentWorkload": {}})


@app.get("/api/recent-activity")
def api_recent_activity():
    try:
        with get_db() as conn:
            rows = conn.execute("""
                SELECT 'Scan' AS type, code AS description, created_at
                FROM scans ORDER BY created_at DESC LIMIT 10
            """).fetchall()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        app.logger.error("recent-activity error: %s", e)
        return jsonify([])


@app.get("/api/operations")
def api_operations():
    search = (request.args.get("search") or "").strip()
    sql = "SELECT * FROM operations WHERE 1=1"
    params = []
    if search:
        sql += " AND (description LIKE ? OR op_no LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like])
    sql += " ORDER BY COALESCE(seq_no, 999999), id"
    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return jsonify([dict(r) for r in rows])


@app.get("/api/bundles")
def api_bundles():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM bundles ORDER BY created_at DESC").fetchall()
    return jsonify([dict(r) for r in rows])


@app.get("/api/production-order")
def api_production_order():
    with get_db() as conn:
        row = conn.execute("SELECT * FROM production_orders ORDER BY created_at DESC LIMIT 1").fetchone()
    return jsonify(dict(row) if row else {})


# -------------------------------------------------------------------
# Single worker add / edit / delete / download QR
# -------------------------------------------------------------------
@app.route("/add", methods=["GET", "POST"])
def add_worker():
    if request.method == "GET":
        # you already have add_worker.html; no layout changes
        return render_template("add_worker.html")

    name = (request.form.get("name") or "").strip()
    token_id = (request.form.get("token_id") or "").strip()
    department = (request.form.get("department") or "").strip()
    line = (request.form.get("line") or "").strip()
    active = 1 if (request.form.get("active") in ("1", "on", "true", "True")) else 0

    if not token_id:
        flash("Token ID cannot be empty.", "error")
        return redirect(url_for("add_worker"))

    try:
        with get_db() as conn:
            # dedupe by token_id
            exists = conn.execute("SELECT 1 FROM workers WHERE token_id=?", (token_id,)).fetchone()
            if exists:
                flash("Token ID already exists. Please use a unique token.", "error")
                return redirect(url_for("add_worker"))

            cur = conn.execute("""
                INSERT INTO workers (name, token_id, department, line, active, created_at, updated_at)
                VALUES (?,?,?,?,?, datetime('now'), datetime('now'))
            """, (name, token_id, department, line, active))
            worker_id = cur.lastrowid

            png_rel, svg_rel = generate_qr_files(token_id, worker_id)
            conn.execute(
                "UPDATE workers SET qrcode_path=?, qrcode_svg_path=?, updated_at=datetime('now') WHERE id=?",
                (png_rel, svg_rel, worker_id)
            )
            conn.commit()
        flash("Worker added successfully!", "success")
        return redirect(url_for("index"))
    except Exception as e:
        app.logger.error("add_worker error: %s", e)
        flash("Server error while adding worker.", "error")
        return redirect(url_for("add_worker"))


@app.route("/edit/<int:worker_id>", methods=["GET", "POST"])
def edit_worker(worker_id: int):
    with get_db() as conn:
        worker = conn.execute("SELECT * FROM workers WHERE id=?", (worker_id,)).fetchone()
        if not worker:
            flash("Worker not found.", "error")
            return redirect(url_for("index"))

        if request.method == "GET":
            return render_template("edit_worker.html", worker=worker)

        # token_id is immutable; only update name/department/line/active
        name = (request.form.get("name") or "").strip()
        department = (request.form.get("department") or "").strip()
        line = (request.form.get("line") or "").strip()
        active = 1 if (request.form.get("active") in ("1", "on", "true", "True")) else 0

        try:
            conn.execute("""
                UPDATE workers
                SET name=?, department=?, line=?, active=?, updated_at=datetime('now')
                WHERE id=?
            """, (name, department, line, active, worker_id))
            conn.commit()
            flash("Worker updated successfully!", "success")
        except Exception as e:
            app.logger.error("edit_worker error: %s", e)
            flash("Server error while updating worker.", "error")
        return redirect(url_for("index"))


@app.route("/delete/<int:worker_id>", methods=["POST", "GET"])
def delete_worker(worker_id: int):
    # allow GET (matches your existing simple link); confirm client-side
    try:
        with get_db() as conn:
            row = conn.execute("SELECT qrcode_path, qrcode_svg_path FROM workers WHERE id=?", (worker_id,)).fetchone()
            if not row:
                flash("Worker not found.", "error")
                return redirect(url_for("index"))

            delete_qr_files(row["qrcode_path"], row["qrcode_svg_path"])
            conn.execute("DELETE FROM workers WHERE id=?", (worker_id,))
            conn.commit()
        flash("Worker deleted.", "success")
    except Exception as e:
        app.logger.error("delete_worker error: %s", e)
        flash("Server error while deleting worker.", "error")
    return redirect(url_for("index"))


@app.get("/download_qr/<int:worker_id>")
def download_qr(worker_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT token_id, qrcode_path FROM workers WHERE id=?", (worker_id,)).fetchone()
        if not row or not row["qrcode_path"]:
            flash("QR not available.", "error")
            return redirect(url_for("index"))

    p = STATIC_DIR / row["qrcode_path"]
    if not p.exists():
        flash("QR file missing on disk.", "error")
        return redirect(url_for("index"))

    return send_file(str(p), mimetype="image/png", as_attachment=True, download_name=f"qr_{row['token_id']}.png")


# -------------------------------------------------------------------
# Bulk Excel upload with dedupe
#  - Expose BOTH /upload_workers (used by your template) AND /upload_excel
# -------------------------------------------------------------------
@app.route("/upload_workers", methods=["POST"])
@app.route("/upload_excel", methods=["POST"])
def upload_workers():
    f = request.files.get("file")
    if not f or not f.filename:
        flash("No file selected.", "error")
        return redirect(url_for("index"))

    ext = Path(f.filename).suffix.lower()
    if ext not in ALLOWED_XLSX_EXT:
        flash("Invalid file. Please upload a .xlsx file.", "error")
        return redirect(url_for("index"))

    temp_path = UPLOADS_DIR / f"{uuid.uuid4()}_{secure_filename(f.filename)}"
    f.save(temp_path)

    added = skipped = invalid = 0
    skipped_tokens: list[str] = []

    try:
        wb = openpyxl.load_workbook(temp_path)
        ws = wb.active

        # header row (case-insensitive)
        header = [str(c).strip().lower() if c is not None else "" for c in next(ws.iter_rows(min_row=1, max_row=1, values_only=True))]
        required = ["name", "token_id", "department", "line", "active"]
        missing = [h for h in required if h not in header]
        if missing:
            flash(f"Excel missing required headers: {', '.join(missing)}", "error")
            temp_path.unlink(missing_ok=True)
            return redirect(url_for("index"))

        idx = {h: header.index(h) for h in header}

        with get_db() as conn:
            try:
                for row in ws.iter_rows(min_row=2, values_only=True):
                    try:
                        name = (str(row[idx["name"]]).strip() if row[idx["name"]] is not None else "")
                        token_id = (str(row[idx["token_id"]]).strip() if row[idx["token_id"]] is not None else "")
                        department = (str(row[idx["department"]]).strip() if row[idx["department"]] is not None else "")
                        line = (str(row[idx["line"]]).strip() if row[idx["line"]] is not None else "")
                        active_cell = row[idx["active"]]
                        active = 1 if str(active_cell).strip().lower() in ("1", "true", "yes", "y") else 0
                    except Exception:
                        invalid += 1
                        continue

                    if not token_id:
                        invalid += 1
                        continue

                    exists = conn.execute("SELECT 1 FROM workers WHERE token_id=?", (token_id,)).fetchone()
                    if exists:
                        skipped += 1
                        if len(skipped_tokens) < 10:
                            skipped_tokens.append(token_id)
                        continue

                    cur = conn.execute("""
                        INSERT INTO workers (name, token_id, department, line, active, created_at, updated_at)
                        VALUES (?,?,?,?,?, datetime('now'), datetime('now'))
                    """, (name, token_id, department, line, active))
                    worker_id = cur.lastrowid

                    png_rel, svg_rel = generate_qr_files(token_id, worker_id)
                    conn.execute(
                        "UPDATE workers SET qrcode_path=?, qrcode_svg_path=?, updated_at=datetime('now') WHERE id=?",
                        (png_rel, svg_rel, worker_id)
                    )
                    added += 1

                conn.commit()
            except Exception as tx_err:
                conn.rollback()
                raise tx_err
    except Exception as e:
        app.logger.error("Excel processing error: %s", e)
        flash("Error processing Excel file.", "error")
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass
        return redirect(url_for("index"))

    try:
        temp_path.unlink(missing_ok=True)
    except Exception:
        pass

    summary = f"Upload complete. Added: {added}, Skipped (duplicates): {skipped}, Invalid: {invalid}"
    if skipped_tokens:
        summary += f" | Skipped token_ids (first 10): {', '.join(skipped_tokens)}"
    flash(summary, "success")
    return redirect(url_for("index"))


# -------------------------------------------------------------------
# Health
# -------------------------------------------------------------------
@app.get("/health")
def health():
    return "OK", 200


# -------------------------------------------------------------------
# Startup
# -------------------------------------------------------------------
if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
else:
    init_db()
