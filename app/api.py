from flask import Blueprint, request, jsonify, current_app
from sqlalchemy import or_
from . import db
from .models import Worker, Log, ProductionOrder, Bundle, BundleOperation, Assignment
from datetime import datetime, timezone
import os, csv
from io import StringIO, BytesIO
import pandas as pd

api = Blueprint("api", __name__)

def utcnow():
    return datetime.now(timezone.utc)

def bundle_state_for(worker: Worker):
    # find active assignment if any
    assign = Assignment.query.filter_by(worker_id=worker.id, completed_at=None).order_by(Assignment.assigned_at.desc()).first()
    if not assign:
        return None
    bundle = Bundle.query.get(assign.bundle_id)
    ops = BundleOperation.query.filter_by(bundle_id=bundle.id).all()
    return {
        "bundle_id": bundle.id,
        "bundle_number": bundle.bundle_number,
        "pieces_assigned": bundle.pieces_assigned,
        "pieces_completed": bundle.pieces_completed,
        "operations": [{"operation_name": o.operation_name, "rate_per_piece": o.rate_per_piece} for o in ops],
        "pieces_remaining": max(0, (bundle.pieces_assigned or 0) - (bundle.pieces_completed or 0))
    }

@api.post("/scan")
def scan():
    data = request.get_json(silent=True) or {}
    token_id = (data.get("token_id") or "").strip()
    scanner_id = (data.get("scanner_id") or "UNKNOWN").strip()
    if not token_id:
        return jsonify({"success": False, "error": "token_id required"}), 400

    worker = Worker.query.filter_by(token_id=token_id).first()
    if not worker:
        log = Log(token_id=token_id, action="error", scanner_id=scanner_id, metadata={"reason": "unknown_token"}, timestamp=utcnow())
        db.session.add(log); db.session.commit()
        return jsonify({"success": False, "error": "Unknown token"}), 404

    # Forced logout of others on same scanner (conservative rule)
    others = Worker.query.filter(Worker.is_logged_in.is_(True), Worker.token_id != token_id, Worker.last_scanner_id == scanner_id).all()
    for o in others:
        o.is_logged_in = False
        db.session.add(Log(worker_id=o.id, token_id=o.token_id, action="logout", scanner_id=scanner_id, timestamp=utcnow(), metadata={"forced": True}))

    # Toggle login for this worker
    if worker.is_logged_in:
        worker.is_logged_in = False
        action = "logout"
    else:
        worker.is_logged_in = True
        worker.last_scanner_id = scanner_id
        action = "login"
    db.session.add(worker)
    db.session.add(Log(worker_id=worker.id, token_id=token_id, action=action, scanner_id=scanner_id, timestamp=utcnow()))
    db.session.commit()

    resp = {
        "success": True,
        "worker": {
            "id": worker.id,
            "name": worker.name,
            "token_id": worker.token_id,
            "department": worker.department,
            "login_state": "IN" if worker.is_logged_in else "OUT",
        },
        "current_bundle": bundle_state_for(worker),
        "message": f"{'Logged in' if worker.is_logged_in else 'Logged out'}"
    }
    return jsonify(resp)

@api.get("/worker/<token_id>")
def get_worker(token_id):
    worker = Worker.query.filter_by(token_id=token_id).first()
    if not worker:
        return jsonify({"success": False, "error": "Unknown token"}), 404
    return jsonify({
        "success": True,
        "worker": {
            "id": worker.id,
            "name": worker.name,
            "token_id": worker.token_id,
            "department": worker.department,
            "login_state": "IN" if worker.is_logged_in else "OUT",
        },
        "current_bundle": bundle_state_for(worker),
    })

@api.post("/admin/assign")
def assign_bundle():
    data = request.get_json(silent=True) or {}
    token_id = data.get("token_id")
    bundle_id = data.get("bundle_id")
    worker = Worker.query.filter_by(token_id=token_id).first()
    bundle = Bundle.query.get(bundle_id)
    if not worker or not bundle:
        return jsonify({"success": False, "error": "Invalid worker or bundle"}), 400
    # close prior assignments
    db.session.query(Assignment).filter_by(worker_id=worker.id, completed_at=None).update({"completed_at": utcnow()})
    db.session.add(Assignment(worker_id=worker.id, bundle_id=bundle.id))
    db.session.commit()
    return jsonify({"success": True})

@api.post("/admin/upload_operations")
def upload_operations():
    if "file" not in request.files:
        return jsonify({"success": False, "error": "No file"}), 400
    f = request.files["file"]
    try:
        df = pd.read_excel(f) if f.filename.lower().endswith((".xlsx",".xls")) else pd.read_csv(f)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

    # Expecting columns: operation_name, rate_per_piece
    required = {"operation_name", "rate_per_piece"}
    missing = required - set([c.strip().lower() for c in df.columns])
    if missing:
        return jsonify({"success": False, "error": f"Missing columns: {', '.join(sorted(missing))}"}), 400
    # return summary only; rates are applied when a PO is created for clarity
    return jsonify({"success": True, "rows": len(df)})

@api.post("/admin/upload_po")
def upload_po():
    # Accept either CSV or Excel. We'll create a demo ProductionOrder and 12 bundles by distributing totals.
    if "file" not in request.files:
        return jsonify({"success": False, "error": "No file"}), 400
    f = request.files["file"]
    # For demo, if a numeric total is provided in query string, use it; else default 1119
    total = int(request.args.get("total", "1119"))
    order = ProductionOrder(order_number="PO-DEMO", brand="Demo", total_pieces=total, raw_upload_reference=f.filename)
    db.session.add(order); db.session.flush()

    # Distribution into 12 bundles (rounded, conservative):
    base = total // 12
    rem = total % 12
    for i in range(12):
        qty = base + (1 if i < rem else 0)
        db.session.add(Bundle(order_id=order.id, bundle_number=i+1, pieces_assigned=qty, pieces_completed=0))
    db.session.commit()
    return jsonify({"success": True, "order_id": order.id, "bundles": 12, "total_pieces": total})

@api.get("/admin/logs")
def get_logs():
    page = int(request.args.get("page", "1"))
    per = min(int(request.args.get("per", "50")), 200)
    q = Log.query.order_by(Log.timestamp.desc()).offset((page-1)*per).limit(per)
    rows = [{
        "id": r.id,
        "token_id": r.token_id,
        "action": r.action,
        "scanner_id": r.scanner_id,
        "timestamp": r.timestamp.isoformat(),
        "metadata": r.metadata,
    } for r in q]
    return jsonify({"success": True, "rows": rows})
