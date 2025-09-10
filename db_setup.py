import os
import sqlite3

# ---------------- Database Path ---------------- #
default_data_dir = '/opt/render/data'
try:
    os.makedirs(default_data_dir, exist_ok=True)
except Exception:
    default_data_dir = '/tmp'
    os.makedirs(default_data_dir, exist_ok=True)

default_db = os.path.join(default_data_dir, 'factory.db')
DB_PATH = os.getenv("DATABASE_URL", default_db)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Settings for earnings and targets
    c.execute('''CREATE TABLE IF NOT EXISTS settings (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        base_rate_per_min REAL DEFAULT 0.50,
        efficiency_target INTEGER DEFAULT 100,
        quality_target INTEGER DEFAULT 95
    )''')

    # Users (workers)
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        worker_code TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        department TEXT,
        skill TEXT,
        hourly_rate REAL DEFAULT 0,
        qr_code TEXT UNIQUE
    )''')

    # Bundles
    c.execute('''CREATE TABLE IF NOT EXISTS bundles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bundle_code TEXT UNIQUE NOT NULL,
        style TEXT,
        color TEXT,
        size_range TEXT,
        quantity INTEGER DEFAULT 0,
        current_op TEXT,
        qr_code TEXT UNIQUE
    )''')

    # Operations (OB)
    c.execute('''CREATE TABLE IF NOT EXISTS operations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        op_no TEXT UNIQUE NOT NULL,
        description TEXT,
        section TEXT,
        std_min REAL DEFAULT 0
    )''')

    # Scans
    c.execute('''CREATE TABLE IF NOT EXISTS scans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        worker_id INTEGER NOT NULL,
        bundle_id INTEGER NOT NULL,
        operation_id INTEGER NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(worker_id) REFERENCES users(id),
        FOREIGN KEY(bundle_id) REFERENCES bundles(id),
        FOREIGN KEY(operation_id) REFERENCES operations(id)
    )''')

    # Tasks
    c.execute('''CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        worker_id INTEGER NOT NULL,
        description TEXT NOT NULL,
        status TEXT DEFAULT 'OPEN',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(worker_id) REFERENCES users(id)
    )''')

    # Ensure there is exactly one settings row
    c.execute("""
        INSERT OR IGNORE INTO settings
        (id, base_rate_per_min, efficiency_target, quality_target)
        VALUES (1, 0.50, 100, 95)
    """)

    # Indexes
    c.execute('CREATE INDEX IF NOT EXISTS idx_scans_time ON scans(timestamp)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_scans_worker ON scans(worker_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_scans_bundle ON scans(bundle_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_scans_operation ON scans(operation_id)')

    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("✅ Database initialized at", DB_PATH)
