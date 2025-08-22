import uuid
from db_sqlite import get_db_connection
from datetime import datetime

def generate_unique_qr_data():
    """Generate a unique QR data string"""
    return f"companion_{uuid.uuid4().hex}"

def create_companion_qr_codes_sqlite(student_id):
    """
    Create QR codes for both companions of a student (SQLite version)
    
    Args:
        student_id: The ID of the graduate student
        
    Returns:
        tuple: (qr_data_1, qr_data_2) - QR codes for companion 1 and 2
    """
    conn = get_db_connection()
    cur = conn.cursor()
    
    now = datetime.now().isoformat()
    
    qr_codes = []
    
    try:
        for companion_number in [1, 2]:
            # Generate unique QR data
            qr_data = generate_unique_qr_data()
            
            # Insert or replace companion record
            cur.execute("""
                INSERT OR REPLACE INTO companions 
                (student_id, companion_number, qr_data, qr_generated_at, access_status)
                VALUES (?, ?, ?, ?, ?)
            """, (student_id, companion_number, qr_data, now, 'pending'))
            
            qr_codes.append(qr_data)
        
        conn.commit()
        return tuple(qr_codes)
        
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()
        conn.close()

def get_companion_qr_codes_sqlite(student_id):
    """
    Get existing QR codes for student's companions (SQLite version)
    
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
            WHERE student_id = ? 
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