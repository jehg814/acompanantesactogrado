import io
import os
import qrcode
import base64
from datetime import datetime
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.units import inch, mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from PIL import Image as PILImage
import urllib.request

# UAM Brand Colors
UAM_BLUE = HexColor('#002060')
UAM_GREEN = HexColor('#009A44')
UAM_LIGHT_GRAY = HexColor('#f7f7f7')

# Optional logo (disabled by default to reduce PDF size). Enable by setting PDF_INCLUDE_LOGO=1
PDF_INCLUDE_LOGO = os.environ.get('PDF_INCLUDE_LOGO', '0') == '1'

def get_uam_logo():
    if not PDF_INCLUDE_LOGO:
        return None
    try:
        with urllib.request.urlopen('https://res.cloudinary.com/demc0oskw/image/upload/v1746210685/uam_logo_fjqv6p.png') as response:
            return response.read()
    except Exception as e:
        print(f"Warning: Could not download logo: {e}")
        return None

def create_qr_code(data):
    """Generate QR code and return as bytes"""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)
    
    # Create image with white background
    qr_image = qr.make_image(fill_color="black", back_color="white")
    
    # Convert to bytes
    img_buffer = io.BytesIO()
    qr_image.save(img_buffer, format='PNG')
    img_buffer.seek(0)
    return img_buffer.getvalue()

def create_invitation_pdf(student_name, companion_number, qr_data):
    """Create a PDF invitation for a companion"""
    
    # Create PDF buffer
    pdf_buffer = io.BytesIO()
    
    # Create document
    doc = SimpleDocTemplate(
        pdf_buffer,
        pagesize=A4,
        rightMargin=20*mm,
        leftMargin=20*mm,
        topMargin=15*mm,
        bottomMargin=15*mm
    )

    # Compressed canvas to reduce PDF size
    class CompressedCanvas(canvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.setPageCompression(1)
    
    # Get styles
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        spaceAfter=20,
        alignment=TA_CENTER,
        textColor=UAM_BLUE,
        fontName='Helvetica-Bold'
    )
    
    subtitle_style = ParagraphStyle(
        'CustomSubtitle',
        parent=styles['Heading2'],
        fontSize=18,
        spaceAfter=15,
        alignment=TA_CENTER,
        textColor=UAM_GREEN,
        fontName='Helvetica-Bold'
    )
    
    body_style = ParagraphStyle(
        'CustomBody',
        parent=styles['Normal'],
        fontSize=12,
        spaceAfter=12,
        alignment=TA_CENTER,
        textColor=black,
        fontName='Helvetica'
    )
    
    emphasis_style = ParagraphStyle(
        'Emphasis',
        parent=styles['Normal'],
        fontSize=14,
        spaceAfter=12,
        alignment=TA_CENTER,
        textColor=UAM_BLUE,
        fontName='Helvetica-Bold'
    )
    
    # Build content
    story = []
    
    # Add logo only if explicitly enabled
    logo_bytes = get_uam_logo()
    if logo_bytes:
        pil_img = PILImage.open(io.BytesIO(logo_bytes))
        original_width, original_height = pil_img.size
        target_height = 48  # Slightly smaller to reduce size
        aspect_ratio = original_width / original_height
        target_width = target_height * aspect_ratio
        logo_img = Image(io.BytesIO(logo_bytes))
        logo_img.drawHeight = target_height
        logo_img.drawWidth = target_width
        story.append(logo_img)
        story.append(Spacer(1, 12))
    
    # Header with gradient-like effect using table
    header_data = [['UNIVERSIDAD ARTURO MICHELENA']]
    header_table = Table(header_data, colWidths=[170*mm])
    header_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), UAM_BLUE),
        ('TEXTCOLOR', (0, 0), (-1, -1), white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 16),
        ('TOPPADDING', (0, 0), (-1, -1), 12),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 20))
    
    # Title
    story.append(Paragraph("INVITACIÓN ESPECIAL", title_style))
    story.append(Paragraph("Acto de Grado", subtitle_style))
    story.append(Spacer(1, 15))
    
    # Main content
    story.append(Paragraph(f"<b>Graduando:</b> {student_name}", emphasis_style))
    story.append(Spacer(1, 15))
    
    story.append(Paragraph(f"<b>Invitación para Acompañante #{companion_number}</b>", emphasis_style))
    story.append(Spacer(1, 10))
    
    # Event details
    event_text = """
    Tenemos el honor de invitarle al solemne Acto de Grado, 
    ceremonia que marca la culminación de los estudios universitarios de nuestro graduando.
    """
    story.append(Paragraph(event_text, body_style))
    story.append(Spacer(1, 15))
    
    # QR Code
    qr_bytes = create_qr_code(qr_data)
    qr_img = Image(io.BytesIO(qr_bytes))
    qr_img.drawHeight = 110
    qr_img.drawWidth = 110
    
    # QR Container with border
    qr_data_table = [
        [qr_img],
        [Paragraph("<b>CÓDIGO DE ACCESO</b>", emphasis_style)],
        [Paragraph("Presente este código en el acceso al evento", body_style)]
    ]
    qr_table = Table(qr_data_table, colWidths=[140])
    qr_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOX', (0, 0), (-1, -1), 2, UAM_GREEN),
        ('BACKGROUND', (0, 0), (-1, -1), UAM_LIGHT_GRAY),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
    ]))
    story.append(qr_table)
    story.append(Spacer(1, 20))
    
    # Instructions
    instructions = """
    <b>INSTRUCCIONES IMPORTANTES:</b><br/>
    • Esta invitación es personal e intransferible<br/>
    • Debe presentar este código QR en el acceso<br/>
    • Llegue con 30 minutos de anticipación<br/>
    • Use vestimenta formal para la ocasión
    """
    story.append(Paragraph(instructions, body_style))
    story.append(Spacer(1, 20))
    
    # Footer
    footer_data = [['© Universidad Arturo Michelena - Todos los derechos reservados']]
    footer_table = Table(footer_data, colWidths=[170*mm])
    footer_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), UAM_BLUE),
        ('TEXTCOLOR', (0, 0), (-1, -1), white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(footer_table)
    
    # Build PDF with compression
    doc.build(story, canvasmaker=CompressedCanvas)
    pdf_buffer.seek(0)
    return pdf_buffer.getvalue()

def generate_companion_pdfs(student_id, student_name, companion_qr_codes):
    """
    Generate PDF invitations for both companions
    
    Args:
        student_id: ID of the graduate
        student_name: Full name of the graduate
        companion_qr_codes: List of QR codes for each companion [(qr_data_1, qr_data_2)]
    
    Returns:
        List of PDF bytes: [pdf_companion_1_bytes, pdf_companion_2_bytes]
    """
    pdfs = []
    
    for i, qr_data in enumerate(companion_qr_codes, 1):
        pdf_bytes = create_invitation_pdf(student_name, i, qr_data)
        pdfs.append(pdf_bytes)
    
    return pdfs