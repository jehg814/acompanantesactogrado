from db import get_db_connection

def reset_students_checkin():
    confirm = input("Are you sure you want to reset check-in status for ALL students? Type YES to confirm: ")
    if confirm != "YES":
        print("Operation cancelled.")
        return
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE students SET access_status='pending', checked_in_at=NULL")
        rows = cur.rowcount
        conn.commit()
        print(f"Rows updated: {rows}")
    except Exception as e:
        print(f"Error updating students: {e}")
    finally:
        cur.close()
        conn.close()
    print("Reset check-in status and datetime for ALL students.")

if __name__ == "__main__":
    reset_students_checkin()
