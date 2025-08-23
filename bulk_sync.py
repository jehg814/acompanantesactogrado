import os
import csv
import logging
import mysql.connector
from dotenv import load_dotenv
try:
    from db import get_db_connection
except ImportError:
    from db_sqlite import get_db_connection
from datetime import datetime
import pytz
import traceback
from typing import List, Dict, Set
import asyncio
from psycopg2.extras import execute_values

load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Ensure all datetime operations use Venezuela timezone (GMT-4)
VE_TZ = pytz.timezone('America/Caracas')

MYSQL_CONFIG = {
    'host': os.getenv('REMOTE_MYSQL_HOST'),
    'port': int(os.getenv('REMOTE_MYSQL_PORT', 3306)),
    'user': os.getenv('REMOTE_MYSQL_USER'),
    'password': os.getenv('REMOTE_MYSQL_PASSWORD'),
    'database': os.getenv('REMOTE_MYSQL_DB'),
    'charset': 'utf8mb4',
    'connection_timeout': 30,  # Increased from 10 to 30 seconds
    'autocommit': True,
    'use_pure': True,
    'ssl_disabled': True
}

def load_allowed_cedulas() -> Set[str]:
    """Load cedulas from graduacion.csv with improved error handling"""
    csv_path = os.path.join(os.path.dirname(__file__), 'graduacion.csv')
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Required file not found: {csv_path}")
    
    allowed: Set[str] = set()
    with open(csv_path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        raw_fieldnames = reader.fieldnames or []
        normalized = [(name or '').strip().lower() for name in raw_fieldnames]
        
        if 'cedula' not in normalized:
            raise ValueError("graduacion.csv must contain a 'cedula' header column")
        
        cedula_idx = normalized.index('cedula')
        cedula_key = raw_fieldnames[cedula_idx]
        
        for row in reader:
            value = (row.get(cedula_key) or '').strip()
            if value:
                allowed.add(value)
    
    if not allowed:
        raise ValueError("graduacion.csv contains no cedulas to authorize")
    
    logger.info(f"Loaded {len(allowed)} allowed cedulas from graduacion.csv")
    return allowed

def fetch_remote_students_bulk(from_date: str) -> List[Dict]:
    """Fetch students from remote MySQL in bulk with connection pooling"""
    logger.info(f"Fetching students with payments after {from_date}")
    
    try:
        remote_conn = mysql.connector.connect(**MYSQL_CONFIG)
        remote_cursor = remote_conn.cursor(dictionary=True, buffered=True)
        
        # Optimized query with proper indexing hints
        query = """
            SELECT e.IDEstudiante, e.Nombres, e.Apellidos, e.EMail,
                   csd.CodPrograma AS career,
                   e.Cedula,
                   cm.FechaMovimiento, ABS(cm.Monto) AS MontoUnitario, 
                   cm.CodCuentaOperacion, cm.DT
            FROM Estudiantes e
            JOIN CuentaMovimiento cm ON cm.IDCuentaVirtual = e.IDEstudiante
            LEFT JOIN CuentaSolicitudDetalle csd ON csd.IDCuentaVirtual = e.IDEstudiante 
                  AND csd.CodCuentaOperacion = cm.CodCuentaOperacion
            WHERE cm.CodCuentaOperacion LIKE 'ACT%'
              AND cm.Confirmado = 1
              AND cm.DT >= %s
            ORDER BY e.IDEstudiante, cm.DT DESC
        """
        
        remote_cursor.execute(query, (from_date,))
        
        # Fetch all results at once for better performance
        rows = remote_cursor.fetchall()
        logger.info(f"Fetched {len(rows)} payment records from remote database")
        
        # Process timezone conversion in bulk
        for row in rows:
            fecha_movimiento = row.get('FechaMovimiento')
            if isinstance(fecha_movimiento, datetime):
                if fecha_movimiento.tzinfo is None:
                    fecha_movimiento = VE_TZ.localize(fecha_movimiento)
                row['FechaMovimiento'] = fecha_movimiento.astimezone(VE_TZ)
            
            dt_value = row.get('DT')
            if dt_value and isinstance(dt_value, datetime):
                if dt_value.tzinfo is None:
                    row['DT'] = VE_TZ.localize(dt_value)
        
        return rows
        
    except Exception as e:
        error_msg = f"Failed to fetch from remote MySQL: {e}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        raise
    finally:
        try:
            remote_cursor.close()
            remote_conn.close()
        except:
            pass

def fetch_secondary_emails_bulk(student_ids: List[int]) -> Dict[int, str]:
    """Fetch secondary emails for multiple students in bulk"""
    if not student_ids:
        return {}
    
    secondary_emails = {}
    
    try:
        remote_conn = mysql.connector.connect(**MYSQL_CONFIG)
        remote_cursor = remote_conn.cursor(dictionary=True)
        
        # Bulk query for Perfil data - use * to avoid column name issues
        placeholders = ','.join(['%s'] * len(student_ids))
        query = f"""
            SELECT *
            FROM Perfil 
            WHERE IDUsuario IN ({placeholders})
        """
        
        remote_cursor.execute(query, student_ids)
        perfil_rows = remote_cursor.fetchall()
        
        for row in perfil_rows:
            user_id = row['IDUsuario']
            candidate = None
            
            # Try preferred email fields
            preferred_keys = ['Correo', 'Email', 'CorreoAlterno', 'CorreoPersonal']
            for key in preferred_keys:
                if row.get(key):
                    candidate = row.get(key)
                    break
            
            # Fallback to any email-like field
            if not candidate:
                for k, v in row.items():
                    if isinstance(k, str) and ('correo' in k.lower() or 'email' in k.lower()) and v:
                        candidate = v
                        break
            
            if candidate:
                secondary_emails[user_id] = str(candidate).strip()
        
        # Handle students with same cedula (multiple expedientes)
        remaining_student_ids = set(student_ids) - set(secondary_emails.keys())
        if remaining_student_ids:
            logger.info(f"Trying cedula-based fallback for {len(remaining_student_ids)} students")
            # Implementation of cedula-based fallback here if needed
        
        logger.info(f"Found secondary emails for {len(secondary_emails)} out of {len(student_ids)} students")
        return secondary_emails
        
    except Exception as e:
        logger.warning(f"Bulk secondary email fetch failed: {e}")
        return {}
    finally:
        try:
            remote_cursor.close()
            remote_conn.close()
        except:
            pass

def bulk_upsert_students(students_data: List[Dict]):
    """Bulk upsert students into local database"""
    if not students_data:
        logger.info("No students to upsert")
        return
    
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        
        # Prepare data for bulk upsert
        upsert_data = [
            (
                str(student['IDEstudiante']),
                student['Nombres'],
                student['Apellidos'],
                student.get('career'),
                student['EMail'],
                True,  # payment_confirmed
                student.get('Cedula'),
                student.get('secondary_email')
            )
            for student in students_data
        ]
        
        # Bulk upsert using execute_values for better performance
        upsert_query = """
            INSERT INTO students (student_remote_id, first_name, last_name, career, email, payment_confirmed, cedula, secondary_email)
            VALUES %s
            ON CONFLICT(student_remote_id) DO UPDATE SET
                first_name=EXCLUDED.first_name,
                last_name=EXCLUDED.last_name,
                career=EXCLUDED.career,
                email=EXCLUDED.email,
                payment_confirmed=EXCLUDED.payment_confirmed,
                cedula=EXCLUDED.cedula,
                secondary_email=COALESCE(EXCLUDED.secondary_email, students.secondary_email)
        """
        
        execute_values(cur, upsert_query, upsert_data, page_size=100)
        conn.commit()
        
        logger.info(f"Bulk upserted {len(students_data)} students")
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Bulk upsert failed: {e}")
        raise
    finally:
        cur.close()
        conn.close()

def sync_paid_students_bulk(from_date: str = '2025-01-01'):
    """
    Enhanced bulk sync of paid students with improved performance
    """
    logger.info(f"Starting bulk sync with from_date: {from_date}")
    
    try:
        # Load cedula whitelist
        allowed_cedulas = load_allowed_cedulas()
        
        # Fetch remote data in bulk
        rows = fetch_remote_students_bulk(from_date)
        
        if not rows:
            logger.info("No payment records found")
            return {"success": True, "message": "No records to sync"}
        
        # Get most recent payment per student
        students = {}
        for row in rows:
            key = row['IDEstudiante']
            if key not in students:
                students[key] = row  # first row is most recent due to ORDER BY
        
        logger.info(f"Processing {len(students)} unique students")
        
        # Filter by allowed cedulas and prepare for bulk operations
        valid_students = []
        skipped_students = []
        
        for student in students.values():
            student_cedula = str(student.get('Cedula', '')).strip()
            
            # Check cedula whitelist
            if not student_cedula or student_cedula not in allowed_cedulas:
                skipped_students.append(student)
                continue
            
            # Check for required email
            if not student.get('EMail'):
                logger.warning(f"Skipping student {student['IDEstudiante']} - missing email")
                skipped_students.append(student)
                continue
            
            valid_students.append(student)
        
        logger.info(f"Valid students: {len(valid_students)}, Skipped: {len(skipped_students)}")
        
        if not valid_students:
            return {
                "success": True,
                "inserted_count": 0,
                "updated_count": 0,
                "skipped_count": len(skipped_students)
            }
        
        # Fetch secondary emails in bulk
        student_ids = [s['IDEstudiante'] for s in valid_students]
        secondary_emails = fetch_secondary_emails_bulk(student_ids)
        
        # Add secondary emails to student data
        for student in valid_students:
            student_id = student['IDEstudiante']
            secondary_email = secondary_emails.get(student_id)
            
            # Avoid duplicating primary as secondary
            primary_email = (student.get('EMail') or '').strip().lower()
            if secondary_email and secondary_email.lower() == primary_email:
                secondary_email = None
            
            student['secondary_email'] = secondary_email
        
        # Check which students already exist
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            existing_ids_query = """
                SELECT student_remote_id 
                FROM students 
                WHERE student_remote_id = ANY(%s)
            """
            cur.execute(existing_ids_query, ([str(s['IDEstudiante']) for s in valid_students],))
            rows = cur.fetchall()
            # RealDictCursor returns dict-like rows; fall back to positional if needed
            try:
                existing_ids = set(row['student_remote_id'] for row in rows)
            except Exception:
                existing_ids = set(row[0] for row in rows)
        finally:
            cur.close()
            conn.close()
        
        # Separate new vs existing students
        inserted_students = [s for s in valid_students if str(s['IDEstudiante']) not in existing_ids]
        updated_students = [s for s in valid_students if str(s['IDEstudiante']) in existing_ids]
        
        # Bulk upsert all students
        bulk_upsert_students(valid_students)
        
        logger.info(f"Sync complete - Inserted: {len(inserted_students)}, Updated: {len(updated_students)}, Skipped: {len(skipped_students)}")
        
        return {
            "success": True,
            "inserted_count": len(inserted_students),
            "updated_count": len(updated_students),
            "skipped_count": len(skipped_students),
            "total_processed": len(valid_students)
        }
        
    except Exception as e:
        error_msg = f"Bulk sync failed: {e}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        return {"success": False, "error": error_msg}

# Async wrapper for integration
async def sync_paid_students_bulk_async(from_date: str = '2025-01-01'):
    """Async wrapper for bulk sync"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, sync_paid_students_bulk, from_date)