import os
import socket
from dotenv import load_dotenv

try:
    import mysql.connector
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False

try:
    import pymysql
    PYMYSQL_AVAILABLE = True
except ImportError:
    PYMYSQL_AVAILABLE = False

load_dotenv()

def test_network_connection(host, port):
    """Test basic network connectivity"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception as e:
        print(f"Network test error: {e}")
        return False

def test_mysql_connection():
    """Test MySQL connection with debug info"""
    
    host = os.getenv('REMOTE_MYSQL_HOST')
    port = int(os.getenv('REMOTE_MYSQL_PORT', 3306))
    user = os.getenv('REMOTE_MYSQL_USER')
    password = os.getenv('REMOTE_MYSQL_PASSWORD')
    database = os.getenv('REMOTE_MYSQL_DB')
    
    print("=== Testing MySQL Connection ===")
    print(f"Host: {host}")
    print(f"Port: {port}")
    print(f"User: {user}")
    print(f"Database: {database}")
    print("Password: [HIDDEN]")
    print()
    
    # Test network connectivity first
    print("Testing network connectivity...")
    if test_network_connection(host, port):
        print("✅ Network connection successful")
    else:
        print("❌ Network connection failed - server unreachable or port blocked")
        return False
    
    print()
    
    if not MYSQL_AVAILABLE:
        print("❌ mysql-connector-python not available")
        return False
    
    try:
        print("Attempting MySQL connection...")
        
        # Simple connection config
        config = {
            'host': host,
            'port': port,
            'user': user,
            'password': password,
            'database': database,
            'connection_timeout': 10
        }
        
        conn = mysql.connector.connect(**config)
        print("✅ MySQL connection successful!")
        
        cursor = conn.cursor()
        cursor.execute("SELECT VERSION()")
        version = cursor.fetchone()
        print(f"MySQL Version: {version[0]}")
        
        # Test if Estudiantes table exists
        cursor.execute("SHOW TABLES LIKE 'Estudiantes'")
        result = cursor.fetchone()
        if result:
            print("✅ Estudiantes table found")
        else:
            print("❌ Estudiantes table not found")
        
        cursor.close()
        conn.close()
        print("✅ Connection test completed successfully")
        return True
        
    except Exception as e:
        print(f"❌ MySQL Connection Error: {e}")
        print(f"Error type: {type(e)}")
        return False

if __name__ == "__main__":
    test_mysql_connection()