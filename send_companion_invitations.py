import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.application import MIMEApplication
from db import get_db_connection, RealDictCursor
from generate_companion_qr import create_companion_qr_codes, get_companion_qr_codes
from generate_invitation_pdf import generate_companion_pdfs
from datetime import datetime
import pytz
import urllib.request
import json

# Use the Cloudinary PNG as the cached logo image
try:
    with urllib.request.urlopen('https://res.cloudinary.com/demc0oskw/image/upload/v1746210685/uam_logo_fjqv6p.png') as response:
        CACHED_LOGO_IMAGE_BYTES = response.read()
except Exception as e:
    CACHED_LOGO_IMAGE_BYTES = None
    print(f"Warning: Could not download logo image: {e}")

def _read_email_config():
    """Read optional email config set from Admin UI"""
    try:
        config_path = os.path.join(os.path.dirname(__file__), 'email_config.json')
        with open(config_path, 'r') as f:
            return json.load(f)
    except Exception:
        return {"dry_run_emails": False, "preview_dir": os.path.join(os.path.dirname(__file__), 'previews')}

def send_companion_invitations():
    """Send PDF invitations to students for their companions"""
    
    # Dry-run mode: when enabled, generate PDFs to disk without sending emails or updating DB
    email_cfg = _read_email_config()
    DRY_RUN = email_cfg.get('dry_run_emails', os.environ.get('DRY_RUN_EMAILS', '0') == '1')
    PREVIEW_DIR = email_cfg.get('preview_dir', os.environ.get('EMAIL_PREVIEW_DIR', os.path.join(os.path.dirname(__file__), 'previews')))

    # Load email credentials from environment variables
    SENDER_EMAIL = os.environ.get('SENDER_EMAIL')
    SENDER_PASSWORD = os.environ.get('SENDER_PASSWORD')
    SMTP_HOST = os.environ.get('SMTP_HOST')
    SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))

    # If not dry-run, validate SMTP config
    if not DRY_RUN:
        if not all([SENDER_EMAIL, SENDER_PASSWORD, SMTP_HOST, SMTP_PORT]):
            return {'success': False, 'error': 'Missing email environment variable(s).'}

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Get students who need companion invitations sent
    cur.execute("""
        SELECT s.id, s.email, s.secondary_email, s.first_name, s.last_name, s.career
        FROM students s
        WHERE s.email IS NOT NULL 
        AND s.payment_confirmed = TRUE
        AND NOT EXISTS (
            SELECT 1 FROM companions c 
            WHERE c.student_id = s.id 
            AND c.pdf_sent_at IS NOT NULL
        )
    """)
    students = cur.fetchall()
    sent = []
    failed = []

    # DRY RUN path: determine if Spaces is configured
    SPACES_ENDPOINT = os.environ.get('SPACES_ENDPOINT')
    SPACES_REGION = os.environ.get('SPACES_REGION')
    SPACES_BUCKET = os.environ.get('SPACES_BUCKET')
    SPACES_KEY = os.environ.get('SPACES_KEY')
    SPACES_SECRET = os.environ.get('SPACES_SECRET')

    s3_client = None
    use_spaces = False
    if DRY_RUN and all([SPACES_ENDPOINT, SPACES_REGION, SPACES_BUCKET, SPACES_KEY, SPACES_SECRET]):
        try:
            import boto3  # Lazy import so app can start even if boto3 missing
            s3_client = boto3.client(
                's3',
                endpoint_url=SPACES_ENDPOINT,
                region_name=SPACES_REGION,
                aws_access_key_id=SPACES_KEY,
                aws_secret_access_key=SPACES_SECRET,
            )
            use_spaces = True
        except Exception as e:
            return {'success': False, 'error': f'Failed to initialize Spaces client: {e}'}

    # In local dry-run without Spaces, ensure preview directory exists
    if DRY_RUN and not use_spaces:
        try:
            os.makedirs(PREVIEW_DIR, exist_ok=True)
        except Exception as e:
            return {'success': False, 'error': f'Failed to create preview directory: {e}'}
        server = None
    else:
        try:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
        except Exception as e:
            return {'success': False, 'error': f'SMTP connection/login failed: {e}'}

    for student in students:
        student_full_name = f"{student['first_name']} {student['last_name']}"
        
        try:
            # Get or create companion QR codes
            qr_codes = get_companion_qr_codes(student['id'])
            if not qr_codes:
                qr_codes = create_companion_qr_codes(student['id'])
            
            # Generate or fetch PDF invitations
            pdf_bytes_list = None
            # If not DRY_RUN but Spaces configured, try to fetch previously generated PDFs from Spaces first
            if not DRY_RUN and all([SPACES_ENDPOINT, SPACES_REGION, SPACES_BUCKET, SPACES_KEY, SPACES_SECRET]):
                try:
                    import boto3  # Lazy import
                    s3_fetch = boto3.client(
                        's3', endpoint_url=SPACES_ENDPOINT, region_name=SPACES_REGION,
                        aws_access_key_id=SPACES_KEY, aws_secret_access_key=SPACES_SECRET
                    )
                    prefix = PREVIEW_DIR.strip('/') if PREVIEW_DIR else 'previews'
                    safe_first = str(student['first_name']).replace(' ', '_')
                    safe_last = str(student['last_name']).replace(' ', '_')
                    keys = [
                        f"{prefix}/Invitacion_Acompanante_1_{safe_first}_{safe_last}.pdf",
                        f"{prefix}/Invitacion_Acompanante_2_{safe_first}_{safe_last}.pdf",
                    ]
                    fetched = []
                    for key in keys:
                        obj = s3_fetch.get_object(Bucket=SPACES_BUCKET, Key=key)
                        fetched.append(obj['Body'].read())
                    if len(fetched) == 2:
                        pdf_bytes_list = fetched
                except Exception:
                    pdf_bytes_list = None
            if pdf_bytes_list is None:
                # Fallback: build PDFs now
                pdf_bytes_list = generate_companion_pdfs(student['id'], student_full_name, qr_codes)
            
            # Build email (or preview metadata)
            msg = MIMEMultipart('related')
            msg['Subject'] = 'Invitaciones para Acompañantes - Acto de Grado'
            msg['From'] = SENDER_EMAIL if SENDER_EMAIL else 'no-reply@example.com'
            recipients = [student['email']]
            if student.get('secondary_email'):
                recipients.append(student['secondary_email'])
            msg['To'] = ', '.join(recipients)

            # HTML content for email body
            html = f"""
            <!DOCTYPE html>
            <html>
            <head>
              <meta charset="UTF-8">
              <title>Invitaciones para Acompañantes - Acto de Grado</title>
            </head>
            <body style="background: #f7f7f7; font-family: Arial, sans-serif; margin:0; padding:0;">
              <table width="100%" cellpadding="0" cellspacing="0" style="background: #fff; padding: 0; margin-bottom: 24px;">
                <tr>
                  <td align="center" style="padding: 0;">
                    <div style="background: linear-gradient(90deg, #002060 0%, #009A44 100%); padding: 24px 0 12px 0; border-radius: 0 0 30px 30px;">
                      <img src="cid:uamlogo" alt="Universidad Arturo Michelena" width="140" style="display:block; margin:auto; background:#fff; border-radius: 12px; box-shadow:0 2px 8px rgba(0,0,0,0.08); padding: 6px;">
                    </div>
                  </td>
                </tr>
              </table>
              <table width="100%" cellpadding="0" cellspacing="0" style="background: #fff; max-width: 600px; margin: 30px auto; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.05); border-top: 4px solid #002060;">
                <tr>
                  <td style="padding: 32px;">
                    <h2 style="color: #002060; margin-top: 0;">Estimado(a) {student['first_name']} {student['last_name']}, ¡Felicitaciones por tan importante logro!</h2>
                    <p>Nos complace informarte que adjuntamos las <b>invitaciones oficiales para tus acompañantes</b> al Acto de Grado de la Universidad Arturo Michelena.</p>
                    <div style="background: #f0f8ff; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #009A44;">
                        <h3 style="color: #002060; margin-top: 0;">📎 Archivos Adjuntos:</h3>
                        <ul style="margin: 10px 0;">
                            <li><b>Invitación Acompañante #1.pdf</b> - Para tu primer acompañante</li>
                            <li><b>Invitación Acompañante #2.pdf</b> - Para tu segundo acompañante</li>
                        </ul>
                    </div>
                    <p><b>Instrucciones importantes:</b></p>
                    <ul style="text-align: left; margin: 20px 0;">
                        <li>Cada PDF contiene un código QR único e intransferible</li>
                        <li>Envía cada invitación al acompañante correspondiente</li>
                        <li>Los acompañantes deben presentar su invitación en formato digital o impreso</li>
                        <li>Es recomendable llegar con 30 minutos de anticipación</li>
                        <li>El código de vestimenta es formal</li>
                    </ul>
                    <hr style="border: none; border-top: 1px solid #eee; margin: 32px 0;">
                    <p style="font-size: 13px; color: #888;">Este correo fue enviado automáticamente por la Universidad Arturo Michelena.<br>
                    Si tienes dudas, contacta a <a href="mailto:info@uam.edu.ve" style="color: #002060;">info@uam.edu.ve</a>.</p>
                  </td>
                </tr>
              </table>
              <table width="100%" cellpadding="0" cellspacing="0" style="background: #002060; padding: 10px 0; margin-top: 20px;">
                <tr>
                  <td align="center">
                    <span style="color: #fff; font-size: 13px;">&copy; Universidad Arturo Michelena - Todos los derechos reservados</span>
                  </td>
                </tr>
              </table>
            </body>
            </html>
            """
            
            msg.attach(MIMEText(html, 'html'))

            # Attach or save PDF files
            if DRY_RUN:
                saved = []
                for i, pdf_bytes in enumerate(pdf_bytes_list, 1):
                    safe_first = str(student['first_name']).replace(' ', '_')
                    safe_last = str(student['last_name']).replace(' ', '_')
                    filename = f'Invitacion_Acompanante_{i}_{safe_first}_{safe_last}.pdf'
                    if use_spaces:
                        prefix = PREVIEW_DIR.strip('/') if PREVIEW_DIR else 'previews'
                        key = f"{prefix}/{filename}"
                        try:
                            s3_client.put_object(
                                Bucket=SPACES_BUCKET,
                                Key=key,
                                Body=pdf_bytes,
                                ContentType='application/pdf',
                                ACL='private'
                            )
                            saved.append({'space_key': key})
                        except Exception as e:
                            failed.append({'email': recipients, 'error': f'Spaces upload failed: {e}', 'id': student['id'], 'name': student_full_name})
                    else:
                        out_path = os.path.join(PREVIEW_DIR, filename)
                        with open(out_path, 'wb') as f:
                            f.write(pdf_bytes)
                        saved.append({'file_path': out_path})
                sent.append({'previews': saved, 'id': student['id'], 'name': student_full_name, 'recipients': recipients})
            else:
                for i, pdf_bytes in enumerate(pdf_bytes_list, 1):
                    pdf_attachment = MIMEApplication(pdf_bytes, _subtype='pdf')
                    pdf_attachment.add_header(
                        'Content-Disposition', 
                        'attachment', 
                        filename=f'Invitacion_Acompanante_{i}_{student["first_name"]}_{student["last_name"]}.pdf'
                    )
                    msg.attach(pdf_attachment)
                
                # Attach cached logo
                if CACHED_LOGO_IMAGE_BYTES:
                    logo_img = MIMEImage(CACHED_LOGO_IMAGE_BYTES, _subtype='png')
                    logo_img.add_header('Content-ID', '<uamlogo>')
                    logo_img.add_header('Content-Disposition', 'inline', filename='uamlogo.png')
                    msg.attach(logo_img)
                
                # Send email
                server.sendmail(SENDER_EMAIL, recipients, msg.as_string())
                
                # Mark as sent in database
                ve_tz = pytz.timezone('America/Caracas')
                now = datetime.now(ve_tz).replace(tzinfo=None)
                cur.execute("""
                    UPDATE companions 
                    SET pdf_sent_at = %s 
                    WHERE student_id = %s
                """, (now, student['id']))
                
                sent.append({'email': recipients, 'id': student['id'], 'name': student_full_name})
            
        except Exception as e:
            failed.append({'email': recipients if 'recipients' in locals() else [], 'error': str(e), 'id': student['id'], 'name': student_full_name})

    if not DRY_RUN:
        conn.commit()
    cur.close()
    conn.close()
    if server:
        server.quit()

    if DRY_RUN:
        return {
            'success': True,
            'dry_run': True,
            'preview_dir': PREVIEW_DIR,
            'previewed_count': len(sent),
            'failed_count': len(failed),
            'previewed': sent,
            'failed': failed
        }
    else:
        return {
            'success': True, 
            'sent_count': len(sent), 
            'failed_count': len(failed), 
            'sent': sent, 
            'failed': failed
        }

def send_companion_invitations_to_student(cedula):
    """Send companion invitations to a specific student by cedula"""
    
    email_cfg = _read_email_config()
    DRY_RUN = email_cfg.get('dry_run_emails', os.environ.get('DRY_RUN_EMAILS', '0') == '1')
    PREVIEW_DIR = email_cfg.get('preview_dir', os.environ.get('EMAIL_PREVIEW_DIR', os.path.join(os.path.dirname(__file__), 'previews')))

    SENDER_EMAIL = os.environ.get('SENDER_EMAIL')
    SENDER_PASSWORD = os.environ.get('SENDER_PASSWORD')
    SMTP_HOST = os.environ.get('SMTP_HOST')
    SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
    
    if not DRY_RUN:
        if not all([SENDER_EMAIL, SENDER_PASSWORD, SMTP_HOST, SMTP_PORT]):
            return {'success': False, 'error': 'Missing email environment variable(s).'}
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM students WHERE cedula=%s", (cedula,))
    student = cur.fetchone()
    
    if not student or not student.get('email'):
        cur.close()
        conn.close()
        return {'success': False, 'error': 'Student not found or missing email.'}
    
    student_full_name = f"{student['first_name']} {student['last_name']}"
    
    try:
        # Get or create companion QR codes
        qr_codes = get_companion_qr_codes(student['id'])
        if not qr_codes:
            qr_codes = create_companion_qr_codes(student['id'])
        
        # Generate or fetch PDF invitations
        pdf_bytes_list = None
        # If not DRY_RUN and Spaces configured, try to fetch existing PDFs from Spaces first
        if not DRY_RUN and all([
            os.environ.get('SPACES_ENDPOINT'), os.environ.get('SPACES_REGION'),
            os.environ.get('SPACES_BUCKET'), os.environ.get('SPACES_KEY'), os.environ.get('SPACES_SECRET')
        ]):
            try:
                import boto3  # Lazy import
                s3_fetch = boto3.client(
                    's3',
                    endpoint_url=os.environ.get('SPACES_ENDPOINT'),
                    region_name=os.environ.get('SPACES_REGION'),
                    aws_access_key_id=os.environ.get('SPACES_KEY'),
                    aws_secret_access_key=os.environ.get('SPACES_SECRET'),
                )
                prefix = PREVIEW_DIR.strip('/') if PREVIEW_DIR else 'previews'
                safe_first = str(student['first_name']).replace(' ', '_')
                safe_last = str(student['last_name']).replace(' ', '_')
                keys = [
                    f"{prefix}/Invitacion_Acompanante_1_{safe_first}_{safe_last}.pdf",
                    f"{prefix}/Invitacion_Acompanante_2_{safe_first}_{safe_last}.pdf",
                ]
                fetched = []
                for key in keys:
                    obj = s3_fetch.get_object(Bucket=os.environ.get('SPACES_BUCKET'), Key=key)
                    fetched.append(obj['Body'].read())
                if len(fetched) == 2:
                    pdf_bytes_list = fetched
            except Exception:
                pdf_bytes_list = None

        if pdf_bytes_list is None:
            pdf_bytes_list = generate_companion_pdfs(student['id'], student_full_name, qr_codes)
        
        # Setup SMTP or preview dir
        if DRY_RUN:
            os.makedirs(PREVIEW_DIR, exist_ok=True)
            server = None
        else:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
        
        # Create email (or preview) (similar to above)
        msg = MIMEMultipart('related')
        msg['Subject'] = 'Invitaciones para Acompañantes - Acto de Grado'
        msg['From'] = SENDER_EMAIL if SENDER_EMAIL else 'no-reply@example.com'
        recipients = [student['email']]
        if student.get('secondary_email'):
            recipients.append(student['secondary_email'])
        msg['To'] = ', '.join(recipients)
        
        # [HTML content similar to above function]
        html = f"""
        <html>
        <body style='background: #f7f7f7; font-family: Arial, sans-serif; margin:0; padding:0;'>
            <table width='100%' cellpadding='0' cellspacing='0' style='background: #fff; padding: 0; margin-bottom: 24px;'>
                <tr>
                    <td align='center' style='padding: 0;'>
                        <div style='background: linear-gradient(90deg, #002060 0%, #009A44 100%); padding: 24px 0 12px 0; border-radius: 0 0 30px 30px;'>
                            <img src='cid:uamlogo' alt='Universidad Arturo Michelena' width='140' style='display:block; margin:auto; background:#fff; border-radius: 12px; box-shadow:0 2px 8px rgba(0,0,0,0.08); padding: 6px;'>
                        </div>
                    </td>
                </tr>
            </table>
            <table width='100%' cellpadding='0' cellspacing='0' style='background: #fff; max-width: 600px; margin: 30px auto; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.05); border-top: 4px solid #002060;'>
                <tr>
                    <td style='padding: 32px;'>
                        <h2 style='color: #002060; margin-top: 0;'>Estimado(a) {student['first_name']} {student['last_name']}, ¡Felicitaciones por tan importante logro!</h2>
                        <p>Adjuntamos las invitaciones oficiales para tus acompañantes al Acto de Grado.</p>
                        <p>Cada PDF contiene un código QR único. Por favor, envía cada invitación al acompañante correspondiente.</p>
                        <hr style='border: none; border-top: 1px solid #eee; margin: 32px 0;'>
                        <p style='font-size: 13px; color: #888;'>Este correo fue enviado automáticamente por la Universidad Arturo Michelena.</p>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """
        
        msg.attach(MIMEText(html, 'html'))
        
        if DRY_RUN:
            # Spaces config detection
            SPACES_ENDPOINT = os.environ.get('SPACES_ENDPOINT')
            SPACES_REGION = os.environ.get('SPACES_REGION')
            SPACES_BUCKET = os.environ.get('SPACES_BUCKET')
            SPACES_KEY = os.environ.get('SPACES_KEY')
            SPACES_SECRET = os.environ.get('SPACES_SECRET')

            saved = []
            if all([SPACES_ENDPOINT, SPACES_REGION, SPACES_BUCKET, SPACES_KEY, SPACES_SECRET]):
                import boto3  # Lazy import
                s3_client = boto3.client(
                    's3',
                    endpoint_url=SPACES_ENDPOINT,
                    region_name=SPACES_REGION,
                    aws_access_key_id=SPACES_KEY,
                    aws_secret_access_key=SPACES_SECRET,
                )
                for i, pdf_bytes in enumerate(pdf_bytes_list, 1):
                    safe_first = str(student['first_name']).replace(' ', '_')
                    safe_last = str(student['last_name']).replace(' ', '_')
                    filename = f'Invitacion_Acompanante_{i}_{safe_first}_{safe_last}.pdf'
                    prefix = PREVIEW_DIR.strip('/') if PREVIEW_DIR else 'previews'
                    key = f"{prefix}/{filename}"
                    s3_client.put_object(
                        Bucket=SPACES_BUCKET,
                        Key=key,
                        Body=pdf_bytes,
                        ContentType='application/pdf',
                        ACL='private'
                    )
                    saved.append({'space_key': key})
            else:
                os.makedirs(PREVIEW_DIR, exist_ok=True)
                for i, pdf_bytes in enumerate(pdf_bytes_list, 1):
                    safe_first = str(student['first_name']).replace(' ', '_')
                    safe_last = str(student['last_name']).replace(' ', '_')
                    filename = f'Invitacion_Acompanante_{i}_{safe_first}_{safe_last}.pdf'
                    out_path = os.path.join(PREVIEW_DIR, filename)
                    with open(out_path, 'wb') as f:
                        f.write(pdf_bytes)
                    saved.append({'file_path': out_path})

            cur.close()
            conn.close()
            return {'success': True, 'dry_run': True, 'email': recipients, 'previews': saved, 'preview_dir': PREVIEW_DIR}
        else:
            # Attach PDFs
            for i, pdf_bytes in enumerate(pdf_bytes_list, 1):
                pdf_attachment = MIMEApplication(pdf_bytes, _subtype='pdf')
                pdf_attachment.add_header(
                    'Content-Disposition', 
                    'attachment', 
                    filename=f'Invitacion_Acompanante_{i}_{student["first_name"]}_{student["last_name"]}.pdf'
                )
                msg.attach(pdf_attachment)
            
            # Attach logo
            if CACHED_LOGO_IMAGE_BYTES:
                logo_img = MIMEImage(CACHED_LOGO_IMAGE_BYTES, _subtype='png')
                logo_img.add_header('Content-ID', '<uamlogo>')
                logo_img.add_header('Content-Disposition', 'inline', filename='uamlogo.png')
                msg.attach(logo_img)
            
            # Send
            server.sendmail(SENDER_EMAIL, recipients, msg.as_string())
            
            # Update database
            ve_tz = pytz.timezone('America/Caracas')
            now = datetime.now(ve_tz).replace(tzinfo=None)
            cur.execute("UPDATE companions SET pdf_sent_at = %s WHERE student_id = %s", (now, student['id']))
            conn.commit()
            
            cur.close()
            conn.close()
            server.quit()
            
            return {'success': True, 'email': recipients}
        
    except Exception as e:
        if 'server' in locals() and server:
            server.quit()
        return {'success': False, 'error': str(e)}