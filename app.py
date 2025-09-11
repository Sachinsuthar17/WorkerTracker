"""Main Flask application for the Garment ERP system.

This module wires together the SQLAlchemy models, configures routes for the
web UI and JSON API, and serves HTML templates.  It also exposes an
``/events`` endpoint using Server-Sent Events (SSE) to push live updates of
daily scan counts to the browser.
"""

import os
from datetime import datetime
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    jsonify,
    send_file,
    Response,
)
from sqlalchemy import desc

from config import Config
from models import db, User, Bundle, Operation, Task, Scan
from qr_utils import make_worker_qr, make_bundle_qr


app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)


def _current_day_start() -> datetime:
    """Return the start of the current UTC day (midnight)."""
    now = datetime.utcnow()
    return datetime(now.year, now.month, now.day)


@app.route("/")
def index():
    """Redirect root URL to the dashboard."""
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
def dashboard():
    """Render the main dashboard page.

    This view aggregates simple statistics: total workers, total bundles,
    today's scan count, and approximate earnings (scans * base rate).  It
    also fetches recent scans for display in a table.
    """
    total_workers = User.query.count()
    total_bundles = Bundle.query.count()
    today_scans = Scan.query.filter(Scan.timestamp >= _current_day_start()).count()
    earnings_today = today_scans * 0.50  # base rate per scan

    recent = (
        db.session.query(
            Scan.timestamp,
            User.name.label("worker_name"),
            Operation.sequence.label("operation_sequence"),
        )
        .join(User, Scan.worker_id == User.id)
        .join(Operation, Scan.operation_id == Operation.id)
        .order_by(desc(Scan.timestamp))
        .limit(10)
        .all()
    )
    return render_template(
        "dashboard.html",
        total_workers=total_workers,
        total_bundles=total_bundles,
        active_scans=today_scans,
        earnings_today=earnings_today,
        recent=recent,
    )


@app.route("/events")
def events():
    """Server-Sent Events (SSE) endpoint for live scan counts.

    The browser opens an EventSource connection to this endpoint.  Every 5
    seconds the current day's scan count is sent to the client as JSON.
    """

    def stream():
        import time
        while True:
            # Rollback any uncommitted session state to avoid stale reads
            db.session.rollback()
            cnt = Scan.query.filter(Scan.timestamp >= _current_day_start()).count()
            yield f"data: {{\"today_scans\": {cnt}}}\n\n"
            time.sleep(5)

    return Response(stream(), mimetype="text/event-stream")


@app.route("/scan", methods=["POST"])
def scan():
    """API endpoint for recording scans from an ESP32.

    Expects a JSON payload with ``token_id``, ``bundle_id`` and
    ``operation_id``.  Looks up the corresponding records and inserts a
    new ``Scan``.  Returns a simple JSON response with the worker name
    and IDs used.  If the task exists and is not completed, its status
    changes to ``in_progress``.
    """
    data = request.get_json(force=True)
    token_id = data.get("token_id")
    bundle_id = data.get("bundle_id")
    operation_id = data.get("operation_id")

    # Validate input
    if not token_id or not bundle_id or not operation_id:
        return (
            jsonify({"ok": False, "error": "token_id, bundle_id, operation_id required"}),
            400,
        )

    worker = User.query.filter_by(token_id=str(token_id)).first()
    bundle = Bundle.query.get(int(bundle_id)) if str(bundle_id).isdigit() else None
    operation = (
        Operation.query.get(int(operation_id)) if str(operation_id).isdigit() else None
    )
    if not worker or not bundle or not operation:
        return (
            jsonify({"ok": False, "error": "Invalid worker/bundle/operation"}),
            404,
        )

    # Insert new Scan
    scan_record = Scan(
        worker_id=worker.id,
        bundle_id=bundle.id,
        operation_id=operation.id,
        timestamp=datetime.utcnow(),
    )
    db.session.add(scan_record)

    # Update task status if applicable
    task = (
        Task.query.filter_by(worker_id=worker.id, bundle_id=bundle.id)
        .order_by(desc(Task.assigned_at))
        .first()
    )
    if task and task.status != "done":
        task.status = "in_progress"

    db.session.commit()
    return jsonify(
        {
            "ok": True,
            "worker": worker.name,
            "bundle": bundle.id,
            "operation": operation.sequence,
        }
    )


@app.route("/users", methods=["GET", "POST"])
def users():
    """List and create users.

    ``GET`` renders a table of existing users with their QR codes.  ``POST``
    creates a new user from form data and generates a QR code on the fly.
    """
    if request.method == "POST":
        name = request.form.get("name")
        token_id = request.form.get("token_id")
        dept = request.form.get("department")
        new_user = User(name=name, token_id=token_id, department=dept)
        db.session.add(new_user)
        db.session.commit()
        # Create QR after commit to use the assigned ID in the file name
        path = make_worker_qr(
            os.path.join("static", "qrcodes"), token_id, f"worker_{new_user.id}.png"
        )
        new_user.qr_path = path
        db.session.commit()
        return redirect(url_for("users"))

    users = User.query.order_by(User.id.asc()).all()
    return render_template("users.html", users=users)


@app.route("/users/<int:uid>/delete", methods=["POST"])
def delete_user(uid: int):
    """Delete a user (worker) from the database."""
    user = User.query.get_or_404(uid)
    db.session.delete(user)
    db.session.commit()
    return redirect(url_for("users"))


@app.route("/bundles", methods=["GET", "POST"])
def bundles():
    """Create and list bundles."""
    if request.method == "POST":
        order_id = request.form.get("order_id")
        size = request.form.get("size")
        color = request.form.get("color")
        qty = int(request.form.get("qty") or 0)
        bundle = Bundle(order_id=order_id, size=size, color=color, qty=qty)
        db.session.add(bundle)
        db.session.commit()
        payload = f"{bundle.id}|{bundle.order_id}|{bundle.size}|{bundle.color}"
        bundle.qr_path = make_bundle_qr(
            os.path.join("static", "qrcodes"), payload, f"bundle_{bundle.id}.png"
        )
        db.session.commit()
        return redirect(url_for("bundles"))

    bundles = Bundle.query.order_by(Bundle.id.desc()).limit(100).all()
    return render_template("bundles.html", bundles=bundles)


@app.route("/assign_task", methods=["GET", "POST"])
def assign_task():
    """Assign bundles to workers.

    ``GET`` displays a form for assigning tasks and shows recent assignments.
    ``POST`` processes the assignment and returns to the same page.
    """
    if request.method == "POST":
        worker_id = int(request.form.get("worker_id"))
        bundle_id = int(request.form.get("bundle_id"))
        task = Task(worker_id=worker_id, bundle_id=bundle_id, status="assigned")
        db.session.add(task)
        db.session.commit()
        return redirect(url_for("assign_task"))

    workers = User.query.all()
    bundles = Bundle.query.all()
    tasks = Task.query.order_by(desc(Task.assigned_at)).limit(50).all()
    return render_template(
        "assign_task.html", workers=workers, bundles=bundles, tasks=tasks
    )


@app.route("/reports")
def reports():
    """Display reports page with export links."""
    return render_template("reports.html")


@app.route("/reports/download")
def download_report():
    """Download scan records as CSV or Excel (xlsx)."""
    kind = request.args.get("kind", "csv")
    since = request.args.get("since")
    query = Scan.query
    if since:
        try:
            dt = datetime.fromisoformat(since)
            query = query.filter(Scan.timestamp >= dt)
        except ValueError:
            pass
    scans = (
        db.session.query(
            Scan.id,
            Scan.timestamp,
            User.name.label("worker"),
            Bundle.id.label("bundle"),
            Operation.sequence.label("operation"),
        )
        .join(User, Scan.worker_id == User.id)
        .join(Bundle, Scan.bundle_id == Bundle.id)
        .join(Operation, Scan.operation_id == Operation.id)
        .filter(Scan.id.in_([s.id for s in query]))
        .order_by(Scan.timestamp.asc())
        .all()
    )
    rows = [("id", "timestamp", "worker", "bundle", "operation")]
    for s in scans:
        rows.append(
            (
                s.id,
                s.timestamp.isoformat(),
                s.worker,
                s.bundle,
                s.operation,
            )
        )
    if kind == "xlsx":
        import pandas as pd
        df = pd.DataFrame(rows[1:], columns=rows[0])
        fp = "reports_scans.xlsx"
        df.to_excel(fp, index=False)
        return send_file(fp, as_attachment=True)
    else:
        fp = "reports_scans.csv"
        import csv
        with open(fp, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerows(rows)
        return send_file(fp, as_attachment=True, download_name="reports_scans.csv")


@app.context_processor
def inject_now():
    """Inject current UTC timestamp into templates for cache busting."""
    return {"now": datetime.utcnow()}


if __name__ == "__main__":
    # Ensure tables exist when running directly
    with app.app_context():
        db.create_all()
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)