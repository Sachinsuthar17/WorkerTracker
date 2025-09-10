# db_setup.py
import os
from sqlalchemy import create_engine, text

def init_db(db_url: str | None = None):
    """
    Create all tables and defaults if they do not exist in PostgreSQL.
    """
    url = db_url or os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("❌ DATABASE_URL is not set. Please add it in Render dashboard.")

    # Render sometimes gives `postgres://`, need `postgresql://`
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

    engine = create_engine(url, future=True)

    schema = [
        # ---------------- Settings ---------------- #
        """
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            base_rate_per_min REAL DEFAULT 0.50,
            efficiency_target INTEGER DEFAULT 100,
            quality_target INTEGER DEFAULT 95
        )
        """,
        # ---------------- Users ---------------- #
        """
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            worker_code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            department TEXT,
            skill TEXT,
            hourly_rate REAL DEFAULT 0,
            qr_code TEXT UNIQUE
        )
        """,
        # ---------------- Bundles ---------------- #
        """
        CREATE TABLE IF NOT EXISTS bundles (
            id SERIAL PRIMARY KEY,
            bundle_code TEXT UNIQUE NOT NULL,
            style TEXT,
            color TEXT,
            size_range TEXT,
            quantity INTEGER DEFAULT 0,
            current_op TEXT,
            qr_code TEXT UNIQUE
        )
        """,
        # ---------------- Operations ---------------- #
        """
        CREATE TABLE IF NOT EXISTS operations (
            id SERIAL PRIMARY KEY,
            op_no TEXT UNIQUE NOT NULL,
            description TEXT,
            section TEXT,
            std_min REAL DEFAULT 0
        )
        """,
        # ---------------- Scans ---------------- #
        """
        CREATE TABLE IF NOT EXISTS scans (
            id SERIAL PRIMARY KEY,
            worker_id INTEGER NOT NULL REFERENCES users(id),
            bundle_id INTEGER NOT NULL REFERENCES bundles(id),
            operation_id INTEGER NOT NULL REFERENCES operations(id),
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        # ---------------- Tasks ---------------- #
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id SERIAL PRIMARY KEY,
            worker_id INTEGER NOT NULL REFERENCES users(id),
            description TEXT NOT NULL,
            status TEXT DEFAULT 'OPEN',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        # ---------------- Defaults ---------------- #
        """
        INSERT INTO settings (id, base_rate_per_min, efficiency_target, quality_target)
        VALUES (1, 0.50, 100, 95)
        ON CONFLICT (id) DO NOTHING
        """,
        # ---------------- Indexes ---------------- #
        "CREATE INDEX IF NOT EXISTS idx_scans_time ON scans(timestamp)",
        "CREATE INDEX IF NOT EXISTS idx_scans_worker ON scans(worker_id)",
        "CREATE INDEX IF NOT EXISTS idx_scans_bundle ON scans(bundle_id)",
        "CREATE INDEX IF NOT EXISTS idx_scans_operation ON scans(operation_id)"
    ]

    with engine.begin() as conn:
        for stmt in schema:
            conn.execute(text(stmt))

    print("✅ Database schema ensured at", url)


if __name__ == "__main__":
    init_db()
