import qrcode
import base64
import io
from db import get_db_connection

def update_test_student_qr():
    conn = get_db_connection()
    cur = conn.cursor()
    # Get the qr_data for the test student
    cur.execute("SELECT id, qr_data FROM students WHERE email=%s", ("javierhiga@gmail.com",))
    row = cur.fetchone()
    if not row:
        print("Test student not found.")
        return
    student_id = row[0]
    qr_data = row[1]
    # Generate QR code image
    qr_img = qrcode.make(qr_data)
    buf = io.BytesIO()
    qr_img.save(buf, format='PNG')
    qr_b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
    cur.execute("UPDATE students SET qr_image_b64=%s WHERE id=%s", (qr_b64, student_id))
    conn.commit()
    cur.close()
    conn.close()
    print(f"Updated test student QR image for id {student_id}")

if __name__ == "__main__":
    update_test_student_qr()
