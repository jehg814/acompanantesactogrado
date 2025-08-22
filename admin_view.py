from fastapi import APIRouter
from fastapi import Depends, Header, HTTPException, Request
from typing import Optional
import os
from db import get_db_connection

router = APIRouter()

ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN")

def verify_admin(request: Request, x_admin_token: Optional[str] = Header(default=None)):
    token = x_admin_token or request.query_params.get("token")
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Admin token not configured")
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

@router.get("/admin/students")
def list_students(_: None = Depends(verify_admin)):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, student_remote_id, first_name, last_name, career, email, payment_confirmed, qr_data, access_status, checked_in_at
        FROM students
        ORDER BY last_name, first_name
    """)
    students = [dict(row) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return {"students": students}
