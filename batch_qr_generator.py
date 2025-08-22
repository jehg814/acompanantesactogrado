import asyncio
import uuid
import qrcode
import base64
import io
from datetime import datetime
import pytz
from db import get_db_connection
from PIL import Image, ImageDraw
import logging
from concurrent.futures import ThreadPoolExecutor
import gc

logger = logging.getLogger(__name__)

class BatchQRGenerator:
    def __init__(self, batch_size=50, max_workers=4):
        self.batch_size = batch_size
        self.max_workers = max_workers
        self.ve_tz = pytz.timezone('America/Caracas')
        
    def generate_single_qr(self, student_data):
        """Generate QR code for a single student - optimized for memory"""
        try:
            qr_data = str(uuid.uuid4())
            
            # Generate QR code with minimal memory usage
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(qr_data)
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
            
            # Optimized frame generation
            border_size = 20
            frame_color_1 = (0, 32, 96)   # UAM Blue
            frame_color_2 = (0, 154, 68)  # UAM Green
            
            size = (qr_img.size[0] + border_size * 2, qr_img.size[1] + border_size * 2)
            frame = Image.new('RGB', size, frame_color_1)
            draw = ImageDraw.Draw(frame)
            
            # More efficient gradient
            height = size[1]
            for y in range(0, height, 2):  # Skip every other line for performance
                ratio = y / height
                r = int(frame_color_1[0] * (1 - ratio) + frame_color_2[0] * ratio)
                g = int(frame_color_1[1] * (1 - ratio) + frame_color_2[1] * ratio)
                b = int(frame_color_1[2] * (1 - ratio) + frame_color_2[2] * ratio)
                draw.line([(0, y), (size[0], y + 1)], fill=(r, g, b))
            
            frame.paste(qr_img, (border_size, border_size))
            
            # Compress to reduce memory usage
            buf = io.BytesIO()
            frame.save(buf, format='PNG', optimize=True, compress_level=6)
            qr_b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
            
            # Clean up memory immediately
            del qr_img, frame, draw, buf
            gc.collect()
            
            return {
                'student_id': student_data['id'],
                'qr_data': qr_data,
                'qr_image_b64': qr_b64,
                'qr_generated_at': datetime.now(self.ve_tz)
            }
            
        except Exception as e:
            logger.error(f"Failed to generate QR for student {student_data.get('id')}: {e}")
            return None
    
    async def generate_batch_async(self, students):
        """Generate QR codes in parallel batches"""
        all_qr_data = []
        
        # Process in batches to control memory usage
        for i in range(0, len(students), self.batch_size):
            batch = students[i:i + self.batch_size]
            logger.info(f"Processing QR batch {i//self.batch_size + 1}/{(len(students)-1)//self.batch_size + 1}")
            
            # Use ThreadPoolExecutor for CPU-bound QR generation
            loop = asyncio.get_event_loop()
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                tasks = [
                    loop.run_in_executor(executor, self.generate_single_qr, student)
                    for student in batch
                ]
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Filter out None results and exceptions
            valid_results = [r for r in batch_results if r is not None and not isinstance(r, Exception)]
            all_qr_data.extend(valid_results)
            
            # Force garbage collection after each batch
            gc.collect()
            
            # Small delay to prevent overwhelming the system
            await asyncio.sleep(0.1)
        
        return all_qr_data
    
    async def bulk_update_database(self, qr_data_list):
        """Bulk update database with generated QR codes"""
        if not qr_data_list:
            return
            
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            
            # Use bulk update with VALUES clause for better performance
            values_data = []
            for qr_data in qr_data_list:
                values_data.append((
                    qr_data['qr_data'],
                    qr_data['qr_generated_at'],
                    qr_data['qr_image_b64'],
                    qr_data['student_id']
                ))
            
            # Use execute_values for bulk update
            from psycopg2.extras import execute_values
            
            # Prepare update query with individual updates
            for qr_data in qr_data_list:
                cur.execute("""
                    UPDATE students SET 
                        qr_data = %s,
                        qr_generated_at = %s,
                        qr_image_b64 = %s
                    WHERE id = %s
                """, (
                    qr_data['qr_data'],
                    qr_data['qr_generated_at'],
                    qr_data['qr_image_b64'],
                    qr_data['student_id']
                ))
            
            conn.commit()
            logger.info(f"Bulk updated {len(qr_data_list)} student QR codes")
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Bulk QR update failed: {e}")
            raise
        finally:
            cur.close()
            conn.close()
    
    async def generate_missing_qrs_batch(self):
        """Main method to generate all missing QR codes in batches"""
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, student_remote_id, first_name, last_name 
                FROM students 
                WHERE payment_confirmed=TRUE AND (qr_data IS NULL OR qr_image_b64 IS NULL)
            """)
            students = cur.fetchall()
            cur.close()
            conn.close()
            
            if not students:
                logger.info("No students need QR code generation")
                return {'success': True, 'generated_count': 0}
            
            logger.info(f"Starting batch QR generation for {len(students)} students")
            
            # Generate QR codes in batches
            qr_data_list = await self.generate_batch_async(students)
            
            # Bulk update database
            await self.bulk_update_database(qr_data_list)
            
            return {
                'success': True, 
                'generated_count': len(qr_data_list),
                'total_students': len(students)
            }
            
        except Exception as e:
            logger.error(f"Batch QR generation failed: {e}")
            return {'success': False, 'error': str(e)}

# Async wrapper for backward compatibility
async def generate_missing_qrs_async():
    generator = BatchQRGenerator()
    return await generator.generate_missing_qrs_batch()