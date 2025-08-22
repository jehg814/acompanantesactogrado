from db import get_db_connection

def reset_students_qr_sent():
    confirm = input("Are you sure you want to reset qr_sent_at for ALL students? Type YES to confirm: ")
    if confirm != "YES":
        print("Operation cancelled.")
        return
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE students SET qr_sent_at=NULL")
    conn.commit()
    cur.close()
    conn.close()
    print("Reset qr_sent_at for ALL students.")

if __name__ == "__main__":
    reset_students_qr_sent()
