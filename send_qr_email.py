import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from db import get_db_connection, RealDictCursor
from datetime import datetime
import pytz
import base64
import urllib.request

# Use the Cloudinary PNG as the cached logo image
try:
    with urllib.request.urlopen('https://res.cloudinary.com/demc0oskw/image/upload/v1746210685/uam_logo_fjqv6p.png') as response:
        CACHED_LOGO_IMAGE_BYTES = response.read()
except Exception as e:
    CACHED_LOGO_IMAGE_BYTES = None
    print(f"Warning: Could not download logo image: {e}")

def send_qr_emails():
    # Load email credentials from environment variables
    SENDER_EMAIL = os.environ.get('SENDER_EMAIL')
    SENDER_PASSWORD = os.environ.get('SENDER_PASSWORD')
    SMTP_HOST = os.environ.get('SMTP_HOST')
    SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))

    # Check for missing credentials
    if not all([SENDER_EMAIL, SENDER_PASSWORD, SMTP_HOST, SMTP_PORT]):
        return {'success': False, 'error': 'Missing email environment variable(s).'}

    conn = get_db_connection()
    # Explicitly create cursor with RealDictCursor to ensure dictionary access
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT id, email, secondary_email, first_name, last_name, qr_image_b64 FROM students
        WHERE qr_image_b64 IS NOT NULL AND email IS NOT NULL AND qr_sent_at IS NULL
    """)
    students = cur.fetchall()
    sent = []
    failed = []

    try:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
    except Exception as e:
        return {'success': False, 'error': f'SMTP connection/login failed: {e}'}

    for student in students:
        msg = MIMEMultipart('related')
        msg['Subject'] = 'Tu código QR para el Acto de Firma del Libro de Grado'
        msg['From'] = SENDER_EMAIL
        recipients = [student['email']]
        if student.get('secondary_email'):
            recipients.append(student['secondary_email'])
        msg['To'] = ', '.join(recipients)
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset=\"UTF-8\">
          <title>Tu código QR para acceder al Acto de Firma del Libro de Grado</title>
        </head>
        <body style=\"background: #f7f7f7; font-family: Arial, sans-serif; margin:0; padding:0;\">
          <table width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"background: #fff; padding: 0; margin-bottom: 24px;\">
            <tr>
              <td align=\"center\" style=\"padding: 0;\">
                <div style=\"background: linear-gradient(90deg, #002060 0%, #009A44 100%); padding: 24px 0 12px 0; border-radius: 0 0 30px 30px;\">
                  <img src=\"cid:uamlogo\" alt=\"Universidad Arturo Michelena\" width=\"140\" style=\"display:block; margin:auto; background:#fff; border-radius: 12px; box-shadow:0 2px 8px rgba(0,0,0,0.08); padding: 6px;\">
                </div>
              </td>
            </tr>
          </table>
          <table width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"background: #fff; max-width: 600px; margin: 30px auto; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.05); border-top: 4px solid #002060;\">
            <tr>
              <td style=\"padding: 32px;\">
                <h2 style=\"color: #002060; margin-top: 0;\">Estimado(a), {student['first_name']} {student['last_name']}, ¡Felicitaciones por tan importante logro!</h2>
                <p>Adjunto encontrarás tu <b>código QR</b> para el Acto de Firma del Libro de Grado de la Universidad Arturo Michelena.</p>
                <p style=\"margin-bottom: 32px;\">Por favor, guarda este código y preséntalo el día del evento para tu ingreso.</p>
                <div style=\"text-align: center; margin-bottom: 32px;\">
                  <img src=\"cid:qrimage\" alt=\"Código QR\" style=\"width: 240px; height: 240px; border: 4px solid #009A44; border-radius: 16px; box-shadow:0 2px 12px rgba(0,32,96,0.12); background: #fff;\">
                </div>
                <hr style=\"border: none; border-top: 1px solid #eee; margin: 32px 0;\">
                <p style=\"font-size: 13px; color: #888;\">Este correo fue enviado automáticamente por la Universidad Arturo Michelena.<br>
                Si tienes dudas, contacta a <a href=\"mailto:info@uam.edu.ve\" style=\"color: #002060;\">info@uam.edu.ve</a>.</p>
              </td>
            </tr>
          </table>
          <table width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"background: #002060; padding: 10px 0; margin-top: 20px;\">
            <tr>
              <td align=\"center\">
                <span style=\"color: #fff; font-size: 13px;\">&copy; Universidad Arturo Michelena - Todos los derechos reservados</span>
              </td>
            </tr>
          </table>
        </body>
        </html>
        """
        msg.attach(MIMEText(html, 'html'))
        qr_bytes = base64.b64decode(student['qr_image_b64'])
        img = MIMEImage(qr_bytes, name="qrcode.png")
        img.add_header('Content-ID', '<qrimage>')
        img.add_header('Content-Disposition', 'inline', filename='qrimage.png')
        msg.attach(img)
        
        # Attach cached logo as a new MIMEImage instance for each email, explicitly set subtype to 'png'
        if CACHED_LOGO_IMAGE_BYTES:
            logo_img = MIMEImage(CACHED_LOGO_IMAGE_BYTES, _subtype='png')
            logo_img.add_header('Content-ID', '<uamlogo>')
            logo_img.add_header('Content-Disposition', 'inline', filename='uamlogo.png')
            msg.attach(logo_img)
        try:
            server.sendmail(SENDER_EMAIL, recipients, msg.as_string())
            ve_tz = pytz.timezone('America/Caracas')
            now = datetime.now(ve_tz).replace(tzinfo=None)
            cur.execute("UPDATE students SET qr_sent_at=%s WHERE id=%s", (now, student['id']))
            sent.append({'email': recipients, 'id': student['id']})
        except Exception as e:
            failed.append({'email': recipients, 'error': str(e), 'id': student['id']})
    conn.commit()
    cur.close()
    conn.close()
    server.quit()
    return {'success': True, 'sent_count': len(sent), 'failed_count': len(failed), 'sent': sent, 'failed': failed}

def send_qr_email_to_student(cedula):
    SENDER_EMAIL = os.environ.get('SENDER_EMAIL')
    SENDER_PASSWORD = os.environ.get('SENDER_PASSWORD')
    SMTP_HOST = os.environ.get('SMTP_HOST')
    SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
    if not all([SENDER_EMAIL, SENDER_PASSWORD, SMTP_HOST, SMTP_PORT]):
        return {'success': False, 'error': 'Missing email environment variable(s).'}
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM students WHERE cedula=%s", (cedula,))
    student = cur.fetchone()
    if not student or not student.get('email') or not student.get('qr_image_b64'):
        cur.close()
        conn.close()
        return {'success': False, 'error': 'Student not found or missing email/QR image.'}
    try:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
    except Exception as e:
        return {'success': False, 'error': f'SMTP connection/login failed: {e}'}
    msg = MIMEMultipart('related')
    msg['Subject'] = 'Tu código QR para acceder al Acto de Firma del Libro de Grado'
    msg['From'] = SENDER_EMAIL
    recipients = [student['email']]
    if student.get('secondary_email'):
        recipients.append(student['secondary_email'])
    msg['To'] = ', '.join(recipients)
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
                    <h2 style='color: #002060; margin-top: 0;'>Estimado(a), {student['first_name']} {student['last_name']}, ¡Felicitaciones por tan importante logro!</h2>
                    <p>Adjunto encontrarás tu <b>código QR</b> para el Acto de Firma del Libro de Grado de la Universidad Arturo Michelena.</p>
                    <p style='margin-bottom: 32px;'>Por favor, guarda este código y preséntalo el día del evento para tu ingreso.</p>
                    <div style='text-align: center; margin-bottom: 32px;'>
                        <img src='cid:qrimage' alt='Código QR' style='width: 240px; height: 240px; border: 4px solid #009A44; border-radius: 16px; box-shadow:0 2px 12px rgba(0,32,96,0.12); background: #fff;'>
                    </div>
                    <hr style='border: none; border-top: 1px solid #eee; margin: 32px 0;'>
                    <p style='font-size: 13px; color: #888;'>Este correo fue enviado automáticamente por la Universidad Arturo Michelena.<br>
                    Si tienes dudas, contacta a <a href='mailto:info@uam.edu.ve' style='color: #002060;'>info@uam.edu.ve</a>.</p>
                </td>
            </tr>
        </table>
        <table width='100%' cellpadding='0' cellspacing='0' style='background: #002060; padding: 10px 0; margin-top: 20px;'>
            <tr>
                <td align='center'>
                    <span style='color: #fff; font-size: 13px;'>&copy; Universidad Arturo Michelena - Todos los derechos reservados</span>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """
    msg.attach(MIMEText(html, 'html'))
    qr_bytes = base64.b64decode(student['qr_image_b64'])
    img = MIMEImage(qr_bytes, name="qrcode.png")
    img.add_header('Content-ID', '<qrimage>')
    img.add_header('Content-Disposition', 'inline', filename='qrimage.png')
    msg.attach(img)
    
    # Attach cached logo as a new MIMEImage instance for each email, explicitly set subtype to 'png'
    if CACHED_LOGO_IMAGE_BYTES:
        logo_img = MIMEImage(CACHED_LOGO_IMAGE_BYTES, _subtype='png')
        logo_img.add_header('Content-ID', '<uamlogo>')
        logo_img.add_header('Content-Disposition', 'inline', filename='uamlogo.png')
        msg.attach(logo_img)
    try:
        server.sendmail(SENDER_EMAIL, recipients, msg.as_string())
        ve_tz = pytz.timezone('America/Caracas')
        now = datetime.now(ve_tz).replace(tzinfo=None)
        cur.execute("UPDATE students SET qr_sent_at=%s WHERE id=%s", (now, student['id']))
        conn.commit()
        cur.close()
        conn.close()
        server.quit()
        return {'success': True, 'email': recipients}
    except Exception as e:
        server.quit()
        return {'success': False, 'error': str(e)}
