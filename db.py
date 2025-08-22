import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.environ["LOCAL_PG_DB"]

STUDENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS students (
    id SERIAL PRIMARY KEY,
    student_remote_id TEXT UNIQUE NOT NULL,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    career TEXT,
    email TEXT NOT NULL,
    secondary_email TEXT,
    payment_confirmed BOOLEAN NOT NULL DEFAULT TRUE,
    qr_data TEXT UNIQUE,
    qr_generated_at TIMESTAMP,
    qr_sent_at TIMESTAMP,
    access_status TEXT NOT NULL DEFAULT 'pending',
    checked_in_at TIMESTAMP,
    qr_image_b64 TEXT,
    cedula TEXT
);
"""

COMPANIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS companions (
    id SERIAL PRIMARY KEY,
    student_id INTEGER REFERENCES students(id) ON DELETE CASCADE,
    companion_number INTEGER NOT NULL CHECK (companion_number IN (1, 2)),
    qr_data TEXT UNIQUE NOT NULL,
    qr_generated_at TIMESTAMP DEFAULT NOW(),
    access_status TEXT NOT NULL DEFAULT 'pending',
    checked_in_at TIMESTAMP,
    pdf_sent_at TIMESTAMP,
    UNIQUE(student_id, companion_number)
);
"""

# Migration: Add qr_image_b64 if not exists
def migrate_add_qr_image_b64():
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("ALTER TABLE students ADD COLUMN qr_image_b64 TEXT;")
        conn.commit()
    except Exception as e:
        if 'duplicate column name' not in str(e):
            raise
    cur.close()
    conn.close()

def migrate_add_secondary_email():
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("ALTER TABLE students ADD COLUMN IF NOT EXISTS secondary_email TEXT;")
        conn.commit()
    except Exception as e:
        if 'duplicate column name' not in str(e):
            raise
    cur.close()
    conn.close()

def get_db_connection():
    DB_CONFIG = {
        "host": os.environ["LOCAL_PG_HOST"],
        "port": os.environ.get("LOCAL_PG_PORT", 5432),
        "user": os.environ["LOCAL_PG_USER"],
        "password": os.environ["LOCAL_PG_PASSWORD"],
        "dbname": os.environ["LOCAL_PG_DB"],
        "cursor_factory": RealDictCursor
    }
    conn = psycopg2.connect(**DB_CONFIG)
    # Set the connection's timezone to America/Caracas (Venezuela, GMT-4)
    conn.cursor().execute("SET TIME ZONE 'America/Caracas';")
    conn.commit()
    return conn

def init_db():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(STUDENTS_SCHEMA)
        cur.execute(COMPANIONS_SCHEMA)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print("[ERROR] Error initializing DB in init_db():", e)
        import traceback; traceback.print_exc()
        raise
