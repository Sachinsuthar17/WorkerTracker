import json, os, io
import pytest
from app import create_app, db
from app.models import Worker, Bundle, ProductionOrder

@pytest.fixture()
def client(tmp_path):
    app = create_app(testing=True)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    with app.app_context():
        db.create_all()
        db.session.add(Worker(name="Alice", token_id="ABC123", department="SLEEVE"))
        db.session.add(Worker(name="Bob", token_id="XYZ999", department="BODY"))
        po = ProductionOrder(order_number="PO1", brand="Demo", total_pieces=120)
        db.session.add(po); db.session.flush()
        for i in range(12):
            db.session.add(Bundle(order_id=po.id, bundle_number=i+1, pieces_assigned=10))
        db.session.commit()
    return app.test_client()

def test_scan_login_logout(client):
    r = client.post("/api/scan", json={"token_id":"ABC123","scanner_id":"S1"})
    assert r.status_code == 200 and r.json["worker"]["login_state"] == "IN"
    r = client.post("/api/scan", json={"token_id":"ABC123","scanner_id":"S1"})
    assert r.status_code == 200 and r.json["worker"]["login_state"] == "OUT"

def test_forced_logout(client):
    client.post("/api/scan", json={"token_id":"ABC123","scanner_id":"S1"})  # Alice IN
    client.post("/api/scan", json={"token_id":"XYZ999","scanner_id":"S1"})  # Bob forces Alice OUT
    r = client.get("/api/worker/ABC123")
    assert r.json["worker"]["login_state"] == "OUT"

def test_upload_po_creates_12_bundles(client):
    data = {"file": (io.BytesIO(b"dummy"), "dummy.pdf")}
    r = client.post("/api/admin/upload_po?total=1119", data=data, content_type="multipart/form-data")
    assert r.status_code == 200
    assert r.json["bundles"] == 12 and r.json["total_pieces"] == 1119
