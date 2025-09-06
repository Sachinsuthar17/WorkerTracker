import sqlite3

# Connect to database (creates if not exists)
conn = sqlite3.connect("attendance.db")
c = conn.cursor()

# ================= USERS TABLE =================
c.execute('''
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    token_id TEXT UNIQUE NOT NULL, -- QR code for login
    department TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
''')

# ================= OPERATIONS TABLE =================
c.execute('''
CREATE TABLE IF NOT EXISTS operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    operation_name TEXT NOT NULL,
    barcode_value TEXT UNIQUE NOT NULL, -- unique barcode assigned
    assigned_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
)
''')

# ================= SCANS TABLE =================
c.execute('''
CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    operation_id INTEGER NOT NULL,
    scan_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (operation_id) REFERENCES operations(id)
)
''')

print("✅ Database setup complete: users, operations, scans")

conn.commit()
conn.close()
