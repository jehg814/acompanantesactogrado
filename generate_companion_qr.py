import uuid
from db import get_db_connection
from datetime import datetime
import pytz

def generate_unique_qr_data():
    """Generate a unique QR data string"""
    return f"companion_{uuid.uuid4().hex}"

def create_companion_qr_codes(student_id):
    """
    Create QR codes for both companions of a student
    
    Args:
        student_id: The ID of the graduate student
        
    Returns:
        tuple: (qr_data_1, qr_data_2) - QR codes for companion 1 and 2
    """
    conn = get_db_connection()
    cur = conn.cursor()
    
    ve_tz = pytz.timezone('America/Caracas')
    now = datetime.now(ve_tz).replace(tzinfo=None)
    
    qr_codes = []
    
    try:
        for companion_number in [1, 2]:
            # Generate unique QR data
            qr_data = generate_unique_qr_data()
            
            # Insert or update companion record
            cur.execute("""
                INSERT INTO companions (student_id, companion_number, qr_data, qr_generated_at, access_status)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (student_id, companion_number) 
                DO UPDATE SET 
                    qr_data = EXCLUDED.qr_data,
                    qr_generated_at = EXCLUDED.qr_generated_at,
                    access_status = 'pending'
                RETURNING qr_data
            """, (student_id, companion_number, qr_data, now, 'pending'))
            
            result = cur.fetchone()
            qr_codes.append(result['qr_data'])
        
        conn.commit()
        return tuple(qr_codes)
        
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()
        conn.close()

def get_companion_qr_codes(student_id):
    """
    Get existing QR codes for student's companions
    
    Args:
        student_id: The ID of the graduate student
        
    Returns:
        tuple: (qr_data_1, qr_data_2) or None if not found
    """
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            SELECT companion_number, qr_data 
            FROM companions 
            WHERE student_id = %s 
            ORDER BY companion_number
        """, (student_id,))
        
        results = cur.fetchall()
        
        if len(results) == 2:
            return (results[0]['qr_data'], results[1]['qr_data'])
        else:
            return None
            
    finally:
        cur.close()
        conn.close()

def regenerate_companion_qr_codes(student_id):
    """
    Regenerate QR codes for student's companions and reset their status
    
    Args:
        student_id: The ID of the graduate student
        
    Returns:
        tuple: (qr_data_1, qr_data_2) - New QR codes
    """
    conn = get_db_connection()
    cur = conn.cursor()
    
    ve_tz = pytz.timezone('America/Caracas')
    now = datetime.now(ve_tz).replace(tzinfo=None)
    
    try:
        # Delete existing companions to regenerate
        cur.execute("DELETE FROM companions WHERE student_id = %s", (student_id,))
        conn.commit()
        
        # Create new QR codes
        return create_companion_qr_codes(student_id)
        
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()
        conn.close()