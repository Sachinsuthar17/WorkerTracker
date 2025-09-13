from app import create_app, db
from app.models import Worker, Log, ProductionOrder, Bundle, BundleOperation, Assignment
from datetime import datetime
app = create_app()

with app.app_context():
    db.drop_all()
    db.create_all()
    # Sample workers
    depts = ["SLEEVE","COLLAR","LINING","BODY","ASSE-1","ASSE-2","FLAP","BACK","POST ASSEMBLY"]
    workers = []
    for i in range(1,9+1):
        w = Worker(name=f"Worker {i}", token_id=f"100{i}", department=depts[i % len(depts)])
        workers.append(w); db.session.add(w)
    db.session.commit()

    # Sample order and 12 bundles (total 1119 distributed)
    order = ProductionOrder(order_number="650010011410", brand="Banswara", total_pieces=1119, raw_upload_reference="19908610.pdf")
    db.session.add(order); db.session.flush()
    base = order.total_pieces // 12
    rem = order.total_pieces % 12
    bundles = []
    for i in range(12):
        qty = base + (1 if i < rem else 0)
        b = Bundle(order_id=order.id, bundle_number=i+1, pieces_assigned=qty, pieces_completed=0)
        db.session.add(b); bundles.append(b)
    db.session.commit()

    # Add a couple of ops per bundle with editable rates
    for b in bundles:
        db.session.add(BundleOperation(bundle_id=b.id, operation_name="SNLS", rate_per_piece=1.2))
        db.session.add(BundleOperation(bundle_id=b.id, operation_name="BH", rate_per_piece=0.8))
    db.session.commit()

    print("Database initialized.")
