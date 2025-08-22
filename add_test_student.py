import uuid
from datetime import datetime
from db import get_db_connection
import time
import sys
import random

# Generate a unique qr_data and a fake QR image (base64 string)
def add_test_student():
    conn = get_db_connection()
    student_remote_id = f'TEST_{uuid.uuid4().hex[:8]}'
    first_name = 'Javier'
    last_name = 'HigaGon'
    career = 'Testing'
    email = 'javierhiga@uam.edu.ve'
    payment_confirmed = True  # Use boolean for PostgreSQL compatibility
    access_status = 'pending'
    cedula = str(random.randint(10_000_000, 99_999_999))
    # Insert with QR fields as None (NULL)
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO students (
            student_remote_id, first_name, last_name, career, email, payment_confirmed, qr_data, qr_generated_at, qr_image_b64, access_status, cedula
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ''', (
        student_remote_id, first_name, last_name, career, email, payment_confirmed, None, None, None, access_status, cedula
    ))
    conn.commit()
    cur.close()
    conn.close()
    print(f"Test student added with email {email}, student_remote_id {student_remote_id}, cedula {cedula} (no QR assigned)")

def delete_test_students():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM students WHERE student_remote_id LIKE 'TEST_%'")
    conn.commit()
    cur.close()
    conn.close()
    print("All test students deleted.")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "delete":
        delete_test_students()
    else:
        add_test_student()
