import os
import json
import pandas as pd
from datetime import datetime
from flask import Flask, request, jsonify, render_template, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.utils import secure_filename
import qrcode
import segno

# App configuration
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'production-secret-key-2024')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///production.db')
if app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgres://'):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# Initialize extensions
db = SQLAlchemy(app)
CORS(app)

# Ensure directories exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs('static/qrcodes', exist_ok=True)

# Database Models
class Worker(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    token_id = db.Column(db.String(50), unique=True, nullable=False)
    department = db.Column(db.String(50), nullable=False)
    line = db.Column(db.String(20))
    status = db.Column(db.String(20), default='active')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Operation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    op_no = db.Column(db.String(10), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    machine = db.Column(db.String(100))
    sub_section = db.Column(db.String(100))
    std_min = db.Column(db.Float, default=0.0)
    piece_rate = db.Column(db.Float, default=0.0)
    department = db.Column(db.String(50))
    skill_level = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ProductionOrder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_no = db.Column(db.String(50), unique=True, nullable=False)
    style_number = db.Column(db.String(100), nullable=False)
    style_name = db.Column(db.String(200))
    buyer = db.Column(db.String(100))
    total_quantity = db.Column(db.Integer, nullable=False)
    order_date = db.Column(db.DateTime, default=datetime.utcnow)
    delivery_date = db.Column(db.DateTime)
    status = db.Column(db.String(20), default='active')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Bundle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    production_order_id = db.Column(db.Integer, db.ForeignKey('production_order.id'))
    bundle_no = db.Column(db.String(50), nullable=False)
    size = db.Column(db.String(10))
    color = db.Column(db.String(50))
    qty_per_bundle = db.Column(db.Integer, nullable=False)
    assigned_line = db.Column(db.String(20))
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Routes matching the screenshots
@app.route('/')
def dashboard():
    return render_template('esp32_scanner.html')

@app.route('/esp32-scanner')
def esp32_scanner():
    return render_template('esp32_scanner.html')

@app.route('/reports')
def reports():
    return render_template('reports.html')

@app.route('/file-upload')
def file_upload():
    return render_template('file_upload.html')

@app.route('/production-order')
def production():
    return render_template('production_order.html')

@app.route('/workers')
def workers():
    workers = Worker.query.all()
    return render_template('workers.html', workers=workers)

@app.route('/operations')
def operations():
    operations = Operation.query.all()
    return render_template('operations.html', operations=operations)

@app.route('/bundles')
def bundles():
    bundles = Bundle.query.all()
    return render_template('bundles.html', bundles=bundles)

# File upload routes
@app.route('/upload-ob-file', methods=['POST'])
def upload_ob_file():
    if 'ob_file' not in request.files:
        flash('No file selected', 'error')
        return redirect(url_for('file_upload'))

    file = request.files['ob_file']
    if file.filename == '':
        flash('No file selected', 'error')
        return redirect(url_for('file_upload'))

    if file:
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        try:
            # Parse Excel file
            df = pd.read_excel(filepath)
            operations_count = 0

            for _, row in df.iterrows():
                std_min = float(row.get('StdMin', 0) or 0)
                piece_rate = std_min * 0.75

                existing_op = Operation.query.filter_by(op_no=str(row.get('OpNo', ''))).first()
                if not existing_op:
                    operation = Operation(
                        op_no=str(row.get('OpNo', '')),
                        name=str(row.get('Description', '')),
                        description=str(row.get('Description', '')),
                        machine=str(row.get('Machine', '')),
                        sub_section=str(row.get('SubSection', '')),
                        std_min=std_min,
                        piece_rate=piece_rate,
                        department=str(row.get('SubSection', ''))
                    )
                    db.session.add(operation)
                    operations_count += 1

            db.session.commit()
            flash(f'Successfully uploaded OB file with {operations_count} operations', 'success')
        except Exception as e:
            flash(f'Error processing file: {str(e)}', 'error')

    return redirect(url_for('file_upload'))

@app.route('/upload-production-order', methods=['POST'])
def upload_production_order():
    if 'production_file' not in request.files:
        flash('No file selected', 'error')
        return redirect(url_for('file_upload'))

    file = request.files['production_file']
    if file.filename == '':
        flash('No file selected', 'error')
        return redirect(url_for('file_upload'))

    if file:
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        flash('Production order uploaded successfully', 'success')

    return redirect(url_for('file_upload'))

# ESP32 Scan endpoint
@app.route('/scan', methods=['POST'])
def scan_endpoint():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data received'}), 400

        token_id = data.get('token_id', '').replace('W:', '')
        action = data.get('action', 'login')

        # Simulate worker lookup
        worker_names = {
            'RK001': 'Rajesh Kumar',
            'PS002': 'Priya Sharma', 
            'AS003': 'Amit Singh',
            'SD004': 'Sunita Devi'
        }

        worker_name = worker_names.get(token_id, 'Unknown Worker')

        return jsonify({
            'success': True,
            'message': f'Worker {worker_name} {action} successful',
            'worker': {
                'name': worker_name,
                'token_id': token_id,
                'action': action,
                'timestamp': datetime.now().isoformat()
            }
        })

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# Initialize database
@app.before_first_request
def create_tables():
    db.create_all()

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
