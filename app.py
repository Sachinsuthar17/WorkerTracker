import os
from datetime import datetime, timedelta
from flask import (
    Flask, request, jsonify, render_template, redirect, url_for, send_file, abort, flash
)

# =====================================================================
# App config
# =====================================================================
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret")

# Render / Environment vars we show in the UI footer and Settings
RATE_PER_PIECE = float(os.getenv("RATE_PER_PIECE", "1.00"))
DEVICE_SECRET = os.getenv("DEVICE_SECRET", "garment_erp_2024_secret")
APP_BRAND = os.getenv("APP_BRAND", "Garment ERP")

# =====================================================================
# In-memory placeholders so the UI renders right now on Render
# Replace with your DB queries in the TODOs below.
# =====================================================================

# Workers
WORKERS = [
    {"id": 1, "name": "RAHUL SHARMA", "token_id": "RAHUL123", "department": "STITCHING A1"},
    {"id": 2, "name": "PRIYA VERMA",  "token_id": "PRIYA567", "department": "STITCHING B3"},
    {"id": 3, "name": "AMIT KUMAR",   "token_id": "AMIT909",  "department": "FINISHING C1"},
]

# Production Orders (list view + optional current active)
ORDERS = [
    {
        "order_no": "65001001140",
        "style_no": "SAINTX1",
        "style_name": "SAINTX MENS BLAZER",
        "buyer": "BANSWARA GARMENTS",
        "order_qty": 1119,
        "delivery_date": "30-11-2024",
        "status": "active",
        "created_at": "2024-11-01 10:00:00",
    }
]

ACTIVE_ORDER = {
    "order_no": "65001001140",
    "style": "SAINTX MENS BLAZER",
    "buyer": "BANSWARA GARMENTS",
    "quantity": 1119,
    "delivery": "30-11-2024",
    "colors": [
        {"code": "BLK3", "qty": 200},
        {"code": "BLK4", "qty": 250},
        {"code": "GREN", "qty": 180},
        {"code": "KHA1", "qty": 170},
        {"code": "LGR1", "qty": 160},
        {"code": "MDGR", "qty": 159},
    ],
}

# Bundles
BUNDLES = [
    {
        "barcode": "BNDL-001-036-050",
        "status": "IN_PROGRESS",
        "style": "SAINTX MENS BLAZER",
        "color": "BLK3",
        "size_range": "036-050",
        "quantity": 50,
        "current_op": "STITCH FRONT PANEL",
        "progress": 42,
        "earned": 210.0,
    }
]

# Live / Recent activities (what the dashboard’s “Recent Activity” shows)
RECENT_ACTIVITIES = [
    {
        "ts": (datetime.utcnow() - timedelta(minutes=i * 7)).isoformat() + "Z",
        "worker": WORKERS[i % len(WORKERS)]["name"],
        "line": WORKERS[i % len(WORKERS)]["department"],
        "operation_code": f"OP-{100+i}",
        "barcode": f"BNDL-00{i}-036-050",
    }
    for i in range(1, 11)
]

# =====================================================================
# Helpers (DB: plug your real code if you have sqlite/psql etc.)
# =====================================================================

def paginate(items, limit, offset=0):
    limit = max(1, min(int(limit or 100), 500))
    offset = max(0, int(offset or 0))
    return items[offset: offset + limit]

# =====================================================================
# Pages
# =====================================================================

@app.route("/")
def dashboard():
    """
    Dashboard (dark UI) – uses dashboard.html
    Shows stat tiles + recent activity table.
    """
    # TODO replace with DB queries
    total_workers = len(WORKERS)
    scans_today = len([r for r in RECENT_ACTIVITIES
                       if datetime.fromisoformat(r["ts"].replace("Z", "")) > datetime.utcnow() - timedelta(days=1)])
    active_today = total_workers  # If you track presence separately, compute here.

    # dashboard.html consumes AlpineJS dashboard(), but we can also pass data if needed.
    return render_template(
        "dashboard.html",
        rate_per_piece=RATE_PER_PIECE,
        APP_BRAND=APP_BRAND,
        # the Alpine page calls /api endpoints on its own; we still pass footer vars
    )


@app.route("/orders")
def production_orders_page():
    """
    Production Orders page – matches screenshot (form + active order info).
    """
    # TODO: If you track a single “active” record, load it. We pass ACTIVE_ORDER placeholder now.
    styles = ["SAINTX MENS BLAZER"]
    return render_template(
        "production_orders.html",
        active=ACTIVE_ORDER,
        styles=styles,
        orders=ORDERS,
        rate_per_piece=RATE_PER_PIECE,
        APP_BRAND=APP_BRAND,
    )


@app.route("/bundles")
def bundles_page():
    """
    Bundle Management – create bundle + active bundle cards.
    """
    colors = ["BLK3", "BLK4", "GREN", "KHA1", "LGR1", "MDGR", "NYYL"]
    return render_template(
        "bundles.html",
        bundles=BUNDLES,
        orders=[{"id": 1, "order_no": ACTIVE_ORDER["order_no"], "style": ACTIVE_ORDER["style"]}],
        colors=colors,
        rate_per_piece=RATE_PER_PIECE,
        APP_BRAND=APP_BRAND,
    )


@app.route("/live")
def live_scanning_page():
    """
    Live Scanning – recent scans + worker activity.
    """
    # TODO: Replace with live metrics
    live = {"active_scans": 0, "avg_time": "2.5 hrs", "efficiency": "104%"}
    workers_state = [
        {"name": w["name"], "department": w["department"], "status": "OK"}
        for w in WORKERS
    ]
    recent = [
        {"bundle": r["barcode"], "worker": r["worker"], "operation": r["operation_code"],
         "time": datetime.fromisoformat(r["ts"].replace("Z","")).strftime("%d-%m %H:%M")}
        for r in RECENT_ACTIVITIES[:10]
    ]
    return render_template(
        "live_scanning.html",
        live=live,
        recent=recent,
        workers=workers_state,
        device_secret=DEVICE_SECRET,
        rate_per_piece=RATE_PER_PIECE,
        APP_BRAND=APP_BRAND,
    )


@app.route("/reports")
def reports_page():
    """
    Reports & Analytics – worker performance + export links
    """
    # TODO: Replace with aggregate metrics
    stats = {"total_workers": len(WORKERS), "avg_efficiency": "104%", "pieces_today": 150}
    worker_perf = [
        {"name": w["name"], "department": w["department"], "efficiency": "102%", "earnings": 180.0}
        for w in WORKERS
    ]
    return render_template(
        "reports.html",
        stats=stats,
        worker_perf=worker_perf,
        rate_per_piece=RATE_PER_PIECE,
        APP_BRAND=APP_BRAND,
    )


@app.route("/settings")
def settings_page():
    """
    Settings – shows environment and accent color picker
    """
    return render_template(
        "settings.html",
        rate_per_piece=RATE_PER_PIECE,
        APP_BRAND=APP_BRAND,
    )

# =====================================================================
# Workers (kept minimal to match your workers.html template)
# Plug in your DB as needed.
# =====================================================================

@app.route("/workers", methods=["GET"])
def workers_page():
    q = (request.args.get("q") or "").strip().lower()
    if q:
        filtered = [w for w in WORKERS if q in w["name"].lower()
                    or q in w["token_id"].lower()
                    or q in (w.get("department") or "").lower()]
    else:
        filtered = WORKERS
    return render_template(
        "workers.html",
        workers=filtered,
        search=q,
        rate_per_piece=RATE_PER_PIECE,
        APP_BRAND=APP_BRAND,
    )

@app.route("/workers/create", methods=["POST"])
def worker_create():
    form = request.form
    name = (form.get("name") or "").strip().upper()
    token_id = (form.get("token_id") or "").strip().upper()
    department = (form.get("department") or "").strip().upper() or None
    if not name or not token_id:
        flash("Name and Token are required.", "error")
        return redirect(url_for("workers_page"))
    new_id = (max([w["id"] for w in WORKERS]) + 1) if WORKERS else 1
    WORKERS.append({"id": new_id, "name": name, "token_id": token_id, "department": department})
    flash("Worker created.", "success")
    return redirect(url_for("workers_page"))

@app.route("/workers/<int:wid>/edit", methods=["POST"])
def worker_edit(wid):
    form = request.form
    for w in WORKERS:
        if w["id"] == wid:
            w["name"] = (form.get("name") or w["name"]).strip().upper()
            w["token_id"] = (form.get("token_id") or w["token_id"]).strip().upper()
            w["department"] = (form.get("department") or w.get("department") or "").strip().upper() or None
            flash("Worker saved.", "success")
            break
    return redirect(url_for("workers_page"))

@app.route("/workers/<int:wid>/delete", methods=["POST"])
def worker_delete(wid):
    global WORKERS
    before = len(WORKERS)
    WORKERS = [w for w in WORKERS if w["id"] != wid]
    if len(WORKERS) < before:
        flash("Worker deleted.", "success")
    else:
        flash("Worker not found.", "error")
    return redirect(url_for("workers_page"))

# Print QR & PNG endpoints are referenced in workers.html; supply simple placeholders
from io import BytesIO
import qrcode

@app.route("/workers/<int:wid>/qr.png")
def worker_qr_png(wid):
    w = next((x for x in WORKERS if x["id"] == wid), None)
    if not w:
        abort(404)
    payload = f"W:{w['token_id']}"
    img = qrcode.make(payload)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")

@app.route("/workers/<int:wid>/print")
def worker_print(wid):
    w = next((x for x in WORKERS if x["id"] == wid), None)
    if not w:
        abort(404)
    # print_qr.html already exists in your repo
    return render_template("print_qr.html", worker=w)

# Map workers.html form action URLs to the endpoints above, matching the template names
# (If your template uses different endpoint names, point them here)
app.add_url_rule("/worker/create", view_func=worker_create, methods=["POST"])
app.add_url_rule("/worker/<int:wid>/edit", view_func=worker_edit, methods=["POST"], endpoint="worker_edit")
app.add_url_rule("/worker/<int:wid>/delete", view_func=worker_delete, methods=["POST"], endpoint="worker_delete")
app.add_url_rule("/worker/<int:wid>/qr.png", view_func=worker_qr_png, methods=["GET"], endpoint="worker_qr_png")
app.add_url_rule("/worker/<int:wid>/print", view_func=worker_print, methods=["GET"], endpoint="worker_print")

# =====================================================================
# Operations (optional — stubs to satisfy template navigation)
# =====================================================================

@app.route("/operations")
def operations_page():
    # TODO: Replace with your operations list
    operations = [
        {"code": "OP-101", "desc": "STITCH FRONT PANEL"},
        {"code": "OP-102", "desc": "JOIN SHOULDERS"},
    ]
    return render_template(
        "operations.html",
        operations=operations,
        rate_per_piece=RATE_PER_PIECE,
        APP_BRAND=APP_BRAND,
    )

@app.route("/assign")
def assign_operation_page():
    # TODO: Replace with your assign UI data
    return render_template(
        "assign_operation.html",
        rate_per_piece=RATE_PER_PIECE,
        APP_BRAND=APP_BRAND,
    )

# =====================================================================
# API used by the dashboard (AlpineJS) – keep these names the same
# =====================================================================

@app.route("/api/stats")
def api_stats():
    """
    Returns counts for the stat tiles.
    """
    # TODO: Replace with DB queries
    total_workers = len(WORKERS)
    active_today = total_workers
    scans_today = len([r for r in RECENT_ACTIVITIES
                       if datetime.fromisoformat(r["ts"].replace("Z","")) > datetime.utcnow() - timedelta(days=1)])
    return jsonify({
        "total_workers": total_workers,
        "active_today": active_today,
        "scans_today": scans_today,
    })

@app.route("/api/activities")
def api_activities():
    """
    Recent activity rows for the dashboard table.
    Accepts ?limit=100
    """
    limit = request.args.get("limit", 100, type=int)
    rows = paginate(sorted(RECENT_ACTIVITIES, key=lambda r: r["ts"], reverse=True), limit)
    return jsonify(rows)

# =====================================================================
# Health + start
# =====================================================================

@app.route("/health")
def health():
    return jsonify({"ok": True, "ts": datetime.utcnow().isoformat() + "Z"})

if __name__ == "__main__":
    # For local debug; Render will use gunicorn via Procfile
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
