# Garment ERP – Worker Per Piece Tracking

This project implements a simplified worker‐per‐piece tracking system inspired
by the provided UI mockups.  It consists of a Flask web application backed
by PostgreSQL, QR code generation utilities, a small ESP32 sketch for
scanning workers and bundles, and helper scripts for database setup and
deployment.

## Quick start (local)

1. Ensure you have PostgreSQL running and create a database:

   ```bash
   createdb garment_erp
   ```

2. Export environment variables for the database and optionally the secret key:

   ```bash
   export DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/garment_erp
   export SECRET_KEY=supersecret
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Initialise the database and seed sample data (workers, bundles and
   operations).  This will also generate QR codes in `static/qrcodes/`.

   ```bash
   python db_setup.py
   ```

5. Run the development server:

   ```bash
   python app.py
   ```

6. Visit [http://localhost:5000](http://localhost:5000) in your browser to see
   the dashboard and manage data.

## Deployment (Render/Heroku)

The repository includes a `Procfile` for Heroku/Render and a `render.yaml`
configuration.  Set the `DATABASE_URL` environment variable to point at
your hosted PostgreSQL database and, optionally, `SECRET_KEY`.  The service
will install dependencies via `pip`, then launch using gunicorn.

## ESP32 Scanner

The `ESP32/esp32_scan_post.ino` sketch demonstrates how to scan two QR
codes (worker and bundle) and post them to the `/scan` endpoint of the
server.  Configure the WiFi credentials and server URL at the top of the
sketch.  The example uses `Serial2` for a serial QR scanner and a TFT
display for user prompts.

## Project structure

- `app.py` – Flask application with routes for dashboard, users, bundles,
  task assignment, scan ingestion, SSE events and report download.
- `models.py` – SQLAlchemy models representing users, bundles, operations,
  scans and tasks.
- `config.py` – Configuration class with sensible defaults for PostgreSQL.
- `db_setup.py` – One‐off script to create tables and seed initial data.
- `qr_utils.py` – Helpers for generating QR codes for workers and bundles.
- `templates/` – Jinja templates for rendering the UI.
- `static/css/style.css` – Dark‐mode stylesheet mirroring the mockups.
- `static/js/app.js` – Placeholder for custom JavaScript.
- `ESP32/esp32_scan_post.ino` – Example Arduino sketch for scanning and posting.
- `requirements.txt` – Python dependencies, pinned to specific versions.
- `Procfile` – Process definition for deploying to Heroku/Render.
- `render.yaml` – Render service configuration.