#!/usr/bin/env python3
"""
Sample data creation script for Production Management System
Run this script after deployment to populate the database with sample data
"""

import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import app, db, Worker, Operation, ProductionOrder, Bundle, WorkerBundle
from datetime import datetime

def create_sample_data():
    """Create sample data for testing and demonstration"""

    with app.app_context():
        # Create tables
        db.create_all()

        # Sample Workers
        workers = [
            Worker(name="Rajesh Kumar", token_id="RK001", department="SLEEVE", line="Line-1"),
            Worker(name="Priya Sharma", token_id="PS002", department="COLLAR", line="Line-2"),
            Worker(name="Amit Singh", token_id="AS003", department="LINING", line="Line-3"),
            Worker(name="Sunita Devi", token_id="SD004", department="BODY", line="Line-1"),
            Worker(name="Vikram Yadav", token_id="VY005", department="ASSE-1", line="Line-4"),
        ]

        # Sample Operations
        operations = [
            Operation(op_no="5001", name="Loading Sleeve- Jkt", piece_rate=0.21, department="SLEEVE"),
            Operation(op_no="599", name="Attach Fusing to Sleeve bottom", piece_rate=0.34, department="SLEEVE"),
            Operation(op_no="5191", name="Marking collar pick", piece_rate=0.11, department="COLLAR"),
            Operation(op_no="5021", name="Loading Lining", piece_rate=0.26, department="LINING"),
            Operation(op_no="5073", name="Loading Line Body", piece_rate=0.20, department="BODY"),
        ]

        # Sample Production Order
        production_order = ProductionOrder(
            order_no="650010011410",
            style_number="SAINTX MENS BLAZER",
            style_name="MEN'S PARTIALLY LINED BLAZER",
            buyer="BANSWARA GARMENTS",
            total_quantity=1119
        )

        # Add all data to database
        for worker in workers:
            db.session.add(worker)

        for operation in operations:
            db.session.add(operation)

        db.session.add(production_order)
        db.session.commit()

        # Generate sample bundles (12 bundles)
        bundle_qty = 93  # 1119 pieces / 12 bundles ≈ 93 per bundle

        for i in range(12):
            bundle = Bundle(
                production_order_id=production_order.id,
                bundle_no=f"650010011410-B{i+1:02d}",
                qty_per_bundle=bundle_qty if i < 11 else 1119 - (bundle_qty * 11),
                assigned_line=f"Line-{(i % 4) + 1}",
                status="pending"
            )
            db.session.add(bundle)

        db.session.commit()

        print("✅ Sample data created successfully!")
        print(f"✅ Created {len(workers)} workers")
        print(f"✅ Created {len(operations)} operations")
        print(f"✅ Created 1 production order with 12 bundles")
        print("\n🚀 You can now start using the system!")

if __name__ == "__main__":
    create_sample_data()
