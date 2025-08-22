from fastapi import FastAPI, Body, Request, Depends, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from db import init_db, get_db_connection, RealDictCursor
from bulk_sync import sync_paid_students_bulk
from admin_view import router as admin_router
from send_companion_invitations import send_companion_invitations, send_companion_invitations_to_student
from job_manager import job_manager, start_sync_job, start_qr_generation_job, start_email_job, start_full_process_job
import os
from datetime import datetime
import csv
from io import StringIO
from fastapi.encoders import jsonable_encoder
import traceback
import json
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
import atexit
import pytz
from typing import Optional

app = FastAPI()

app.include_router(admin_router)

templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), 'templates'))

AUTO_SYNC_CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'auto_sync_config.json')

# Simple admin auth
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN")

def verify_admin(request: Request, x_admin_token: Optional[str] = Header(default=None)):
    token = x_admin_token or request.query_params.get("token")
    if not ADMIN_TOKEN:
        # If no token is set in environment, deny to avoid accidental exposure
        raise HTTPException(status_code=403, detail="Admin token not configured")
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

# Helper functions to read/write auto sync config

def read_auto_sync_config():
    try:
        with open(AUTO_SYNC_CONFIG_PATH, 'r') as f:
            return json.load(f)
    except Exception:
        return {"enabled": False, "last_run": None}

def write_auto_sync_config(config):
    with open(AUTO_SYNC_CONFIG_PATH, 'w') as f:
        json.dump(config, f)

VE_TZ = pytz.timezone('America/Caracas')

# APScheduler setup
scheduler = None

def auto_sync_job():
    config = read_auto_sync_config()
    if not config.get("enabled", False):
        return
    now = datetime.now(VE_TZ)
    # Always sync payments from the last 10 minutes, regardless of last_run
    from_date = (now - timedelta(minutes=10)).strftime('%Y-%m-%d %H:%M:%S')
    print(f"[AUTO SYNC] Syncing students with payments after {from_date} (America/Caracas time). Current server time: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    try:
        sync_paid_students_bulk(from_date=from_date)
        config["last_run"] = now.strftime('%Y-%m-%d %H:%M:%S')
        write_auto_sync_config(config)
    except Exception as e:
        print("[AUTO SYNC ERROR]", e)

@app.on_event("startup")
async def startup_db_client():
    try:
        init_db()
    except Exception as e:
        print("[ERROR] init_db() failed during startup!")
        print("Exception:", e)
        traceback.print_exc()  # Imprime el stack trace completo
        raise  # Vuelve a lanzar la excepción: la app no arranca si la BD falla
    # Set up auto-sync only if enabled
    global scheduler
    config = read_auto_sync_config()
    if config.get("enabled", False):
        scheduler = BackgroundScheduler(timezone=VE_TZ)
        scheduler.add_job(auto_sync_job, 'interval', minutes=1)
        scheduler.start()
        atexit.register(lambda: scheduler.shutdown())
        print("[AUTO SYNC] Scheduler started - auto sync enabled")
    else:
        print("[AUTO SYNC] Scheduler not started - auto sync disabled")

@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    return templates.TemplateResponse("admin.html", {"request": request})

@app.get("/")
def health_check():
    return {"status": "ok"}

# Background Job Management Endpoints

@app.post("/admin/jobs/sync")
async def admin_start_sync_job(from_date: str = Body('2025-01-01', embed=True), _: None = Depends(verify_admin)):
    """Start a background sync job"""
    try:
        job_id = await start_sync_job(from_date)
        return {"success": True, "job_id": job_id}
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

@app.post("/admin/jobs/generate-qrs")
async def admin_start_qr_job(_: None = Depends(verify_admin)):
    """Start a background QR generation job"""
    try:
        job_id = await start_qr_generation_job()
        return {"success": True, "job_id": job_id}
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

@app.post("/admin/jobs/send-emails")
async def admin_start_email_job(_: None = Depends(verify_admin)):
    """Start a background email sending job"""
    try:
        job_id = await start_email_job()
        return {"success": True, "job_id": job_id}
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

@app.post("/admin/jobs/full-process")
async def admin_start_full_process_job(from_date: str = Body('2025-01-01', embed=True), _: None = Depends(verify_admin)):
    """Start a full process job: sync + QR generation + email sending"""
    try:
        job_id = await start_full_process_job(from_date)
        return {"success": True, "job_id": job_id, "message": "Full process started in background"}
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

@app.get("/admin/jobs/{job_id}")
def admin_get_job_status(job_id: str, _: None = Depends(verify_admin)):
    """Get status of a background job"""
    status = job_manager.get_job_status(job_id)
    if status:
        return status
    else:
        return JSONResponse({"error": "Job not found"}, status_code=404)

@app.get("/admin/jobs")
def admin_list_jobs(_: None = Depends(verify_admin)):
    """List all background jobs"""
    return job_manager.list_jobs()

@app.delete("/admin/jobs/{job_id}")
def admin_cancel_job(job_id: str, _: None = Depends(verify_admin)):
    """Cancel a background job"""
    success = job_manager.cancel_job(job_id)
    if success:
        return {"success": True, "message": "Job cancelled"}
    else:
        return JSONResponse({"success": False, "error": "Job not found or cannot be cancelled"}, status_code=400)

# Legacy Endpoints (for backward compatibility)

@app.post("/admin/sync")
def admin_sync(from_date: str = Body('2025-07-27', embed=True), _: None = Depends(verify_admin)):
    """
    Trigger sync of paid students from remote MySQL to local PostgreSQL.
    Accepts a from_date parameter in the JSON body (YYYY-MM-DD).
    """
    result = sync_paid_students_bulk(from_date=from_date)
    return result

@app.post("/admin/send-companion-invitations")
def admin_send_companion_invitations(_: None = Depends(verify_admin)):
    """
    Send PDF invitations to students for their companions.
    """
    try:
        result = send_companion_invitations()
        if not isinstance(result, dict):
            return JSONResponse({"success": False, "error": "Unexpected result from send_companion_invitations"}, status_code=500)
        return JSONResponse(result)
    except Exception as e:
        print(f"Error in /admin/send-companion-invitations: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )

@app.post("/admin/resend-companion-invitations")
def admin_resend_companion_invitations(payload: dict, _: None = Depends(verify_admin)):
    cedula = payload.get("cedula")
    if not cedula:
        return {"success": False, "error": "Missing cedula"}
    try:
        result = send_companion_invitations_to_student(cedula)
        if result["success"]:
            return {"success": True, "email": result["email"]}
        else:
            return {"success": False, "error": result["error"]}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/resend-companion-invitations")
def public_resend_companion_invitations(payload: dict):
    """Public endpoint for resending companion invitations (no admin auth required)"""
    cedula = payload.get("cedula")
    if not cedula:
        return {"success": False, "error": "Missing cedula"}
    try:
        result = send_companion_invitations_to_student(cedula)
        if result["success"]:
            return {"success": True, "email": result["email"]}
        else:
            return {"success": False, "error": result["error"]}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/scan", response_class=HTMLResponse)
def scan_page(request: Request):
    return templates.TemplateResponse("scanner.html", {"request": request})

@app.post("/api/verify")
def api_verify(payload: dict):
    qr_data = payload.get("qr_data")
    if not qr_data:
        return JSONResponse({"status": "error", "message": "Missing qr_data"}, status_code=400)
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Check if it's a companion QR code
    cur.execute("""
        SELECT c.id, c.companion_number, c.access_status, c.checked_in_at,
               s.first_name, s.last_name, s.career
        FROM companions c 
        JOIN students s ON c.student_id = s.id 
        WHERE c.qr_data = %s
    """, (qr_data,))
    
    companion_row = cur.fetchone()
    
    if companion_row:
        # Handle companion verification
        companion = dict(companion_row)
        
        # Convert datetime to isoformat if present
        if companion.get("checked_in_at") and hasattr(companion["checked_in_at"], 'isoformat'):
            companion["checked_in_at"] = companion["checked_in_at"].isoformat()
        
        if companion["access_status"] == "checked_in":
            conn.close()
            return JSONResponse(jsonable_encoder({
                "status": "warning", 
                "message": f"Acompañante #{companion['companion_number']} ya registrado", 
                "companion": companion,
                "type": "companion"
            }), status_code=200)
        elif companion["access_status"] == "denied":
            conn.close()
            return JSONResponse(jsonable_encoder({
                "status": "error", 
                "message": "Acceso Denegado para Acompañante", 
                "companion": companion,
                "type": "companion"
            }), status_code=403)
        else:
            # Mark companion as checked in
            now = datetime.now(VE_TZ).replace(tzinfo=None)
            cur.execute("UPDATE companions SET access_status=%s, checked_in_at=%s WHERE id=%s", 
                       ("checked_in", now, companion["id"]))
            conn.commit()
            conn.close()
            companion["access_status"] = "checked_in"
            companion["checked_in_at"] = now
            return JSONResponse(jsonable_encoder({
                "status": "ok", 
                "companion": companion,
                "type": "companion",
                "message": f"Bienvenido Acompañante #{companion['companion_number']} de {companion['first_name']} {companion['last_name']}"
            }))
    
    else:
        # Check if it's a legacy student QR code (backward compatibility)
        cur.execute("SELECT id, first_name, last_name, career, access_status, checked_in_at FROM students WHERE qr_data=%s", (qr_data,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return JSONResponse({"status": "error", "message": "Código QR Inválido"}, status_code=404)
        
        student = dict(row)
        # Convert datetime to isoformat if present
        if student.get("checked_in_at") and hasattr(student["checked_in_at"], 'isoformat'):
            student["checked_in_at"] = student["checked_in_at"].isoformat()
        
        if student["access_status"] == "checked_in":
            conn.close()
            return JSONResponse(jsonable_encoder({
                "status": "warning", 
                "message": "Ya registrado (código de graduando)", 
                "student": student,
                "type": "student"
            }), status_code=200)
        elif student["access_status"] == "denied":
            conn.close()
            return JSONResponse(jsonable_encoder({
                "status": "error", 
                "message": "Acceso Denegado", 
                "student": student,
                "type": "student"
            }), status_code=403)
        else:
            # Mark as checked in using Venezuela local time (naive datetime)
            now = datetime.now(VE_TZ).replace(tzinfo=None)
            cur.execute("UPDATE students SET access_status=%s, checked_in_at=%s WHERE id=%s", ("checked_in", now, student["id"]))
            conn.commit()
            conn.close()
            student["access_status"] = "checked_in"
            student["checked_in_at"] = now
            return JSONResponse(jsonable_encoder({
                "status": "ok", 
                "student": student,
                "type": "student",
                "message": f"Bienvenido graduando {student['first_name']} {student['last_name']}"
            }))

@app.post("/admin/delete-db")
def admin_delete_db(_: None = Depends(verify_admin)):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        # Use TRUNCATE for faster deletion and to reset sequences
        cur.execute("TRUNCATE TABLE companions, students RESTART IDENTITY CASCADE;")
        conn.commit()
        conn.close()
        return {"success": True, "message": "Database cleared successfully"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/admin/reset-test-checkin")
def admin_reset_test_checkin(_: None = Depends(verify_admin)):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE students SET access_status='pending', checked_in_at=NULL WHERE student_remote_id LIKE 'TEST_%'")
        cur.execute("""
            UPDATE companions SET access_status='pending', checked_in_at=NULL 
            WHERE student_id IN (SELECT id FROM students WHERE student_remote_id LIKE 'TEST_%')
        """)
        conn.commit()
        cur.close()
        conn.close()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/admin/reset-checkin")
def admin_reset_checkin(_: None = Depends(verify_admin)):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE students SET access_status='pending', checked_in_at=NULL")
        student_rows = cur.rowcount
        cur.execute("UPDATE companions SET access_status='pending', checked_in_at=NULL")
        companion_rows = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        return {"success": True, "updated_students": student_rows, "updated_companions": companion_rows}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/admin/reset-checkin-cedula")
def admin_reset_checkin_cedula(payload: dict, _: None = Depends(verify_admin)):
    cedula = payload.get("cedula")
    if not cedula:
        return {"success": False, "error": "Missing cedula"}
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE students SET access_status='pending', checked_in_at=NULL WHERE cedula=%s", (cedula,))
        student_rows = cur.rowcount
        cur.execute("""
            UPDATE companions SET access_status='pending', checked_in_at=NULL 
            WHERE student_id = (SELECT id FROM students WHERE cedula=%s)
        """, (cedula,))
        companion_rows = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        if student_rows > 0:
            return {"success": True, "updated_students": student_rows, "updated_companions": companion_rows}
        else:
            return {"success": False, "error": "No student found with cedula %s" % cedula}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/admin/export")
def admin_export(_: None = Depends(verify_admin)):
    """
    Export all students and companions as a CSV file.
    """
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Export with companion information
    cur.execute("""
        SELECT s.*, 
               COALESCE(c1.access_status, 'no_companion') as companion_1_status,
               c1.checked_in_at as companion_1_checked_in,
               COALESCE(c2.access_status, 'no_companion') as companion_2_status,
               c2.checked_in_at as companion_2_checked_in
        FROM students s
        LEFT JOIN companions c1 ON s.id = c1.student_id AND c1.companion_number = 1
        LEFT JOIN companions c2 ON s.id = c2.student_id AND c2.companion_number = 2
        ORDER BY s.last_name, s.first_name
    """)
    rows = cur.fetchall()
    
    # Define custom headers for better readability
    header = [
        'id', 'student_remote_id', 'first_name', 'last_name', 'career', 'email', 'secondary_email',
        'cedula', 'payment_confirmed', 'qr_data', 'qr_generated_at', 'qr_sent_at', 
        'access_status', 'checked_in_at', 'qr_image_b64',
        'companion_1_status', 'companion_1_checked_in',
        'companion_2_status', 'companion_2_checked_in'
    ]
    conn.close()
    
    def generate():
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(header)
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)
        for row in rows:
            writer.writerow([row.get(h, '') if row.get(h) is not None else '' for h in header])
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)
    
    return StreamingResponse(generate(), media_type='text/csv', headers={
        'Content-Disposition': 'attachment; filename="students_and_companions_export.csv"'
    })

@app.get("/admin/export-companions")
def admin_export_companions(_: None = Depends(verify_admin)):
    """
    Export all companions with student information as a CSV file.
    """
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Export companions with student information
    cur.execute("""
        SELECT c.id, c.companion_number, c.qr_data, c.qr_generated_at, 
               c.access_status, c.checked_in_at, c.pdf_sent_at,
               s.student_remote_id, s.first_name, s.last_name, s.career, 
               s.email, s.cedula
        FROM companions c
        JOIN students s ON c.student_id = s.id
        ORDER BY s.last_name, s.first_name, c.companion_number
    """)
    rows = cur.fetchall()
    
    # Define headers for companions export
    header = [
        'id', 'companion_number', 'qr_data', 'qr_generated_at',
        'access_status', 'checked_in_at', 'pdf_sent_at',
        'student_remote_id', 'first_name', 'last_name', 
        'career', 'email', 'cedula'
    ]
    conn.close()
    
    def generate():
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(header)
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)
        for row in rows:
            writer.writerow([row.get(h, '') if row.get(h) is not None else '' for h in header])
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)
    
    return StreamingResponse(generate(), media_type='text/csv', headers={
        'Content-Disposition': 'attachment; filename="companions_export.csv"'
    })

@app.get("/admin/auto-sync-config")
def get_auto_sync_config(_: None = Depends(verify_admin)):
    config = read_auto_sync_config()
    return JSONResponse(config)

@app.post("/admin/auto-sync-config")
def set_auto_sync_config(payload: dict, _: None = Depends(verify_admin)):
    enabled = payload.get("enabled", False)
    config = read_auto_sync_config()
    config["enabled"] = bool(enabled)
    write_auto_sync_config(config)
    
    # Start or stop scheduler based on new setting
    global scheduler
    if enabled and scheduler is None:
        scheduler = BackgroundScheduler(timezone=VE_TZ)
        scheduler.add_job(auto_sync_job, 'interval', minutes=1)
        scheduler.start()
        atexit.register(lambda: scheduler.shutdown())
        print("[AUTO SYNC] Scheduler started")
    elif not enabled and scheduler is not None:
        scheduler.shutdown()
        scheduler = None
        print("[AUTO SYNC] Scheduler stopped")
    
    return JSONResponse(config)
