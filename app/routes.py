from flask import Blueprint, render_template, send_from_directory, current_app, jsonify
import os

bp = Blueprint("main", __name__)

@bp.get("/")
def home():
    # The index.html was copied from the provided UI to preserve pixel fidelity
    return render_template("index.html")

# Small health check
@bp.get("/healthz")
def healthz():
    return jsonify({"ok": True})
