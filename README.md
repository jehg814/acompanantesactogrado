# Graduation Event Companion Access Control System

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Copy `.env.example` to `.env` and fill in credentials.
3. Run the app (for local development):
   ```bash
   uvicorn main:app --reload
   ```
   This command is for local development only. For production deployment (e.g., Azure App Service), use gunicorn as described below.

## Features
- Sync paid students from remote MySQL
- Generate PDF invitations for student companions (2 per graduate)
- Each PDF contains unique QR codes with UAM branding
- Email PDF invitations to graduates for their companions
- Admin web interface for companion management
- Real-time QR verification API for companion access control
- Scanner PWA (see `code_grad.md`)
- Cedula whitelist via `graduacion.csv` (only students whose cedula is listed are inserted/updated during sync)

## New Companion System
- **Each graduate can invite 2 companions**
- **PDF invitations** with professional UAM design (colors: #002060 blue, #009A44 green)
- **Unique QR codes** for each companion invitation
- **Access control** specifically designed for companions, not graduates
- **Database tracking** of companion check-ins and invitation status

## Deploy en Azure App Service

1. Asegúrate de tener los archivos `requirements.txt`, `runtime.txt` y `startup.sh` en la raíz del proyecto.
2. Sube el código a tu repositorio (GitHub, Bitbucket, etc).
3. En Azure Portal, crea un nuevo recurso Web App:
   - Elige el runtime Python 3.10
   - Selecciona tu repositorio o sube el código manualmente
4. En Configuración > General > Comando de inicio, coloca:
   ```bash
   bash startup.sh
   ```
   
   **O usa directamente como comando de inicio:**
   ```bash
   gunicorn -w 4 -k uvicorn.workers.UvicornWorker main:app --bind 0.0.0.0:8000
   ```
5. Configura tus variables de entorno en Azure (usa `.env.example` como referencia).
6. Guarda y reinicia la app. ¡Listo!

## Cedula whitelist (graduacion.csv)

During the sync process, the application enforces a whitelist of cedulas. Only students whose cedula appears in the `graduacion.csv` file will be inserted/updated into the local database. Others will be reported in the "Skipped" list.

- Location: place `graduacion.csv` in the project root (same folder as `main.py`).
- Required header: the file must contain a header row with a column named `cedula`.
  - Header matching is case-insensitive and whitespace-tolerant.
  - UTF-8 and UTF-8 with BOM are supported.
- Structure: one cedula per row (single column file is fine).

Example:

```csv
cedula
30118750
26917566
31464615
```

If the file is missing or malformed (no `cedula` header or empty list), the sync will fail with an error indicating the problem.

Additional sync conditions already enforced:
- Students without an email address are skipped.
- Upsert behavior by `student_remote_id` with QR generation for new or missing QR entries.
