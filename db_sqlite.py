import os
import sqlite3
from dotenv import load_dotenv

load_dotenv()

DB_PATH = "graduation_demo.db"

STUDENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER REFERENCES students(id) ON DELETE CASCADE,
    companion_number INTEGER NOT NULL CHECK (companion_number IN (1, 2)),
    qr_data TEXT UNIQUE NOT NULL,
    qr_generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    access_status TEXT NOT NULL DEFAULT 'pending',
    checked_in_at TIMESTAMP,
    pdf_sent_at TIMESTAMP,
    UNIQUE(student_id, companion_number)
);
"""

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # This makes rows behave like dictionaries
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
        print("SQLite database initialized successfully")
    except Exception as e:
        print("[ERROR] Error initializing SQLite DB:", e)
        import traceback; traceback.print_exc()
        raise

# For compatibility with existing code
RealDictCursor = None

# Add some demo data
def add_demo_data():
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Check if demo data already exists
    cur.execute("SELECT COUNT(*) as count FROM students")
    count = cur.fetchone()['count']
    
    if count == 0:
        # Insert demo student
        cur.execute("""
            INSERT INTO students (student_remote_id, first_name, last_name, career, email, cedula, payment_confirmed)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, ('DEMO_001', 'María Elena', 'González Rodríguez', 'Ingeniería', 'maria.gonzalez@email.com', '12345678', True))
        
        conn.commit()
        print("Demo data added successfully")
    
    cur.close()
    conn.close()