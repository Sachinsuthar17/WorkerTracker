import os
import sqlite3
import qrcode
import qrcode.image.svg
from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from datetime import datetime
from werkzeug.utils import secure_filename
import openpyxl

app = Flask(__name__)
app.secret_key = "supersecret"  # replace with env var in prod

DB_PATH = "attendance.db"
QR_DIR = os.path.join("static", "qrcodes")
UPLOAD_DIR = os.path.join("uploads")

os.makedirs(QR_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def generate_qr(token_id, worker_id):
    """Generate both PNG and SVG for a worker token_id"""
    filename_base = f"qrcode_{token_id}_{worker_id}"
    png_path = os.path.join(QR_DIR, f"{filename_base}.png")
    svg_path = os.path.join(QR_DIR, f"{filename_base}.svg")

    # PNG
    img = qrcode.make(token_id)
    img.save(png_path)

    # SVG
    factory = qrcode.image.svg.SvgImage
    svg_img = qrcode.make(token_id, image_factory=factory)
    with open(svg_path, "wb") as f:
        svg_img.save(f)

    rel_path = os.path.relpath(png_path, "static")
    return rel_path

@app.route("/")
def index():
    conn = get_db()
    workers = conn.execute("SELECT * FROM workers ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("index.html", workers=workers)

@app.route("/add", methods=["GET", "POST"])
def add_worker():
    if request.method == "POST":
        name = request.form["name"].strip()
        token_id = request.form["token_id"].strip()
        department = request.form["department"].strip()
        line = request.form.get("line", "").strip()
        active = 1 if request.form.get("active") else 0

        if not token_id:
            flash("Token ID cannot be empty.", "error")
            return redirect(url_for("add_worker"))

        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO workers (name, token_id, department, line, active, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                (name, token_id, department, line, active, datetime.now(), datetime.now()),
            )
            worker_id = cur.lastrowid
            qrcode_path = generate_qr(token_id, worker_id)
            cur.execute("UPDATE workers SET qrcode_path=?, updated_at=? WHERE id=?",
                        (qrcode_path, datetime.now(), worker_id))
            conn.commit()
            flash("Worker added successfully!", "success")
        except sqlite3.IntegrityError:
            flash("Token ID already exists. Please use a unique token.", "error")
        finally:
            conn.close()
        return redirect(url_for("index"))
    return render_template("add_worker.html")

@app.route("/edit/<int:worker_id>", methods=["GET", "POST"])
def edit_worker(worker_id):
    conn = get_db()
    worker = conn.execute("SELECT * FROM workers WHERE id=?", (worker_id,)).fetchone()
    if not worker:
        flash("Worker not found.", "error")
        return redirect(url_for("index"))

    if request.method == "POST":
        name = request.form["name"].strip()
        department = request.form["department"].strip()
        line = request.form.get("line", "").strip()
        active = 1 if request.form.get("active") else 0

        conn.execute(
            "UPDATE workers SET name=?, department=?, line=?, active=?, updated_at=? WHERE id=?",
            (name, department, line, active, datetime.now(), worker_id),
        )
        conn.commit()
        conn.close()
        flash("Worker updated successfully!", "success")
        return redirect(url_for("index"))

    conn.close()
    return render_template("edit_worker.html", worker=worker)

@app.route("/delete/<int:worker_id>")
def delete_worker(worker_id):
    conn = get_db()
    worker = conn.execute("SELECT * FROM workers WHERE id=?", (worker_id,)).fetchone()
    if not worker:
        flash("Worker not found.", "error")
        conn.close()
        return redirect(url_for("index"))

    # Remove QR files
    if worker["qrcode_path"]:
        try:
            abs_png = os.path.join("static", worker["qrcode_path"])
            abs_svg = abs_png.replace(".png", ".svg")
            if os.path.exists(abs_png):
                os.remove(abs_png)
            if os.path.exists(abs_svg):
                os.remove(abs_svg)
        except Exception as e:
            app.logger.error(f"Failed to delete QR files: {e}")

    conn.execute("DELETE FROM workers WHERE id=?", (worker_id,))
    conn.commit()
    conn.close()
    flash("Worker deleted.", "success")
    return redirect(url_for("index"))

@app.route("/download_qr/<int:worker_id>")
def download_qr(worker_id):
    conn = get_db()
    worker = conn.execute("SELECT * FROM workers WHERE id=?", (worker_id,)).fetchone()
    conn.close()
    if not worker or not worker["qrcode_path"]:
        flash("QR not available.", "error")
        return redirect(url_for("index"))
    abs_path = os.path.join("static", worker["qrcode_path"])
    return send_file(abs_path, as_attachment=True)

@app.route("/upload_excel", methods=["POST"])
def upload_excel():
    file = request.files.get("file")
    if not file or not file.filename.endswith(".xlsx"):
        flash("Invalid file. Please upload .xlsx only.", "error")
        return redirect(url_for("index"))

    filepath = os.path.join(UPLOAD_DIR, secure_filename(file.filename))
    file.save(filepath)

    wb = openpyxl.load_workbook(filepath)
    sheet = wb.active

    headers = [cell.value.lower() for cell in next(sheet.iter_rows(min_row=1, max_row=1, values_only=True))]
    required = ["name", "token_id", "department", "line", "active"]
    if not all(h in headers for h in required):
        flash("Excel missing required headers.", "error")
        return redirect(url_for("index"))

    name_idx = headers.index("name")
    token_idx = headers.index("token_id")
    dept_idx = headers.index("department")
    line_idx = headers.index("line")
    active_idx = headers.index("active")

    conn = get_db()
    cur = conn.cursor()
    added, skipped, invalid = 0, 0, []

    for row in sheet.iter_rows(min_row=2, values_only=True):
        try:
            name = str(row[name_idx]).strip()
            token_id = str(row[token_idx]).strip()
            dept = str(row[dept_idx]).strip()
            line = str(row[line_idx]).strip() if row[line_idx] else ""
            active = 1 if str(row[active_idx]).strip().lower() in ("1", "true", "yes") else 0
        except Exception:
            invalid.append(row)
            continue

        if not token_id:
            invalid.append(row)
            continue

        try:
            cur.execute(
                "INSERT INTO workers (name, token_id, department, line, active, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                (name, token_id, dept, line, active, datetime.now(), datetime.now()),
            )
            worker_id = cur.lastrowid
            qrcode_path = generate_qr(token_id, worker_id)
            cur.execute("UPDATE workers SET qrcode_path=?, updated_at=? WHERE id=?",
                        (qrcode_path, datetime.now(), worker_id))
            added += 1
        except sqlite3.IntegrityError:
            skipped += 1
            invalid.append(token_id)

    conn.commit()
    conn.close()
    flash(f"Upload complete. Added: {added}, Skipped: {skipped}, Invalid: {len(invalid)}", "info")
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(debug=True)
