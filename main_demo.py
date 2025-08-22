from fastapi import FastAPI, Body, Request, Depends, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from db_sqlite import init_db, get_db_connection, add_demo_data
from sync import sync_paid_students
from send_companion_invitations import send_companion_invitations
import os
from datetime import datetime
import csv
from io import StringIO
from fastapi.encoders import jsonable_encoder
import traceback
import json
from typing import Optional

app = FastAPI(title="Sistema ACTO DE GRADO UAM - Control de Acceso Acompañantes")

templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), 'templates'))

# Simple admin auth
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "9090")

def verify_admin(request: Request, x_admin_token: Optional[str] = Header(default=None)):
    token = x_admin_token or request.query_params.get("token")
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Admin token not configured")
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

@app.on_event("startup")
async def startup_db_client():
    try:
        init_db()
        add_demo_data()
        print("Demo database ready!")
    except Exception as e:
        print("[ERROR] init_db() failed during startup!")
        print("Exception:", e)
        traceback.print_exc()
        raise

@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    return templates.TemplateResponse("admin.html", {"request": request})

@app.get("/")
def health_check():
    return {
        "status": "ok", 
        "mode": "demo", 
        "title": "🎓 Sistema ACTO DE GRADO - Universidad Arturo Michelena",
        "description": "Control de Acceso para Acompañantes",
        "admin_url": "/admin?token=9090",
        "scanner_url": "/scan"
    }

@app.post("/admin/sync")
def admin_sync(from_date: str = Body('2025-07-27', embed=True), _: None = Depends(verify_admin)):
    """
    Trigger sync of paid students from remote MySQL to local SQLite.
    """
    result = sync_paid_students(from_date=from_date)
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

@app.get("/admin/students")
def admin_get_students(_: None = Depends(verify_admin)):
    """Get all students"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM students")
    students = [dict(row) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return {"students": students}

@app.get("/admin/companions")
def admin_get_companions(_: None = Depends(verify_admin)):
    """Get all companions"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT c.*, s.first_name, s.last_name 
        FROM companions c 
        JOIN students s ON c.student_id = s.id
    """)
    companions = [dict(row) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return {"companions": companions}

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
        WHERE c.qr_data = ?
    """, (qr_data,))
    
    companion_row = cur.fetchone()
    
    if companion_row:
        # Handle companion verification
        companion = dict(companion_row)
        
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
            now = datetime.now().isoformat()
            cur.execute("UPDATE companions SET access_status=?, checked_in_at=? WHERE id=?", 
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
    
    conn.close()
    return JSONResponse({"status": "error", "message": "Código QR Inválido"}, status_code=404)

@app.get("/admin/export")
def admin_export_students(request: Request, _: None = Depends(verify_admin)):
    """Export students to CSV"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM students")
    students = [dict(row) for row in cur.fetchall()]
    cur.close()
    conn.close()
    
    output = StringIO()
    if students:
        fieldnames = students[0].keys()
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(students)
    
    response = StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=students.csv"}
    )
    return response

@app.get("/admin/export-companions")
def admin_export_companions(request: Request, _: None = Depends(verify_admin)):
    """Export companions to CSV"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT c.*, s.first_name as student_first_name, s.last_name as student_last_name, s.cedula as student_cedula
        FROM companions c 
        JOIN students s ON c.student_id = s.id
    """)
    companions = [dict(row) for row in cur.fetchall()]
    cur.close()
    conn.close()
    
    output = StringIO()
    if companions:
        fieldnames = companions[0].keys()
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(companions)
    
    response = StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=companions.csv"}
    )
    return response

@app.post("/admin/reset-test-checkin")
def admin_reset_test_checkin(_: None = Depends(verify_admin)):
    """Reset check-in status for test students"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE companions SET access_status='pending', checked_in_at=NULL WHERE student_id IN (SELECT id FROM students WHERE email LIKE '%test%')")
    updated = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    return {"success": True, "updated": updated}

@app.post("/admin/reset-checkin")
def admin_reset_checkin(_: None = Depends(verify_admin)):
    """Reset check-in status for ALL students"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE companions SET access_status='pending', checked_in_at=NULL")
    updated = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    return {"success": True, "updated": updated}

@app.post("/admin/reset-checkin-cedula")
async def admin_reset_checkin_cedula(request: Request, _: None = Depends(verify_admin)):
    """Reset check-in status for specific cedula"""
    data = await request.json()
    cedula = data.get("cedula")
    if not cedula:
        return JSONResponse({"success": False, "error": "Cedula required"}, status_code=400)
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE companions SET access_status='pending', checked_in_at=NULL WHERE student_id IN (SELECT id FROM students WHERE cedula=?)", (cedula,))
    updated = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    
    if updated == 0:
        return JSONResponse({"success": False, "error": f"No companions found for cedula {cedula}"}, status_code=404)
    
    return {"success": True, "updated": updated}

@app.get("/admin/auto-sync-config")
def admin_get_auto_sync_config(_: None = Depends(verify_admin)):
    """Get auto-sync configuration"""
    return {"enabled": False, "message": "Auto-sync not implemented in demo mode"}

@app.post("/admin/auto-sync-config")
async def admin_set_auto_sync_config(request: Request, _: None = Depends(verify_admin)):
    """Set auto-sync configuration"""
    data = await request.json()
    enabled = data.get("enabled", False)
    return {"success": True, "enabled": enabled, "message": "Auto-sync configuration updated (demo mode)"}

@app.post("/admin/resend-companion-invitations")
async def admin_resend_companion_invitations(request: Request, _: None = Depends(verify_admin)):
    """Resend companion invitations for specific cedula"""
    data = await request.json()
    cedula = data.get("cedula")
    if not cedula:
        return JSONResponse({"success": False, "error": "Cedula required"}, status_code=400)
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT email, first_name, last_name FROM students WHERE cedula=?", (cedula,))
    student = cur.fetchone()
    cur.close()
    conn.close()
    
    if not student:
        return JSONResponse({"success": False, "error": f"Student with cedula {cedula} not found"}, status_code=404)
    
    return {"success": True, "email": student[0], "message": f"Invitations would be resent to {student[1]} {student[2]} (demo mode)"}

@app.post("/admin/delete-db")
def admin_delete_db(_: None = Depends(verify_admin)):
    """Delete database (demo mode - not implemented)"""
    return {"success": False, "error": "Database deletion not allowed in demo mode"}

@app.get("/scan", response_class=HTMLResponse)
def scan_page(request: Request):
    return templates.TemplateResponse("scanner.html", {"request": request})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)