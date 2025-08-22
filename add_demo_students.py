from db_sqlite import get_db_connection
from generate_companion_qr_sqlite import create_companion_qr_codes_sqlite

def add_demo_students():
    """Add demo students with companion QR codes"""
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Sample students for demo
    demo_students = [
        {
            'student_remote_id': 'UAM_001',
            'first_name': 'María Elena',
            'last_name': 'González Rodríguez',
            'career': 'Ingeniería de Sistemas',
            'email': 'maria.gonzalez@email.com',
            'cedula': '12345678'
        },
        {
            'student_remote_id': 'UAM_002', 
            'first_name': 'Carlos Alberto',
            'last_name': 'Martínez López',
            'career': 'Administración de Empresas',
            'email': 'carlos.martinez@email.com',
            'cedula': '87654321'
        },
        {
            'student_remote_id': 'UAM_003',
            'first_name': 'Ana Sofía',
            'last_name': 'Hernández Morales',
            'career': 'Derecho',
            'email': 'ana.hernandez@email.com', 
            'cedula': '11223344'
        }
    ]
    
    print("Adding demo students...")
    
    for student in demo_students:
        # Insert student
        cur.execute("""
            INSERT OR REPLACE INTO students 
            (student_remote_id, first_name, last_name, career, email, cedula, payment_confirmed)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            student['student_remote_id'],
            student['first_name'],
            student['last_name'], 
            student['career'],
            student['email'],
            student['cedula'],
            True
        ))
        
        # Get student ID
        cur.execute("SELECT id FROM students WHERE student_remote_id = ?", (student['student_remote_id'],))
        student_id = cur.fetchone()['id']
        
        # Generate companion QR codes
        try:
            create_companion_qr_codes_sqlite(student_id)
            print(f"✅ Added {student['first_name']} {student['last_name']} with companion QR codes")
        except Exception as e:
            print(f"❌ Error generating QR codes for {student['first_name']}: {e}")
    
    conn.commit()
    cur.close()
    conn.close()
    
    print(f"\n🎓 Demo students added successfully!")
    print("Now you can:")
    print("1. Go to /admin?token=9090") 
    print("2. Click 'Enviar Invitaciones PDF a Acompañantes'")
    print("3. Test the scanner at /scan")

if __name__ == "__main__":
    add_demo_students()