# Garment ERP – Flask (ESP32 integrated)

## Quick start (local)
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
set DEVICE_SECRET=garment_erp_2024_secret
set RATE_PER_PIECE=25
python app.py
# open http://127.0.0.1:5000

## PostgreSQL (Render)
set DATABASE_URL=postgresql+psycopg2://USER:PASS@HOST:5432/DBNAME
gunicorn app:app