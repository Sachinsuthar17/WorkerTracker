import os
import io
import uuid
import threading
from datetime import datetime, timezone
from typing import Optional, Tuple

from flask import (
    Flask, jsonify, render_template, request,
    redirect, url_for, send_file, abort
)
from flask_cors import CORS
import psycopg2
from psycopg2.pool import SimpleConnectionPool
from psycopg2 import errors as pg_errors

import segno  # QR generation (PNG/SVG)

# =========================
# Config
# =========================
DEVICE_SECRET   = os.getenv("DEVICE_SECRET", "u38fh39fh28fh92hf928hfh92hF9H2hf92h3f9h2F")
DATABASE_URL    = os.getenv("DATABASE_URL")  # Render Postgres URL
RATE_PER_PIECE  = float(os.getenv("RATE_PER_PIECE", "1.0"))  # INR per piece

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required")

app = Flask(__name__)
CORS(app)

# A simple banner message mechanism using query params (?msg=...&err=1)
def go(where: str, msg: str = "", err: bool = False):
    if not msg:
        return redirect(where)
    sep = "&" if ("?" in where) else "?"
    return redirect(f"{where}{sep}msg={msg}&err={'1' if err else '0'}")

_pool: Optional[SimpleConnectionPool] = None
_inited = False
_init_lock = threading.Lock()


def get_pool() -> SimpleConnectionPool:
    """Create / return a shared connection pool."""
    global _pool
    if _pool is None:
        _pool = SimpleConnectionPool(minconn=1, maxconn=12, dsn=DATABASE_URL, sslmode="require")
    return _pool


def ensure_schema(conn: psycopg2.extensions.connection) -> None:
    """
    Idempotent schema bootstrap (safe to re-run).
      - workers(id, name, department, token_id UNIQUE)
      - scans(id, worker_id, barcode, operation_code, created_at TIMESTAMPTZ)
    """
    cur = conn.cursor()
    try:
        # workers
        cur.execute("""
            CREATE TABLE IF NOT EXISTS workers (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                department TEXT NOT NULL DEFAULT '',
                token_id TEXT UNIQUE
            );
        """)

        # scans
        cur.execute("CREATE TABLE IF NOT EXISTS scans (id SERIAL PRIMARY KEY);")

        cur.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='scans' AND column_name='worker_id') THEN
                ALTER TABLE scans ADD COLUMN worker_id INTEGER;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='scans' AND column_name='barcode') THEN
                ALTER TABLE scans ADD COLUMN barcode TEXT;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='scans' AND column_name='operation_code') THEN
                ALTER TABLE scans ADD COLUMN operation_code TEXT;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='scans' AND column_name='created_at') THEN
                ALTER TABLE scans ADD COLUMN created_at TIMESTAMPTZ DEFAULT NOW();
            END IF;
        END $$;
        """)

        # backfill legacy scanned_at
        cur.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name='scans' AND column_name='scanned_at') THEN
                UPDATE scans SET created_at = COALESCE(created_at, scanned_at)
                WHERE created_at IS NULL;
            END IF;
        END $$;
        """)

        # FK once
        cur.execute("""
        DO $$
        DECLARE fk_exists BOOLEAN;
        BEGIN
            SELECT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname='scans_worker_id_fkey'
            ) INTO fk_exists;
            IF NOT fk_exists THEN
                ALTER TABLE scans
                ADD CONSTRAINT scans_worker_id_fkey
                FOREIGN KEY (worker_id) REFERENCES workers(id)
                ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED;
            END IF;
        END $$;
        """)

        # indexes
        cur.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name='scans' AND column_name='created_at') THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_scans_created_at ON scans (created_at DESC)';
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name='scans' AND column_name='worker_id')
               AND EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='scans' AND column_name='created_at') THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_scans_worker ON scans (worker_id, created_at DESC)';
            END IF;
        END $$;
        """)
    finally:
        cur.close()
        conn.commit()


def init_once() -> None:
    global _inited
    if _inited:
        return
    with _init_lock:
        if _inited:
            return
        pool = get_pool()
        conn = pool.getconn()
        try:
            ensure_schema(conn)
            _inited = True
        finally:
            pool.putconn(conn)


@app.before_request
def _guard_init():
    init_once()


def today_bounds_utc() -> Tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    end = datetime(now.year, now.month, now.day, 23, 59, 59, 999999, tzinfo=timezone.utc)
    return start, end


# =========================
# Pages
# =========================
@app.route("/")
def dashboard():
    return render_template("dashboard.html", rate_per_piece=RATE_PER_PIECE)

@app.route("/workers", methods=["GET"])
def workers_page():
    """
    List workers + Add Worker form.
    Optional banner via ?msg=&err=0/1
    """
    msg = (request.args.get("msg") or "").strip()
    err = (request.args.get("err") or "0") == "1"

    pool = get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT id,
                       COALESCE(NULLIF(name,''),'(no name)') AS name,
                       COALESCE(NULLIF(department,''),'') AS department,
                       COALESCE(NULLIF(token_id,''),'') AS token_id
                  FROM workers
                 ORDER BY id DESC;
            """)
            workers = [
                {"id": rid, "name": nm, "department": dept, "token_id": tok or ""}
                for (rid, nm, dept, tok) in cur.fetchall()
            ]
        finally:
            cur.close()
    finally:
        pool.putconn(conn)

    return render_template(
        "workers.html",
        rate_per_piece=RATE_PER_PIECE,
        workers=workers,
        banner_msg=msg,
        banner_err=err
    )

@app.route("/workers/<int:worker_id>/edit", methods=["GET"])
def workers_edit_page(worker_id: int):
    pool = get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        try:
            cur.execute("SELECT id, name, department, token_id FROM workers WHERE id=%s;", (worker_id,))
            row = cur.fetchone()
        finally:
            cur.close()
    finally:
        pool.putconn(conn)

    if not row:
        return go(url_for("workers_page"), "Worker not found", True)

    worker = {"id": row[0], "name": row[1] or "", "department": row[2] or "", "token_id": row[3] or ""}
    return render_template("workers_edit.html", worker=worker, rate_per_piece=RATE_PER_PIECE)

@app.route("/workers/<int:worker_id>/print", methods=["GET"])
def workers_print(worker_id: int):
    """Print-friendly page with QR + details."""
    pool = get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        try:
            cur.execute("SELECT id, name, department, token_id FROM workers WHERE id=%s;", (worker_id,))
            row = cur.fetchone()
        finally:
            cur.close()
    finally:
        pool.putconn(conn)

    if not row:
        abort(404)

    worker = {"id": row[0], "name": row[1] or "", "department": row[2] or "", "token_id": row[3] or ""}
    return render_template("print_qr.html", worker=worker, rate_per_piece=RATE_PER_PIECE)

@app.route("/operations")
def operations_page():
    return render_template("operations.html", rate_per_piece=RATE_PER_PIECE)

@app.route("/reports")
def reports_page():
    return render_template("reports.html", rate_per_piece=RATE_PER_PIECE)

@app.route("/settings")
def settings_page():
    return render_template("settings.html", rate_per_piece=RATE_PER_PIECE)

@app.route("/assign_operation")
def assign_operation_page():
    return render_template("assign_operation.html", rate_per_piece=RATE_PER_PIECE)


# =========================
# Worker CRUD
# =========================
def _new_token() -> str:
    return uuid.uuid4().hex[:12].upper()

def _clean_token(raw: str) -> str:
    if not raw:
        return ""
    t = raw.strip().upper()
    if t.startswith("W:"):
        t = t[2:]
    return t

@app.route("/workers/add", methods=["POST"])
def workers_add():
    """
    Add worker. Fields: name, department, token (optional).
    If token blank -> auto-generate.
    """
    name = (request.form.get("name") or "").strip()
    department = (request.form.get("department") or "").strip()
    manual_token = _clean_token(request.form.get("token") or "")
    token_id = manual_token or _new_token()

    pool = get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO workers (name, department, token_id)
                VALUES (%s, %s, %s)
                RETURNING id;
            """, (name, department, token_id))
            worker_id = cur.fetchone()[0]
        except pg_errors.UniqueViolation:
            conn.rollback()
            return go(url_for("workers_page"), "Token already exists. Please use another.", True)
        finally:
            cur.close()
        conn.commit()
    finally:
        pool.putconn(conn)

    return go(url_for("workers_page") + f"#w{worker_id}", "Worker added")

@app.route("/workers/<int:worker_id>/edit", methods=["POST"])
def workers_edit(worker_id: int):
    """
    Update name, department, token_id (manual override).
    """
    name = (request.form.get("name") or "").strip()
    department = (request.form.get("department") or "").strip()
    token_id = _clean_token(request.form.get("token") or "")

    pool = get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        try:
            # Ensure exists
            cur.execute("SELECT id FROM workers WHERE id=%s;", (worker_id,))
            if not cur.fetchone():
                return go(url_for("workers_page"), "Worker not found", True)

            cur.execute("""
                UPDATE workers
                   SET name=%s, department=%s, token_id = NULLIF(%s,'')
                 WHERE id=%s;
            """, (name, department, token_id, worker_id))
        except pg_errors.UniqueViolation:
            conn.rollback()
            return go(url_for("workers_edit_page", worker_id=worker_id), "Token already in use by another worker.", True)
        finally:
            cur.close()
        conn.commit()
    finally:
        pool.putconn(conn)

    return go(url_for("workers_page") + f"#w{worker_id}", "Worker updated")

@app.route("/workers/<int:worker_id>/delete", methods=["POST"])
def workers_delete(worker_id: int):
    """
    Delete worker (and cascade delete their scans).
    """
    pool = get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM workers WHERE id=%s;", (worker_id,))
            deleted = cur.rowcount
        finally:
            cur.close()
        conn.commit()
    finally:
        pool.putconn(conn)

    if deleted:
        return go(url_for("workers_page"), "Worker deleted")
    return go(url_for("workers_page"), "Worker not found", True)


# =========================
# QR endpoints
# =========================
@app.route("/workers/<int:worker_id>/qr.png")
def worker_qr_png(worker_id: int):
    pool = get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        try:
            cur.execute("SELECT token_id FROM workers WHERE id=%s;", (worker_id,))
            row = cur.fetchone()
        finally:
            cur.close()
    finally:
        pool.putconn(conn)

    if not row or not row[0]:
        abort(404)

    qr = segno.make(f"W:{row[0]}")
    buf = io.BytesIO()
    qr.save(buf, kind="png", scale=6, border=2)
    buf.seek(0)
    return send_file(buf, mimetype="image/png", download_name=f"worker_{worker_id}.png")

@app.route("/workers/<int:worker_id>/qr.svg")
def worker_qr_svg(worker_id: int):
    pool = get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        try:
            cur.execute("SELECT token_id FROM workers WHERE id=%s;", (worker_id,))
            row = cur.fetchone()
        finally:
            cur.close()
    finally:
        pool.putconn(conn)

    if not row or not row[0]:
        abort(404)

    qr = segno.make(f"W:{row[0]}")
    buf = io.BytesIO()
    qr.save(buf, kind="svg", border=2)
    buf.seek(0)
    return send_file(buf, mimetype="image/svg+xml", download_name=f"worker_{worker_id}.svg")


# =========================
# APIs for dashboard (unchanged)
# =========================
def _normalize_worker_token(raw: str) -> str:
    raw = (raw or "").strip()
    if raw.startswith("W:"):
        return raw[2:]
    return raw

def _normalize_barcode(raw: str) -> str:
    return (raw or "").strip()

def _lookup_or_create_worker_by_token(cur, token_raw: str) -> int:
    cur.execute("SELECT id FROM workers WHERE token_id = %s;", (token_raw,))
    row = cur.fetchone()
    if row:
        return row[0]
    placeholder_name = f"Worker {token_raw[:6]}" if token_raw else "Worker"
    cur.execute("""
        INSERT INTO workers (name, token_id)
        VALUES (%s, %s)
        ON CONFLICT (token_id) DO UPDATE SET token_id = EXCLUDED.token_id
        RETURNING id;
    """, (placeholder_name, token_raw))
    return cur.fetchone()[0]

def _fetch_worker_profile(cur, worker_id: int):
    cur.execute("SELECT name, COALESCE(NULLIF(department,''),'N/A') FROM workers WHERE id=%s;", (worker_id,))
    row = cur.fetchone() or ("Unknown", "N/A")
    return row[0], row[1]

def _today_pieces_for(cur, worker_id: int, start, end) -> int:
    cur.execute("""
        SELECT COUNT(*) FROM scans
         WHERE worker_id=%s AND created_at >= %s AND created_at <= %s;
    """, (worker_id, start, end))
    return cur.fetchone()[0]


@app.route("/api/stats")
def api_stats():
    pool = get_pool()
    start, end = today_bounds_utc()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        try:
            cur.execute("SELECT COUNT(*) FROM workers;")
            total_workers = cur.fetchone()[0]

            cur.execute("""
                SELECT COUNT(DISTINCT worker_id)
                  FROM scans
                 WHERE created_at >= %s AND created_at <= %s
                   AND worker_id IS NOT NULL;
            """, (start, end))
            active_today = cur.fetchone()[0]

            cur.execute("""
                SELECT COUNT(*)
                  FROM scans
                 WHERE created_at >= %s AND created_at <= %s;
            """, (start, end))
            scans_today = cur.fetchone()[0]
        finally:
            cur.close()
        return jsonify({
            "total_workers": total_workers,
            "active_today": active_today,
            "scans_today": scans_today
        })
    finally:
        pool.putconn(conn)


@app.route("/api/activities")
def api_activities():
    limit = max(1, min(int(request.args.get("limit", 100)), 500))
    pool = get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT
                    s.created_at AS ts,
                    COALESCE(w.name, '(unknown)') AS worker,
                    NULLIF(w.department,'') AS line,
                    NULLIF(s.operation_code,'') AS operation_code,
                    NULLIF(s.barcode,'') AS barcode
                FROM scans s
                LEFT JOIN workers w ON w.id = s.worker_id
                ORDER BY s.created_at DESC NULLS LAST
                LIMIT %s;
            """, (limit,))
            rows = cur.fetchall()
            data = []
            for ts, worker, line, op, bc in rows:
                ts_iso = ts.isoformat() if ts else None
                data.append({
                    "ts": ts_iso,
                    "worker": worker,
                    "line": line or "",
                    "operation_code": op or "",
                    "barcode": bc or ""
                })
        finally:
            cur.close()
        return jsonify(data)
    finally:
        pool.putconn(conn)


# =========================
# Device endpoints (ESP32)
# =========================
@app.route("/scan", methods=["POST"])
def scan_login_or_ping():
    """
    Body: {"token_id":"W:<token>", "secret":"<DEVICE_SECRET>"}
    """
    payload = request.get_json(silent=True) or {}
    if (payload.get("secret") or "").strip() != DEVICE_SECRET:
        return jsonify({"status": "error", "message": "forbidden"}), 403

    token_raw = _normalize_worker_token(payload.get("token_id", ""))
    if not token_raw:
        return jsonify({"status":"error","message":"token_id required"}), 400

    start, end = today_bounds_utc()
    pool = get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        try:
            worker_id = _lookup_or_create_worker_by_token(cur, token_raw)
            name, department = _fetch_worker_profile(cur, worker_id)
            scans_today = _today_pieces_for(cur, worker_id, start, end)
        finally:
            cur.close()
        conn.commit()
    finally:
        pool.putconn(conn)

    return jsonify({
        "status": "success",
        "name": name,
        "department": department,
        "scans_today": scans_today,
        "earnings": scans_today * RATE_PER_PIECE
    })


@app.route("/scan_operation", methods=["POST"])
def scan_operation():
    """
    Body: {"token_id":"W:<token>","barcode":"B:...","secret":"<DEVICE_SECRET>"}
    """
    payload = request.get_json(silent=True) or {}
    if (payload.get("secret") or "").strip() != DEVICE_SECRET:
        return jsonify({"status": "error", "message": "forbidden"}), 403

    token_raw = _normalize_worker_token(payload.get("token_id", ""))
    barcode = _normalize_barcode(payload.get("barcode", ""))

    if not token_raw:
        return jsonify({"status":"error","message":"token_id required"}), 400
    if not barcode:
        return jsonify({"status":"error","message":"barcode required"}), 400

    start, end = today_bounds_utc()
    pool = get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        try:
            worker_id = _lookup_or_create_worker_by_token(cur, token_raw)

            # simple OP parse
            op_code = ""
            try:
                b = barcode[2:] if barcode.startswith("B:") else barcode
                op_code = b.split("-", 1)[0].strip() if b else ""
            except Exception:
                op_code = ""

            cur.execute("""
                INSERT INTO scans (worker_id, barcode, operation_code, created_at)
                VALUES (%s, %s, NULLIF(%s,''), NOW());
            """, (worker_id, barcode, op_code))

            scans_today = _today_pieces_for(cur, worker_id, start, end)
        finally:
            cur.close()
        conn.commit()
    finally:
        pool.putconn(conn)

    return jsonify({
        "status": "success",
        "scans_today": scans_today,
        "earnings": scans_today * RATE_PER_PIECE
    })


@app.route("/logout", methods=["POST"])
def logout():
    """
    Device handles local session; server returns success for compatibility.
    """
    payload = request.get_json(silent=True) or {}
    if (payload.get("secret") or "").strip() != DEVICE_SECRET:
        return jsonify({"status": "error", "message": "forbidden"}), 403
    return jsonify({"status": "success"})


# =========================
# Template globals
# =========================
@app.context_processor
def inject_globals():
    return dict(
        app_name="Banswara Scanner",
        brand="Banswara Scanner",
        rate_per_piece=RATE_PER_PIECE,
        current_year=datetime.now().year
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
