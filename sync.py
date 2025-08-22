import os
import csv
import logging
import mysql.connector
from mysql.connector import Error as MySQLError
from dotenv import load_dotenv
try:
    from db import get_db_connection
except ImportError:
    from db_sqlite import get_db_connection
from datetime import datetime
import pytz
from generate_qr import generate_qr_for_student
from generate_companion_qr import create_companion_qr_codes
import traceback
import time

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
    'use_pure': True,  # Use pure Python implementation
    'ssl_disabled': True
}

def load_allowed_cedulas() -> set:
    """Load cedulas permitted to be recorded from graduacion.csv.
    Expects a header row with at least a column named 'cedula'.
    Returns a set of trimmed string cedulas.
    Raises an Exception if the file is missing or unreadable.
    """
    csv_path = os.path.join(os.path.dirname(__file__), 'graduacion.csv')
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Required file not found: {csv_path}")
    allowed: set[str] = set()
    # Use utf-8-sig to gracefully handle BOM in header; accept case/whitespace variations
    with open(csv_path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        raw_fieldnames = reader.fieldnames or []
        normalized = [ (name or '').strip().lower() for name in raw_fieldnames ]
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
    return allowed

def get_mysql_connection_with_retry(max_retries=3, delay=1):
    """Get MySQL connection with retry logic"""
    for attempt in range(max_retries):
        try:
            logger.info(f"Attempting MySQL connection (attempt {attempt + 1}/{max_retries})")
            conn = mysql.connector.connect(**MYSQL_CONFIG)
            logger.info("MySQL connection successful")
            return conn
        except MySQLError as e:
            logger.warning(f"MySQL connection attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {delay} seconds...")
                time.sleep(delay)
                delay *= 2  # Exponential backoff
            else:
                raise
        except Exception as e:
            logger.error(f"Unexpected error during MySQL connection: {e}")
            raise

def sync_paid_students(from_date: str = '2025-01-01'):
    """
    Sync students with most recent confirmed payment after from_date.
    Upserts by student_remote_id.
    Returns inserted and updated student lists as well as counts.
    """
    print(f"[SYNC DEBUG] Running sync_paid_students with from_date: {from_date}")
    # Load cedula whitelist from CSV (mandatory)
    try:
        allowed_cedulas = load_allowed_cedulas()
    except Exception as e:
        logger.error(f"Failed to load graduacion.csv: {e}")
        return {"success": False, "error": f"Failed to load graduacion.csv: {e}"}

    try:
        print(f"[SYNC DEBUG] Connecting to MySQL: {MYSQL_CONFIG['host']}:{MYSQL_CONFIG['port']}")
        remote_conn = get_mysql_connection_with_retry()
        remote_cursor = remote_conn.cursor(dictionary=True)
        print(f"[SYNC DEBUG] MySQL connection successful")
        # Find all students with a qualifying payment after from_date
        # Add LIMIT to prevent extremely large result sets
        query = """
            SELECT e.IDEstudiante, e.Nombres, e.Apellidos, e.EMail,
                   csd.CodPrograma AS career,
                   e.Cedula,
                   cm.FechaMovimiento, ABS(cm.Monto) AS MontoUnitario, cm.CodCuentaOperacion, cm.DT
            FROM Estudiantes e
            JOIN CuentaMovimiento cm ON cm.IDCuentaVirtual = e.IDEstudiante
            LEFT JOIN CuentaSolicitudDetalle csd ON csd.IDCuentaVirtual = e.IDEstudiante AND csd.CodCuentaOperacion = cm.CodCuentaOperacion
            WHERE cm.CodCuentaOperacion LIKE 'ACT%'
              AND cm.Confirmado = 1
              AND cm.DT >= %s
            ORDER BY e.IDEstudiante, cm.DT DESC
            LIMIT 5000
        """
        logger.info(f"Executing main sync query with from_date: {from_date}")
        remote_cursor.execute(query, (from_date,))
        rows = remote_cursor.fetchall()
        print(f"[SYNC DEBUG] Rows fetched: {len(rows)}")
        for row in rows:
            # Convert FechaMovimiento to Venezuela time if it's naive or in another timezone
            fecha_movimiento = row['FechaMovimiento']
            if isinstance(fecha_movimiento, datetime):
                if fecha_movimiento.tzinfo is None:
                    fecha_movimiento = VE_TZ.localize(fecha_movimiento)
                row['FechaMovimiento'] = fecha_movimiento.astimezone(VE_TZ)
            
            # Handle DT field - preserve as is since it's already in Venezuela time (GMT-4)
            # Just ensure it's properly recognized as Venezuela timezone
            dt_value = row.get('DT')
            if dt_value and isinstance(dt_value, datetime):
                if dt_value.tzinfo is None:
                    # If DT has no timezone info, assume it's already in Venezuela time
                    row['DT'] = VE_TZ.localize(dt_value)
                
            print(f"[SYNC DEBUG] Row: {row}")
        remote_cursor.close()
        remote_conn.close()
    except Exception as e:
        error_msg = f"Failed to fetch from remote MySQL: {e}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        return {"success": False, "error": error_msg}

    # Get most recent payment per student
    students = {}
    for row in rows:
        key = row['IDEstudiante']
        if key not in students:
            students[key] = row  # first row is most recent due to ORDER BY

    inserted, updated, skipped = [], [], []
    try:
        local_conn = get_db_connection()
        cur = local_conn.cursor()
        # Reuse a single remote MySQL connection/cursor for secondary email lookups
        try:
            remote_conn2 = get_mysql_connection_with_retry()
            remote_cursor2 = remote_conn2.cursor(dictionary=True)
        except Exception as e:
            remote_conn2 = None
            remote_cursor2 = None
            logger.warning(f"Could not establish secondary MySQL connection for Perfil lookups: {e}")

        total_students = len(students.values())
        logger.info(f"Processing {total_students} unique students")
        
        for idx, student in enumerate(students.values(), 1):
            if idx % 50 == 0 or idx == 1:
                logger.info(f"Processing student {idx}/{total_students}")
            
            # Enforce cedula whitelist from graduacion.csv BEFORE any DB writes
            student_cedula = (student.get('Cedula') or '')
            student_cedula = str(student_cedula).strip()
            if not student_cedula or student_cedula not in allowed_cedulas:
                skipped.append({
                    'student_remote_id': student['IDEstudiante'],
                    'first_name': student['Nombres'],
                    'last_name': student['Apellidos'],
                    'career': student.get('career'),
                    'email': student.get('EMail'),
                    'secondary_email': None
                })
                continue
            # Fetch secondary email from Perfil table in MySQL
            secondary_email = None
            try:
                if remote_cursor2 is not None and idx <= 10:  # Only log for first 10 students
                    logger.debug(f"Fetching secondary email for student {student['IDEstudiante']}")
                if remote_cursor2 is not None:
                    student_id = student['IDEstudiante']
                    logger.debug(f"Fetching Perfil for IDUsuario={student_id}")
                    # Fetch full row to tolerate schema variations
                    remote_cursor2.execute("SELECT * FROM Perfil WHERE IDUsuario=%s", (student_id,))
                    perfil_row = remote_cursor2.fetchone()
                    logger.debug(f"Perfil query result for {student_id}: {perfil_row}")
                    if perfil_row:
                        # Try common email field names first
                        candidate = None
                        preferred_keys = ['Correo', 'Email', 'CorreoAlterno', 'CorreoPersonal']
                        for key in preferred_keys:
                            if key in perfil_row and perfil_row.get(key):
                                candidate = perfil_row.get(key)
                                break
                        # As a fallback, detect any column containing 'correo' or 'email'
                        if not candidate:
                            for k, v in perfil_row.items():
                                if isinstance(k, str) and ('correo' in k.lower() or 'email' in k.lower()):
                                    if v:
                                        candidate = v
                                        break
                        if candidate:
                            secondary_email = str(candidate).strip() or None
                    else:
                        logger.warning(f"No Perfil row found for student {student_id}")
            except Exception as e:
                logger.warning(f"Could not fetch secondary email for student {student['IDEstudiante']}: {e}")

            # Cedula-based fallback: some students have multiple expedientes (IDEstudiante)
            # and Perfil may be linked to another ID. If we haven't found a secondary email yet,
            # try all Estudiantes with the same Cedula and look up Perfil for each.
            if secondary_email is None and remote_cursor2 is not None and student_cedula:
                try:
                    remote_cursor2.execute(
                        "SELECT IDEstudiante FROM Estudiantes WHERE Cedula=%s ORDER BY IDEstudiante DESC",
                        (student_cedula,)
                    )
                    id_rows = remote_cursor2.fetchall() or []
                    for id_row in id_rows:
                        # Extract IDEstudiante from row dict (handle different casings just in case)
                        other_id = (
                            id_row.get('IDEstudiante')
                            or id_row.get('IDESTUDIANTE')
                            or id_row.get('idestudiante')
                        )
                        if other_id is None:
                            # Fallback: take first value if keys are unexpected
                            if isinstance(id_row, dict) and len(id_row.values()) > 0:
                                other_id = list(id_row.values())[0]
                        if other_id is None:
                            continue
                        try:
                            remote_cursor2.execute("SELECT * FROM Perfil WHERE IDUsuario=%s", (other_id,))
                            perfil_row2 = remote_cursor2.fetchone()
                            if not perfil_row2:
                                continue
                            candidate2 = None
                            preferred_keys2 = ['Correo', 'Email', 'CorreoAlterno', 'CorreoPersonal']
                            for key in preferred_keys2:
                                if key in perfil_row2 and perfil_row2.get(key):
                                    candidate2 = perfil_row2.get(key)
                                    break
                            if not candidate2:
                                for k2, v2 in perfil_row2.items():
                                    if isinstance(k2, str) and ('correo' in k2.lower() or 'email' in k2.lower()):
                                        if v2:
                                            candidate2 = v2
                                            break
                            if candidate2:
                                secondary_email = str(candidate2).strip() or None
                                if secondary_email:
                                    logger.debug(
                                        f"Secondary email found via cedula fallback using IDUsuario={other_id}"
                                    )
                                    break
                        except Exception as inner_e:
                            logger.warning(
                                f"Perfil lookup failed for alternate IDUsuario={other_id} (cedula {student_cedula}): {inner_e}"
                            )
                except Exception as e:
                    logger.warning(
                        f"Cedula-based fallback failed for cedula {student_cedula}: {e}"
                    )
            # Avoid duplicating primary as secondary
            primary_email = (student.get('EMail') or '').strip()
            if secondary_email and primary_email and secondary_email.lower() == primary_email.lower():
                secondary_email = None
            # Skip students with missing email
            if not student.get('EMail'):
                logger.warning(f"Skipping student {student['IDEstudiante']} due to missing email.")
                skipped.append({
                    'student_remote_id': student['IDEstudiante'],
                    'first_name': student['Nombres'],
                    'last_name': student['Apellidos'],
                    'career': student.get('career'),
                    'email': student.get('EMail'),
                    'secondary_email': secondary_email
                })
                continue
            # Check if student exists
            cur.execute(
                "SELECT id, qr_data, qr_image_b64 FROM students WHERE student_remote_id = %s",
                (str(student['IDEstudiante']),)
            )
            row = cur.fetchone()
            exists = row is not None

            # Upsert student
            cur.execute(
                """
                INSERT INTO students (student_remote_id, first_name, last_name, career, email, payment_confirmed, cedula, secondary_email)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(student_remote_id) DO UPDATE SET
                    first_name=excluded.first_name,
                    last_name=excluded.last_name,
                    career=excluded.career,
                    email=excluded.email,
                    payment_confirmed=excluded.payment_confirmed,
                    cedula=excluded.cedula,
                    secondary_email=COALESCE(excluded.secondary_email, students.secondary_email)
                """,
                (
                    str(student['IDEstudiante']),
                    student['Nombres'],
                    student['Apellidos'],
                    student.get('career'),
                    student['EMail'],
                    True,
                    student.get('Cedula'),
                    secondary_email
                )
            )

            # Track students for QR generation after commit
            if not exists:
                inserted.append({
                    'student_remote_id': student['IDEstudiante'],
                    'first_name': student['Nombres'],
                    'last_name': student['Apellidos'],
                    'career': student.get('career'),
                    'email': student.get('EMail'),
                    'secondary_email': secondary_email
                })
            else:
                updated.append({
                    'student_remote_id': student['IDEstudiante'],
                    'first_name': student['Nombres'],
                    'last_name': student['Apellidos'],
                    'career': student.get('career'),
                    'email': student['EMail'],
                    'secondary_email': secondary_email
                })
        local_conn.commit()
        cur.close()
        local_conn.close()
        
        # Close reused remote resources if they were opened
        try:
            if remote_cursor2 is not None:
                remote_cursor2.close()
            if remote_conn2 is not None:
                remote_conn2.close()
        except Exception:
            pass
        
        # Skip QR code generation during sync to prevent database locks
        logger.info(f"Sync processing completed. Final counts - Inserted: {len(inserted)}, Updated: {len(updated)}, Skipped: {len(skipped)}")
        print(f"[SYNC DEBUG] Skipping QR code generation during sync to prevent database locks. QR codes will be generated when needed.")
    except Exception as e:
        logger.error(f"Failed to upsert into local PostgreSQL: {e}")
        logger.error(traceback.format_exc())
        return {"success": False, "error": traceback.format_exc()}

    logger.info(f"Sync complete. Inserted: {len(inserted)}, Updated: {len(updated)}, Skipped: {len(skipped)}")
    return {
        "success": True,
        "inserted_count": len(inserted),
        "updated_count": len(updated),
        "skipped_count": len(skipped),
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped
    }
