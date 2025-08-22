# 🎓 Guía de Configuración - Sistema ACTO DE GRADO UAM

## 📋 Requisitos

### **1. Base de Datos PostgreSQL Local**
```bash
# Instalar PostgreSQL
brew install postgresql  # macOS
# o en Ubuntu: sudo apt install postgresql postgresql-contrib

# Iniciar servicio PostgreSQL
brew services start postgresql  # macOS
# o en Ubuntu: sudo systemctl start postgresql

# Crear base de datos
psql postgres
CREATE DATABASE acto_grado_uam;
CREATE USER tu_usuario WITH PASSWORD 'tu_password';
GRANT ALL PRIVILEGES ON DATABASE acto_grado_uam TO tu_usuario;
\q
```

### **2. Acceso a Base de Datos MySQL Remota**
Asegúrate de tener:
- ✅ Host/IP del servidor MySQL remoto
- ✅ Usuario y contraseña con permisos de lectura
- ✅ Nombre de la base de datos
- ✅ Puerto (por defecto 3306)

### **3. Configuración de Email**
Para Gmail, necesitas:
- ✅ Email de la cuenta
- ✅ **App Password** (no la contraseña normal)
- ✅ Habilitar "2-Step Verification" en Gmail
- ✅ Generar App Password en https://myaccount.google.com/apppasswords

## 🔧 Configuración

### **1. Instalar Dependencias**
```bash
pip install -r requirements.txt
```

### **2. Configurar Variables de Entorno**
Edita el archivo `.env`:

```env
# Token de administrador
ADMIN_TOKEN=tu_token_secreto_aqui

# Base de Datos PostgreSQL Local
LOCAL_PG_HOST=localhost
LOCAL_PG_PORT=5432
LOCAL_PG_USER=tu_usuario_postgresql
LOCAL_PG_PASSWORD=tu_password_postgresql  
LOCAL_PG_DB=acto_grado_uam

# Base de Datos MySQL Remota (para sincronización)
REMOTE_MYSQL_HOST=tu_servidor_mysql.com
REMOTE_MYSQL_PORT=3306
REMOTE_MYSQL_USER=tu_usuario_mysql
REMOTE_MYSQL_PASSWORD=tu_password_mysql
REMOTE_MYSQL_DB=tu_base_datos_mysql

# Configuración de Email
SENDER_EMAIL=tu_email@gmail.com
SENDER_PASSWORD=tu_app_password_gmail
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
```

### **3. Archivo graduacion.csv**
Crea el archivo `graduacion.csv` con las cédulas permitidas:

```csv
cedula
12345678
87654321
11223344
```

## 🚀 Ejecutar el Sistema

### **Opción A: Modo Producción (con PostgreSQL)**
```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

### **Opción B: Modo Demo (con SQLite)**
```bash
uvicorn main_demo:app --host 0.0.0.0 --port 8000
```

## 🔗 Acceso a las Interfaces

- **Panel Admin:** http://localhost:8000/admin?token=tu_token_secreto_aqui
- **Scanner QR:** http://localhost:8000/scan
- **API Info:** http://localhost:8000/

## 📝 Flujo de Trabajo

### **1. Sincronización de Estudiantes**
1. Ir al panel admin
2. Configurar fecha de sincronización
3. Hacer clic en "🔄 Sincronizar Ahora"
4. El sistema:
   - Consulta estudiantes con pagos confirmados desde MySQL remoto
   - Filtra por cédulas permitidas en `graduacion.csv`
   - Inserta/actualiza en PostgreSQL local
   - Genera códigos QR únicos para acompañantes

### **2. Envío de Invitaciones**
1. Hacer clic en "📧 Enviar Invitaciones PDF a Acompañantes"
2. El sistema envía 2 PDFs por graduando:
   - `Invitacion_Acompanante_1_[Nombre]_[Apellido].pdf`
   - `Invitacion_Acompanante_2_[Nombre]_[Apellido].pdf`

### **3. Control de Acceso**
1. Usar el scanner en `/scan`
2. Escanear códigos QR de las invitaciones
3. El sistema verifica y registra el acceso de los acompañantes

## 🔍 Solución de Problemas

### **Error de Conexión PostgreSQL**
```bash
# Verificar que PostgreSQL esté ejecutándose
ps aux | grep postgres

# Verificar conexión
psql -h localhost -U tu_usuario -d acto_grado_uam
```

### **Error de Conexión MySQL**
- Verificar credenciales en `.env`
- Confirmar que la IP del servidor permite conexiones externas
- Verificar firewall y puertos

### **Error de Email**
- Confirmar que uses App Password de Gmail
- Verificar que 2FA esté habilitado
- Probar credenciales manualmente

### **Problemas con QR**
- Los QR se generan automáticamente durante la sincronización
- Si faltan, usar "🔄 Reiniciar Check-in" para regenerar

## 📊 Endpoints de la API

- `POST /admin/sync` - Sincronizar estudiantes
- `POST /admin/send-companion-invitations` - Enviar invitaciones
- `POST /admin/resend-companion-invitations` - Reenviar por cédula
- `POST /api/verify` - Verificar código QR de acompañante
- `GET /admin/export` - Exportar datos CSV
- `POST /admin/reset-checkin` - Reiniciar check-ins

¡El sistema está listo para el ACTO DE GRADO! 🎓