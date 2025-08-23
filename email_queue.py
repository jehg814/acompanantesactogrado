import asyncio
import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from db import get_db_connection, RealDictCursor
from datetime import datetime
import pytz
import base64
import urllib.request
import logging
from dataclasses import dataclass
from typing import List, Optional
import time
import json

logger = logging.getLogger(__name__)

@dataclass
class EmailJob:
    student_id: int
    email: str
    secondary_email: Optional[str]
    first_name: str
    last_name: str
    qr_image_b64: str
    priority: int = 0  # Higher number = higher priority
    retry_count: int = 0
    max_retries: int = 3

class EmailQueue:
    def __init__(self, rate_limit_per_minute=30, batch_size=10, max_retries=3):
        self.rate_limit_per_minute = rate_limit_per_minute
        self.batch_size = batch_size
        self.max_retries = max_retries
        self.queue = asyncio.Queue()
        self.failed_queue = asyncio.Queue()
        self.sent_count = 0
        self.failed_count = 0
        self.ve_tz = pytz.timezone('America/Caracas')
        
        # Cache logo image once
        self.cached_logo_bytes = self._load_cached_logo()
        
        # Email credentials
        self.smtp_config = {
            'host': os.environ.get('SMTP_HOST'),
            'port': int(os.environ.get('SMTP_PORT', 587)),
            'username': os.environ.get('SMTP_USERNAME') or os.environ.get('SENDER_EMAIL'),
            'password': os.environ.get('SMTP_PASSWORD') or os.environ.get('SENDER_PASSWORD')
        }
    
    def _load_cached_logo(self):
        """Load and cache the logo image once"""
        try:
            with urllib.request.urlopen('https://res.cloudinary.com/demc0oskw/image/upload/v1746210685/uam_logo_fjqv6p.png') as response:
                return response.read()
        except Exception as e:
            logger.warning(f"Could not download logo image: {e}")
            return None
    
    def _validate_smtp_config(self):
        """Validate SMTP configuration"""
        required_fields = ['host', 'port', 'username', 'password']
        missing = [field for field in required_fields if not self.smtp_config.get(field)]
        if missing:
            raise ValueError(f"Missing SMTP configuration: {missing}")
    
    async def add_job(self, job: EmailJob):
        """Add an email job to the queue"""
        await self.queue.put(job)
    
    async def load_pending_emails(self):
        """Load all pending emails from database and add to queue"""
        conn = get_db_connection()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                SELECT id, email, secondary_email, first_name, last_name, qr_image_b64 
                FROM students
                WHERE qr_image_b64 IS NOT NULL AND email IS NOT NULL AND qr_sent_at IS NULL
                ORDER BY id
            """)
            students = cur.fetchall()
            
            for student in students:
                job = EmailJob(
                    student_id=student['id'],
                    email=student['email'],
                    secondary_email=student.get('secondary_email'),
                    first_name=student['first_name'],
                    last_name=student['last_name'],
                    qr_image_b64=student['qr_image_b64']
                )
                await self.add_job(job)
            
            logger.info(f"Loaded {len(students)} pending emails into queue")
            return len(students)
            
        finally:
            cur.close()
            conn.close()
    
    def _create_email_message(self, job: EmailJob):
        """Create email message for a job"""
        msg = MIMEMultipart('related')
        msg['Subject'] = 'Tu código QR para el Acto de Firma del Libro de Grado'
        msg['From'] = self.smtp_config['username']
        
        recipients = [job.email]
        if job.secondary_email:
            recipients.append(job.secondary_email)
        msg['To'] = ', '.join(recipients)
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="UTF-8">
          <title>Tu código QR para acceder al Acto de Firma del Libro de Grado</title>
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
                <h2 style="color: #002060; margin-top: 0;">Estimado(a), {job.first_name} {job.last_name}, ¡Felicitaciones por tan importante logro!</h2>
                <p>Adjunto encontrarás tu <b>código QR</b> para el Acto de Firma del Libro de Grado de la Universidad Arturo Michelena.</p>
                <p style="margin-bottom: 32px;">Por favor, guarda este código y preséntalo el día del evento para tu ingreso.</p>
                <div style="text-align: center; margin-bottom: 32px;">
                  <img src="cid:qrimage" alt="Código QR" style="width: 240px; height: 240px; border: 4px solid #009A44; border-radius: 16px; box-shadow:0 2px 12px rgba(0,32,96,0.12); background: #fff;">
                </div>
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
        
        # Attach QR code
        qr_bytes = base64.b64decode(job.qr_image_b64)
        qr_img = MIMEImage(qr_bytes, name="qrcode.png")
        qr_img.add_header('Content-ID', '<qrimage>')
        qr_img.add_header('Content-Disposition', 'inline', filename='qrimage.png')
        msg.attach(qr_img)
        
        # Attach logo
        if self.cached_logo_bytes:
            logo_img = MIMEImage(self.cached_logo_bytes, _subtype='png')
            logo_img.add_header('Content-ID', '<uamlogo>')
            logo_img.add_header('Content-Disposition', 'inline', filename='uamlogo.png')
            msg.attach(logo_img)
        
        return msg, recipients
    
    async def _send_single_email(self, job: EmailJob, server):
        """Send a single email"""
        try:
            msg, recipients = self._create_email_message(job)
            server.sendmail(self.smtp_config['username'], recipients, msg.as_string())
            
            # Update database
            conn = get_db_connection()
            try:
                cur = conn.cursor()
                now = datetime.now(self.ve_tz).replace(tzinfo=None)
                cur.execute("UPDATE students SET qr_sent_at=%s WHERE id=%s", (now, job.student_id))
                conn.commit()
            finally:
                cur.close()
                conn.close()
            
            self.sent_count += 1
            logger.info(f"Email sent successfully to {recipients} (student_id: {job.student_id})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email to student {job.student_id}: {e}")
            return False
    
    async def _process_batch(self, jobs: List[EmailJob]):
        """Process a batch of email jobs with a single SMTP connection"""
        if not jobs:
            return
        
        try:
            # Create single SMTP connection for the batch
            server = smtplib.SMTP(self.smtp_config['host'], self.smtp_config['port'])
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(self.smtp_config['username'], self.smtp_config['password'])
            
            # Send emails in batch
            for job in jobs:
                success = await self._send_single_email(job, server)
                if not success:
                    job.retry_count += 1
                    if job.retry_count < self.max_retries:
                        await self.failed_queue.put(job)
                    else:
                        self.failed_count += 1
                        logger.error(f"Email permanently failed for student {job.student_id} after {self.max_retries} retries")
            
            server.quit()
            
        except Exception as e:
            logger.error(f"Batch email processing failed: {e}")
            # Re-queue failed jobs for retry
            for job in jobs:
                job.retry_count += 1
                if job.retry_count < self.max_retries:
                    await self.failed_queue.put(job)
                else:
                    self.failed_count += 1
    
    async def start_worker(self):
        """Start the email worker with rate limiting"""
        self._validate_smtp_config()
        logger.info(f"Starting email worker with rate limit: {self.rate_limit_per_minute}/minute")
        
        interval = 60.0 / self.rate_limit_per_minute * self.batch_size  # Seconds between batches
        
        while True:
            batch = []
            
            # Collect batch of jobs
            for _ in range(self.batch_size):
                try:
                    job = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                    batch.append(job)
                except asyncio.TimeoutError:
                    break
            
            if batch:
                await self._process_batch(batch)
                
                # Rate limiting
                if len(batch) == self.batch_size:
                    await asyncio.sleep(interval)
            else:
                # No jobs available, wait before checking again
                await asyncio.sleep(5.0)
    
    async def process_retry_queue(self):
        """Process failed emails for retry"""
        while not self.failed_queue.empty():
            try:
                job = await asyncio.wait_for(self.failed_queue.get(), timeout=1.0)
                await self.queue.put(job)
            except asyncio.TimeoutError:
                break
    
    async def get_stats(self):
        """Get queue statistics"""
        return {
            'queue_size': self.queue.qsize(),
            'failed_queue_size': self.failed_queue.qsize(),
            'sent_count': self.sent_count,
            'failed_count': self.failed_count
        }

# Main function to send all pending emails
async def send_qr_emails_batch():
    """Send all pending QR emails using the queue system"""
    email_queue = EmailQueue(rate_limit_per_minute=30, batch_size=5)
    
    # Load pending emails
    total_emails = await email_queue.load_pending_emails()
    
    if total_emails == 0:
        return {'success': True, 'message': 'No pending emails to send'}
    
    # Start worker
    worker_task = asyncio.create_task(email_queue.start_worker())
    
    # Monitor progress
    start_time = time.time()
    while email_queue.queue.qsize() > 0 or email_queue.failed_queue.qsize() > 0:
        stats = await email_queue.get_stats()
        logger.info(f"Email progress: {stats}")
        
        # Process retries
        if email_queue.failed_queue.qsize() > 0:
            await email_queue.process_retry_queue()
        
        await asyncio.sleep(10)  # Check progress every 10 seconds
        
        # Timeout after 30 minutes
        if time.time() - start_time > 1800:
            logger.warning("Email processing timeout reached")
            break
    
    # Cancel worker
    worker_task.cancel()
    
    final_stats = await email_queue.get_stats()
    return {
        'success': True,
        'total_emails': total_emails,
        'sent_count': final_stats['sent_count'],
        'failed_count': final_stats['failed_count'],
        'stats': final_stats
    }