import asyncio
import json
import logging
from datetime import datetime
from enum import Enum
from dataclasses import dataclass, asdict
from typing import Optional, Dict, List, Callable, Any
import traceback
import pytz
from db import get_db_connection
import uuid

logger = logging.getLogger(__name__)

class JobStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class JobType(Enum):
    SYNC_STUDENTS = "sync_students"
    GENERATE_QRS = "generate_qrs"
    SEND_EMAILS = "send_emails"
    FULL_PROCESS = "full_process"
    SEND_COMPANION_INVITATIONS = "send_companion_invitations"

@dataclass
class Job:
    id: str
    job_type: JobType
    status: JobStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    progress: int = 0  # 0-100
    total_items: int = 0
    processed_items: int = 0
    error_message: Optional[str] = None
    result: Optional[Dict] = None
    parameters: Optional[Dict] = None

class JobManager:
    def __init__(self):
        self.active_jobs: Dict[str, Job] = {}
        self.job_handlers = {
            JobType.SYNC_STUDENTS: self._handle_sync_students,
            JobType.GENERATE_QRS: self._handle_generate_qrs,
            JobType.SEND_EMAILS: self._handle_send_emails,
            JobType.FULL_PROCESS: self._handle_full_process,
            JobType.SEND_COMPANION_INVITATIONS: self._handle_send_companion_invitations
        }
        self.ve_tz = pytz.timezone('America/Caracas')
    
    def create_job(self, job_type: JobType, parameters: Optional[Dict] = None) -> str:
        """Create a new background job"""
        job_id = str(uuid.uuid4())
        job = Job(
            id=job_id,
            job_type=job_type,
            status=JobStatus.PENDING,
            created_at=datetime.now(self.ve_tz),
            parameters=parameters or {}
        )
        
        self.active_jobs[job_id] = job
        logger.info(f"Created job {job_id} of type {job_type.value}")
        return job_id
    
    async def start_job(self, job_id: str) -> bool:
        """Start executing a job in background"""
        if job_id not in self.active_jobs:
            logger.error(f"Job {job_id} not found")
            return False
        
        job = self.active_jobs[job_id]
        if job.status != JobStatus.PENDING:
            logger.warning(f"Job {job_id} is not in pending status: {job.status}")
            return False
        
        # Start job in background
        asyncio.create_task(self._execute_job(job_id))
        return True
    
    async def _execute_job(self, job_id: str):
        """Execute a job and handle errors"""
        job = self.active_jobs[job_id]
        
        try:
            job.status = JobStatus.RUNNING
            job.started_at = datetime.now(self.ve_tz)
            logger.info(f"Starting job {job_id} ({job.job_type.value})")
            
            # Execute the appropriate handler
            handler = self.job_handlers.get(job.job_type)
            if not handler:
                raise ValueError(f"No handler for job type {job.job_type}")
            
            result = await handler(job)
            
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.now(self.ve_tz)
            job.result = result
            job.progress = 100
            
            logger.info(f"Job {job_id} completed successfully")
            
        except Exception as e:
            job.status = JobStatus.FAILED
            job.completed_at = datetime.now(self.ve_tz)
            job.error_message = str(e)
            logger.error(f"Job {job_id} failed: {e}")
            logger.error(traceback.format_exc())
    
    async def _handle_sync_students(self, job: Job) -> Dict:
        """Handle student sync job"""
        from bulk_sync import sync_paid_students_bulk_async
        
        job.progress = 10
        from_date = job.parameters.get('from_date', '2025-01-01')
        
        logger.info(f"Starting student sync from {from_date}")
        result = await sync_paid_students_bulk_async(from_date)
        
        job.total_items = result.get('total_processed', 0)
        job.processed_items = job.total_items
        
        return result
    
    async def _handle_generate_qrs(self, job: Job) -> Dict:
        """Handle QR generation job"""
        from batch_qr_generator import generate_missing_qrs_async
        
        job.progress = 10
        logger.info("Starting batch QR generation")
        
        result = await generate_missing_qrs_async()
        
        job.total_items = result.get('total_students', 0)
        job.processed_items = result.get('generated_count', 0)
        
        return result
    
    async def _handle_send_emails(self, job: Job) -> Dict:
        """Handle email sending job"""
        from email_queue import send_qr_emails_batch
        
        job.progress = 10
        logger.info("Starting batch email sending")
        
        # Create a progress callback to update job status
        async def progress_callback(sent_count: int, total_count: int):
            job.processed_items = sent_count
            job.total_items = total_count
            job.progress = min(90, int(sent_count / total_count * 90)) if total_count > 0 else 90
        
        result = await send_qr_emails_batch()
        
        job.total_items = result.get('total_emails', 0)
        job.processed_items = result.get('sent_count', 0)
        
        return result

    async def _handle_send_companion_invitations(self, job: Job) -> Dict:
        """Handle sending companion invitations (supports DRY RUN)"""
        from send_companion_invitations import send_companion_invitations
        loop = asyncio.get_event_loop()
        job.progress = 10
        # Run sync function in thread to avoid blocking
        result = await loop.run_in_executor(None, send_companion_invitations)
        # Try to extract counts for progress
        if isinstance(result, dict):
            total = result.get('previewed_count') or result.get('sent_count') or 0
            job.total_items = total
            job.processed_items = total
            job.progress = 100
        return result
    
    async def _handle_full_process(self, job: Job) -> Dict:
        """Handle full process: sync -> generate QRs -> send emails"""
        results = {}
        
        try:
            # Step 1: Sync students
            job.progress = 5
            logger.info("Full process: Step 1 - Syncing students")
            from bulk_sync import sync_paid_students_bulk_async
            
            from_date = job.parameters.get('from_date', '2025-01-01')
            sync_result = await sync_paid_students_bulk_async(from_date)
            results['sync'] = sync_result
            
            if not sync_result.get('success'):
                raise Exception(f"Sync failed: {sync_result.get('error')}")
            
            # Step 2: Generate QR codes
            job.progress = 35
            logger.info("Full process: Step 2 - Generating QR codes")
            from batch_qr_generator import generate_missing_qrs_async
            
            qr_result = await generate_missing_qrs_async()
            results['qr_generation'] = qr_result
            
            if not qr_result.get('success'):
                raise Exception(f"QR generation failed: {qr_result.get('error')}")
            
            # Step 3: Send emails
            job.progress = 65
            logger.info("Full process: Step 3 - Sending emails")
            from email_queue import send_qr_emails_batch
            
            email_result = await send_qr_emails_batch()
            results['email_sending'] = email_result
            
            if not email_result.get('success'):
                raise Exception(f"Email sending failed: {email_result.get('error')}")
            
            job.progress = 100
            
            # Summary
            total_synced = sync_result.get('total_processed', 0)
            total_qrs = qr_result.get('generated_count', 0)
            total_emails = email_result.get('sent_count', 0)
            
            job.total_items = total_synced
            job.processed_items = total_emails
            
            results['summary'] = {
                'students_synced': total_synced,
                'qr_codes_generated': total_qrs,
                'emails_sent': total_emails
            }
            
            return results
            
        except Exception as e:
            results['error'] = str(e)
            raise
    
    def get_job_status(self, job_id: str) -> Optional[Dict]:
        """Get job status and progress"""
        if job_id not in self.active_jobs:
            return None
        
        job = self.active_jobs[job_id]
        return {
            'id': job.id,
            'type': job.job_type.value,
            'status': job.status.value,
            'progress': job.progress,
            'total_items': job.total_items,
            'processed_items': job.processed_items,
            'created_at': job.created_at.isoformat() if job.created_at else None,
            'started_at': job.started_at.isoformat() if job.started_at else None,
            'completed_at': job.completed_at.isoformat() if job.completed_at else None,
            'error_message': job.error_message,
            'result': job.result
        }
    
    def list_jobs(self) -> List[Dict]:
        """List all jobs with their status"""
        return [self.get_job_status(job_id) for job_id in self.active_jobs.keys()]
    
    def cancel_job(self, job_id: str) -> bool:
        """Cancel a job (if it's still pending)"""
        if job_id not in self.active_jobs:
            return False
        
        job = self.active_jobs[job_id]
        if job.status == JobStatus.PENDING:
            job.status = JobStatus.CANCELLED
            job.completed_at = datetime.now(self.ve_tz)
            logger.info(f"Job {job_id} cancelled")
            return True
        
        return False
    
    def cleanup_completed_jobs(self, max_age_hours: int = 24):
        """Remove completed jobs older than max_age_hours"""
        cutoff_time = datetime.now(self.ve_tz).timestamp() - (max_age_hours * 3600)
        
        jobs_to_remove = []
        for job_id, job in self.active_jobs.items():
            if job.status in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]:
                if job.completed_at and job.completed_at.timestamp() < cutoff_time:
                    jobs_to_remove.append(job_id)
        
        for job_id in jobs_to_remove:
            del self.active_jobs[job_id]
            logger.info(f"Cleaned up old job {job_id}")
        
        return len(jobs_to_remove)

# Global job manager instance
job_manager = JobManager()

# Convenience functions
async def start_sync_job(from_date: str = '2025-01-01') -> str:
    """Start a student sync job"""
    job_id = job_manager.create_job(JobType.SYNC_STUDENTS, {'from_date': from_date})
    await job_manager.start_job(job_id)
    return job_id

async def start_qr_generation_job() -> str:
    """Start a QR generation job"""
    job_id = job_manager.create_job(JobType.GENERATE_QRS)
    await job_manager.start_job(job_id)
    return job_id

async def start_email_job() -> str:
    """Start an email sending job"""
    job_id = job_manager.create_job(JobType.SEND_EMAILS)
    await job_manager.start_job(job_id)
    return job_id

async def start_full_process_job(from_date: str = '2025-01-01') -> str:
    """Start a full process job (sync + QR + email)"""
    job_id = job_manager.create_job(JobType.FULL_PROCESS, {'from_date': from_date})
    await job_manager.start_job(job_id)
    return job_id

async def start_companion_invitations_job() -> str:
    """Start job to send companion invitations (or DRY RUN)"""
    job_id = job_manager.create_job(JobType.SEND_COMPANION_INVITATIONS)
    await job_manager.start_job(job_id)
    return job_id