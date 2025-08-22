import uuid
import qrcode
import base64
import io
from datetime import datetime
import pytz
from db import get_db_connection
from PIL import Image, ImageDraw

def generate_missing_qrs():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, student_remote_id FROM students WHERE payment_confirmed=TRUE AND (qr_data IS NULL OR qr_image_b64 IS NULL)")
    students = cur.fetchall()
    generated = []
    for student in students:
        qr_data = str(uuid.uuid4())
        # Generate QR code image
        qr_img = qrcode.make(qr_data).convert("RGB")
        # Add blue-green frame
        border_size = 20
        frame_color_1 = (0, 32, 96)   # UAM Blue
        frame_color_2 = (0, 154, 68)  # UAM Green
        # Create gradient frame
        size = (qr_img.size[0] + border_size * 2, qr_img.size[1] + border_size * 2)
        frame = Image.new('RGB', size, frame_color_1)
        draw = ImageDraw.Draw(frame)
        for y in range(size[1]):
            ratio = y / size[1]
            r = int(frame_color_1[0] * (1 - ratio) + frame_color_2[0] * ratio)
            g = int(frame_color_1[1] * (1 - ratio) + frame_color_2[1] * ratio)
            b = int(frame_color_1[2] * (1 - ratio) + frame_color_2[2] * ratio)
            draw.line([(0, y), (size[0], y)], fill=(r, g, b))
        frame.paste(qr_img, (border_size, border_size))
        buf = io.BytesIO()
        frame.save(buf, format='PNG')
        qr_b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        # Use Venezuela time (GMT-4) instead of UTC
        ve_tz = pytz.timezone('America/Caracas')
        now = datetime.now(ve_tz)
        cur.execute("UPDATE students SET qr_data=%s, qr_generated_at=%s, qr_image_b64=%s WHERE id=%s", (qr_data, now, qr_b64, student['id']))
        generated.append({
            'student_remote_id': student['student_remote_id'],
            'qr_data': qr_data
        })
    conn.commit()
    cur.close()
    conn.close()
    return {'success': True, 'generated_count': len(generated), 'generated': generated}

def generate_qr_for_student(conn, student_id):
    import uuid, qrcode, base64, io
    from datetime import datetime
    cur = conn.cursor()
    cur.execute("SELECT qr_data, qr_image_b64 FROM students WHERE id=%s", (student_id,))
    row = cur.fetchone()
    if row:
        qr_data = row[0] if isinstance(row, tuple) else row['qr_data']
        qr_image_b64 = row[1] if isinstance(row, tuple) else row['qr_image_b64']
        if qr_data and qr_image_b64:
            cur.close()
            return  # Already has QR
    qr_data = str(uuid.uuid4())
    qr_img = qrcode.make(qr_data)
    buf = io.BytesIO()
    qr_img.save(buf, format='PNG')
    qr_b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
    # Use Venezuela time (GMT-4) instead of UTC
    ve_tz = pytz.timezone('America/Caracas')
    now = datetime.now(ve_tz)
    cur.execute("UPDATE students SET qr_data=%s, qr_generated_at=%s, qr_image_b64=%s WHERE id=%s",
                 (qr_data, now, qr_b64, student_id))
    cur.close()
