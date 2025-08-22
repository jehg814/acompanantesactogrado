# Graduation Event Access Control System Plan

## 1. Goal

To create a secure and efficient system for verifying student access to a graduation event based on payment confirmation stored in a remote, read-only MySQL database (`cestudio_uam`). The system will use QR codes scanned by university staff via a web-based application.

## 2. Core Components & Technology Stack

*   **Remote Database:** `cestudio_uam` (MySQL, Read-Only Access) - Source of truth for student info and payment status.
*   **Local Database:** PostgreSQL (Recommended) - Stores synced student data, QR codes, email status, and check-in status. Managed by the backend.
    *   *Why PostgreSQL?* Better concurrency handling if multiple admins or scanners operate simultaneously.
    *   Libraries:
        *   `mysql-connector-python` (or appropriate connector for `cestudio_uam`)
        *   `psycopg2-binary` (for PostgreSQL)
        *   `qrcode[pil]` (For QR code generation)
        *   `smtplib`, `email` (For sending emails via SMTP) or SDKs for email services (SendGrid, Mailgun)
        *   `python-dotenv` (For managing credentials securely)
        *   `uuid` (For generating unique QR data)
*   **Admin Interface:** Web Application
    *   Frontend: HTML, CSS, JavaScript (Vanilla JS or a simple framework like Alpine.js/HTMX)
    *   Purpose: Trigger sync, QR generation, email sending; view basic stats.
*   **Backend API:** Python (Using the same Flask/FastAPI application as the Admin Backend)
    *   Purpose: Provide an endpoint for the Scanner App to verify QR codes against the Local Database in real-time.
*   **Scanner Application:** Progressive Web App (PWA)
    *   Frontend: HTML, CSS, JavaScript
    *   Libraries: QR Code scanning library (e.g., `html5-qrcode`)
    *   Purpose: Allow staff to scan QR codes using device cameras and get immediate access validation via the Backend API.

## 3. Local Database Schema (`local_event_db`)

**Table: `students`**

| Column Name         | Data Type                        | Constraints                      | Description                                        |
| :------------------ | :------------------------------- | :------------------------------- | :------------------------------------------------- |
| `id`                | SERIAL / INTEGER                 | PRIMARY KEY, AUTO_INCREMENT      | Local unique ID for the record.                    |
| `student_remote_id` | VARCHAR / TEXT                   | UNIQUE, NOT NULL                 | Student's unique ID from `cestudio_uam`.           |
| `first_name`        | VARCHAR / TEXT                   | NOT NULL                         | Student's first name.                              |
| `last_name`         | VARCHAR / TEXT                   | NOT NULL                         | Student's last name.                               |
| `career`            | VARCHAR / TEXT                   | NULL                             | Student's career/major.                            |
| `email`             | VARCHAR / TEXT                   | NOT NULL                         | Student's email address.                           |
| `payment_confirmed` | BOOLEAN                          | NOT NULL, DEFAULT TRUE           | Indicates if payment was confirmed during sync.    |
| `qr_data`           | UUID / VARCHAR(36)               | UNIQUE, NULL                     | Unique data embedded in the QR code (e.g., a UUID). |
| `qr_generated_at`   | TIMESTAMP WITH TIME ZONE / DATETIME | NULL                             | Timestamp when the QR code was generated.          |
| `qr_sent_at`        | TIMESTAMP WITH TIME ZONE / DATETIME | NULL                             | Timestamp when the QR code email was sent.         |
| `access_status`     | VARCHAR(20)                      | NOT NULL, DEFAULT 'pending'      | 'pending', 'checked_in', 'denied'                  |
| `checked_in_at`     | TIMESTAMP WITH TIME ZONE / DATETIME | NULL                             | Timestamp when the student was checked in.         |
| `last_synced_at`    | TIMESTAMP WITH TIME ZONE / DATETIME | NOT NULL                         | Timestamp when this record was last synced/verified. |

*(Note: Adjust data types like `VARCHAR`/`TEXT`, `DATETIME`/`TIMESTAMP` based on the chosen DB: PostgreSQL)*

## 4. Implementation Phases

### Phase 1: Setup & Admin Functionality (Python Backend & Admin Interface)

1.  **Environment Setup:**
    *   Install Python and required libraries (`pip install ...`).
    *   Set up the chosen Local Database (PostgreSQL).
    *   Create a `.env` file to securely store database credentials (Remote & Local) and email settings.
    *   Set up the Flask/FastAPI project structure.

2.  **Local Database Connection:**
    *   Implement Python functions to connect/disconnect from the Local Database.

3.  **Feature: Sync with `cestudio_uam`**
    *   **Backend (Python):**
        *   Create a function `sync_paid_students()`.
        *   Securely read `cestudio_uam` credentials.
        *   Connect to `cestudio_uam`.
        *   Execute a **read-only** SQL query to fetch students who have paid the specific concept (e.g., `SELECT student_id, first_name, last_name, career, email FROM ... WHERE payment_concept = 'GRADUATION_FEE' AND status = 'PAID'`). **Adapt this query precisely.**
        *   Connect to the Local Database.
        *   For each fetched student:
            *   Check if `student_remote_id` exists in the local `students` table.
            *   If not exists: Insert a new record (`payment_confirmed=True`, `access_status='pending'`, other fields NULL/default, set `last_synced_at`).
            *   If exists: Optionally update info (name, email, career), ensure `payment_confirmed=True`, update `last_synced_at`. (Consider logic for students who *were* paid but are no longer - mark `payment_confirmed=False` or `access_status='denied'`).
        *   Log sync results (added/updated counts, errors).
    *   **Admin Interface (HTML/JS):**
        *   Create a page with a "Sync Paid Students" button.
        *   Use JavaScript (`fetch` API) to call a backend endpoint (e.g., `/admin/sync`) that triggers the `sync_paid_students()` function.
        *   Display feedback (syncing..., completed, errors).

4.  **Feature: Generate QR Codes**
    *   **Backend (Python):**
        *   Create a function `generate_missing_qrs()`.
        *   Query the local `students` table for records where `payment_confirmed=True` AND `qr_data IS NULL`.
        *   For each student:
            *   Generate a unique `uuid.uuid4()` string. This will be the `qr_data`. **Do NOT put PII directly in the QR.**
            *   Update the student's record in the local DB with the generated `qr_data` and set `qr_generated_at`.
        *   Log generation results.
        *   *(Optional: Generate and save QR image files if needed for direct download/embedding, but on-the-fly generation for email is often sufficient).*
    *   **Admin Interface (HTML/JS):**
        *   Add a "Generate Missing QR Codes" button.
        *   Use JavaScript to call a backend endpoint (e.g., `/admin/generate-qrs`) that triggers `generate_missing_qrs()`.
        *   Display feedback.

5.  **Feature: Send QR Codes via Email**
    *   **Backend (Python):**
        *   Configure email settings (SMTP server, port, user, password/app password OR Email API keys) via `.env`.
        *   Create a function `send_unsent_qrs()`.
        *   Query the local `students` table for records where `payment_confirmed=True` AND `qr_data IS NOT NULL` AND `qr_sent_at IS NULL`.
        *   For each student:
            *   Generate the QR code image in memory using the `qrcode` library and the student's `qr_data`.
            *   Compose an HTML email (using `email.mime...` modules) including event details, instructions, and the embedded/attached QR code image.
            *   Use `smtplib` (or an email service SDK) to send the email to the student's `email`.
            *   **Crucially:** If sending is successful, update the student's record, setting `qr_sent_at` to the current timestamp.
            *   If sending fails, log the error and *do not* update `qr_sent_at` (allows retrying). Implement error handling and potentially rate limiting.
    *   **Admin Interface (HTML/JS):**
        *   Add a "Send Unsent QR Codes" button.
        *   Use JavaScript to call a backend endpoint (e.g., `/admin/send-qrs`) that triggers `send_unsent_qrs()`.
        *   Display feedback (emails sent, errors).

### Phase 2: Real-time Access Control (Backend API & Scanner PWA)

6.  **Backend API Endpoint (Python - Flask/FastAPI)**
    *   Create an API endpoint: `POST /api/verify`
    *   Requires HTTPS for security.
    *   Optionally protect with a simple API key that the Scanner App must send.
    *   **Logic:**
        *   Accepts JSON body: `{ "qr_data": "scanned_uuid_string" }`
        *   Validate the input `qr_data`.
        *   Query the local `students` table: `SELECT id, first_name, last_name, career, access_status FROM students WHERE qr_data = ?`
        *   **If student found:**
            *   Check `access_status`:
                *   If `'pending'`: Update status: `UPDATE students SET access_status = 'checked_in', checked_in_at = NOW() WHERE id = ?`. Return `200 OK` with `{ "status": "success", "message": "Access Granted", "student": { "firstName": "...", "lastName": "...", "career": "..." } }`.
                *   If `'checked_in'`: Return `409 Conflict` (or similar like `200 OK` with different status) with `{ "status": "warning", "message": "Already Checked In", "student": { ... } }`. **Prevents reuse.**
                *   If `'denied'` or other invalid state: Return `403 Forbidden` with `{ "status": "error", "message": "Access Denied", "student": { ... } }`.
        *   **If student NOT found:** Return `404 Not Found` with `{ "status": "error", "message": "Invalid QR Code" }`.
        *   Return responses as JSON.

7.  **Scanner Application (HTML/CSS/JavaScript - PWA)**
    *   Create the basic HTML structure (camera view placeholder, results display area).
    *   Style with CSS for clear visual feedback (large GREEN for success, RED for error/denied, YELLOW/ORANGE for warning/already checked in).
    *   **JavaScript Logic:**
        *   Use a library like `html5-qrcode` to access the camera (`getUserMedia`) and scan QR codes.
        *   On successful scan, extract the QR data string (the UUID).
        *   Make a `fetch` POST request to the `/api/verify` endpoint on the Backend API, sending the `{ "qr_data": scanned_uuid }` in the body and any required API key in headers.
        *   Handle the JSON response from the API:
            *   Parse the `status`, `message`, and `student` data.
            *   Display the student's Name, Last Name, Career (if available).
            *   Display the message ("Access Granted", "Already Checked In", etc.).
            *   Show the corresponding visual indicator (Green/Yellow/Red background/icon).
        *   Provide a button or automatic timeout to clear the results and prepare for the next scan.
        *   Implement basic error handling for network issues or API errors.
    *   Configure as a PWA (Manifest file, Service Worker) for easier "installation" on staff devices and potential offline caching of assets (though the API call requires connectivity).

## 5. Key Considerations

*   **Security:**
    *   Use HTTPS for Admin Interface, Backend API, and Scanner App.
    *   Securely store all credentials (`.env` file, environment variables). Do not commit secrets to Git.
    *   Protect the `/api/verify` endpoint (e.g., simple shared API key, IP Whitelisting if feasible).
    *   Validate and sanitize all inputs (especially `qr_data` from scanner).
*   **Error Handling:** Implement robust try-except blocks in Python backend tasks (DB connections, file I/O, email sending, API requests). Log errors clearly. Provide user-friendly error messages in frontends.
*   **Network Connectivity:** The Scanner App relies *heavily* on real-time connection to the Backend API for validation and reuse prevention. Ensure reliable Wi-Fi or cellular data at the event venue entrance.
*   **Scalability:** Ensure the Backend API server and Local Database can handle the peak load of scans at the start of the event. Test API response times.
*   **User Experience (Scanner App):** Must be FAST and VERY CLEAR. Large fonts, distinct colors, minimal clicks. Staff will be under pressure.
*   **Testing:**
    *   Unit tests for backend functions (Python).
    *   Integration tests for API endpoints.
    *   End-to-end testing: Sync -> Generate -> Email -> Scan (valid, invalid, duplicate). Use test email accounts. Test on various devices staff might use.
*   **Backup:** Regularly back up the Local Database.
*   **Deployment:** Plan how/where the Python backend/API and the web frontends will be hosted.

## 6. Next Steps

1.  Finalize choice of Local Database (PostgreSQL).
2.  Set up the development environment (Python, DB, Node.js if needed for frontend tooling).
3.  Begin implementation, starting with Phase 1 (Backend DB setup, Sync).
4.  Develop components iteratively, testing each part.
5.  Deploy and conduct thorough testing in a staging environment before the event.
6.  Train staff on using the Scanner App.