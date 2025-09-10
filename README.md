# Worker Per Piece - Complete System

This is a production-ready Flask app with:
- `/scan` ingestion for ESP32 scanners
- Dashboard, Workers, Bundles, Operations, Assign Task, Reports
- SQLite database (`factory.db`) with tables for users, bundles, operations, scans and tasks
- Built-in QR PNG endpoints for workers and bundles
- CSV export

## Run locally

```bash
python db_setup.py   # create factory.db
python app.py        # start on http://localhost:5000
```

## Deploy (Render/Heroku)
- Use the provided `Procfile`, `requirements.txt`, and `runtime.txt`.
- Set environment variables:
  - `DEVICE_SECRET` (required for ESP32 auth)
  - `SECRET_KEY` (Flask session)
  - `AUTO_CREATE=1` if you want unknown workers/bundles/ops created automatically.

## ESP32
Upload `esp32/esp32_scan.ino` after editing WiFi and `SERVER_URL`.
