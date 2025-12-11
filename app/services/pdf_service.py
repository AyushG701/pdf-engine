"""
PDF Service - Handles PDF file operations, page rendering, and text detection.
"""
import fitz  # PyMuPDF
import os
import io
import base64
import uuid
import logging
from pathlib import Path
from typing import Optional, Tuple
from datetime import datetime
from sqlalchemy.orm import Session
from fastapi import UploadFile, HTTPException

from app.config import settings
from app.models.models import PDFDocument
from app.schemas.schemas import (
    PDFUploadResponse,
    PDFInfoResponse,
    TextDetectionRequest,
    TextDetectionResponse,
    LineData
)
from app.utils.text_detection import TextDetector

logger = logging.getLogger("pdf_editor.services.pdf")


class PDFService:
    """Service for PDF file operations."""

    @staticmethod
    async def upload_pdf(file: UploadFile, db: Session) -> PDFUploadResponse:
        """
        Upload and store a PDF file.

        Args:
            file: Uploaded file from FastAPI
            db: Database session

        Returns:
            PDFUploadResponse with file metadata
        """
        # Validate file type
        if not file.filename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail="Only PDF files are allowed")

        # Read file content
        content = await file.read()

        # Validate file size
        if len(content) > settings.max_file_size_bytes:
            raise HTTPException(
                status_code=400,
                detail=f"File too large. Maximum size is {settings.MAX_FILE_SIZE_MB}MB"
            )

        # Validate it's a valid PDF
        try:
            doc = fitz.open(stream=content, filetype="pdf")
            page_count = len(doc)
            doc.close()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid PDF file")

        # Generate unique filename
        file_id = str(uuid.uuid4())
        safe_filename = f"{file_id}.pdf"
        file_path = os.path.join(settings.UPLOAD_DIR, safe_filename)

        # Save file
        with open(file_path, "wb") as f:
            f.write(content)

        # Create database record
        pdf_doc = PDFDocument(
            id=file_id,
            filename=safe_filename,
            original_filename=file.filename,
            file_path=file_path,
            file_size=len(content),
            page_count=page_count
        )
        db.add(pdf_doc)
        db.commit()
        db.refresh(pdf_doc)

        return PDFUploadResponse(
            id=pdf_doc.id,
            filename=pdf_doc.filename,
            original_filename=pdf_doc.original_filename,
            page_count=pdf_doc.page_count,
            file_size=pdf_doc.file_size,
            created_at=pdf_doc.created_at
        )

    @staticmethod
    def get_pdf_info(pdf_id: str, db: Session) -> PDFInfoResponse:
        """Get PDF document metadata."""
        pdf_doc = db.query(PDFDocument).filter(PDFDocument.id == pdf_id).first()
        if not pdf_doc:
            raise HTTPException(status_code=404, detail="PDF not found")

        # Get page dimensions from first page
        width, height = None, None
        try:
            doc = fitz.open(pdf_doc.file_path)
            if len(doc) > 0:
                page = doc[0]
                rect = page.rect
                width = rect.width
                height = rect.height
            doc.close()
        except Exception:
            pass

        return PDFInfoResponse(
            id=pdf_doc.id,
            filename=pdf_doc.filename,
            original_filename=pdf_doc.original_filename,
            page_count=pdf_doc.page_count,
            file_size=pdf_doc.file_size,
            created_at=pdf_doc.created_at,
            width=width,
            height=height
        )

    @staticmethod
    def get_page_image(
        pdf_id: str,
        page_num: int,
        db: Session,
        zoom: float = 1.5,
        as_base64: bool = True
    ) -> Tuple[bytes, int, int, float, float]:
        """
        Render a PDF page as an image.

        Args:
            pdf_id: PDF document ID
            page_num: Page number (0-indexed)
            db: Database session
            zoom: Zoom factor for rendering
            as_base64: Return as base64 string if True

        Returns:
            Tuple of (image_data, total_pages, page_num, width, height)
        """
        logger.debug(f"get_page_image called: pdf_id={pdf_id}, page_num={page_num}, zoom={zoom}")

        pdf_doc = db.query(PDFDocument).filter(PDFDocument.id == pdf_id).first()
        if not pdf_doc:
            logger.warning(f"PDF not found in database: {pdf_id}")
            raise HTTPException(status_code=404, detail="PDF not found")

        if not os.path.exists(pdf_doc.file_path):
            logger.error(f"PDF file not found on disk: {pdf_doc.file_path}")
            raise HTTPException(status_code=404, detail="PDF file not found on disk")

        doc = None
        try:
            logger.debug(f"Opening PDF file: {pdf_doc.file_path}")
            doc = fitz.open(pdf_doc.file_path)

            if page_num < 0 or page_num >= len(doc):
                logger.warning(f"Invalid page number {page_num} for PDF with {len(doc)} pages")
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid page number. PDF has {len(doc)} pages (0-{len(doc)-1})"
                )

            page = doc[page_num]
            mat = fitz.Matrix(zoom, zoom)

            logger.debug(f"Rendering page {page_num} at zoom {zoom}")
            pix = page.get_pixmap(matrix=mat)

            # Get dimensions (after zoom)
            width = pix.width
            height = pix.height

            # Convert to PNG
            img_data = pix.tobytes("png")
            total_pages = len(doc)

            logger.debug(f"Page rendered successfully: {width}x{height}, {len(img_data)} bytes")

            if as_base64:
                img_data = base64.b64encode(img_data).decode('utf-8')
                logger.debug(f"Converted to base64: {len(img_data)} chars")

            return img_data, total_pages, page_num, width, height

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error rendering page: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Error rendering page: {str(e)}")
        finally:
            if doc:
                doc.close()

    @staticmethod
    def detect_text_in_area(
        pdf_id: str,
        request: TextDetectionRequest,
        db: Session
    ) -> TextDetectionResponse:
        """
        Detect text within a selected area of a PDF page.

        Args:
            pdf_id: PDF document ID
            request: Detection request with coordinates
            db: Database session

        Returns:
            TextDetectionResponse with detected text and layout info
        """
        logger.info(f"=== DETECT TEXT REQUEST ===")
        logger.info(f"PDF ID: {pdf_id}")
        logger.info(f"Page: {request.page}")
        logger.info(f"Coordinates: x0={request.x0}, y0={request.y0}, x1={request.x1}, y1={request.y1}")

        pdf_doc = db.query(PDFDocument).filter(PDFDocument.id == pdf_id).first()
        if not pdf_doc:
            logger.warning(f"PDF not found in database: {pdf_id}")
            raise HTTPException(status_code=404, detail="PDF not found")

        if not os.path.exists(pdf_doc.file_path):
            logger.error(f"PDF file not found on disk: {pdf_doc.file_path}")
            raise HTTPException(status_code=404, detail="PDF file not found on disk")

        doc = None
        try:
            doc = fitz.open(pdf_doc.file_path)

            if request.page < 0 or request.page >= len(doc):
                logger.warning(f"Invalid page number {request.page} for PDF with {len(doc)} pages")
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid page number. PDF has {len(doc)} pages"
                )

            page = doc[request.page]

            # Log page dimensions for debugging
            page_rect = page.rect
            logger.info(f"Page dimensions: width={page_rect.width}, height={page_rect.height}")
            logger.info(f"Page mediabox: {page.mediabox}")

            # Create rectangle from coordinates
            rect = fitz.Rect(request.x0, request.y0, request.x1, request.y1)
            logger.info(f"Detection rect: {rect}")
            logger.info(f"Rect dimensions: width={rect.width}, height={rect.height}")

            # Validate rectangle
            if rect.width < 1 or rect.height < 1:
                logger.warning(f"Selection area too small: {rect.width}x{rect.height}")
                raise HTTPException(status_code=400, detail="Selection area too small")

            # Check if rect is within page bounds
            if rect.x1 > page_rect.width or rect.y1 > page_rect.height:
                logger.warning(f"Selection extends beyond page! Page: {page_rect.width}x{page_rect.height}, Selection end: ({rect.x1}, {rect.y1})")

            # Detect text
            detected_text, detection_source, lines_data = TextDetector.detect_text(page, rect)
            logger.info(f"=== DETECTION RESULT ===")
            logger.info(f"Source: {detection_source}")
            logger.info(f"Text: '{detected_text[:100] if detected_text else '(empty)'}...'")
            logger.info(f"Lines data count: {len(lines_data)}")

            return TextDetectionResponse(
                detected_text=detected_text,
                detection_source=detection_source,
                lines_data=[LineData(**ld) for ld in lines_data],
                rect=[request.x0, request.y0, request.x1, request.y1]
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error detecting text: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Error detecting text: {str(e)}")
        finally:
            if doc:
                doc.close()

    @staticmethod
    def delete_pdf(pdf_id: str, db: Session) -> bool:
        """
        Delete a PDF document and its file.

        Args:
            pdf_id: PDF document ID
            db: Database session

        Returns:
            True if deleted successfully
        """
        pdf_doc = db.query(PDFDocument).filter(PDFDocument.id == pdf_id).first()
        if not pdf_doc:
            raise HTTPException(status_code=404, detail="PDF not found")

        # Delete file from disk
        if os.path.exists(pdf_doc.file_path):
            try:
                os.remove(pdf_doc.file_path)
            except Exception:
                pass  # Continue even if file deletion fails

        # Delete database record (cascades to templates and placeholders)
        db.delete(pdf_doc)
        db.commit()

        return True

    @staticmethod
    def list_pdfs(db: Session, skip: int = 0, limit: int = 100):
        """
        List all uploaded PDF documents.

        Args:
            db: Database session
            skip: Number of records to skip
            limit: Maximum number of records to return

        Returns:
            List of PDF document metadata
        """
        logger.debug(f"Listing PDFs: skip={skip}, limit={limit}")
        pdfs = db.query(PDFDocument).offset(skip).limit(limit).all()

        return [
            {
                "id": pdf.id,
                "filename": pdf.filename,
                "original_filename": pdf.original_filename,
                "page_count": pdf.page_count,
                "file_size": pdf.file_size,
                "created_at": pdf.created_at,
                "exists_on_disk": os.path.exists(pdf.file_path)
            }
            for pdf in pdfs
        ]

    @staticmethod
    def get_pdf_path(pdf_id: str, db: Session) -> str:
        """Get the file path for a PDF document."""
        pdf_doc = db.query(PDFDocument).filter(PDFDocument.id == pdf_id).first()
        if not pdf_doc:
            raise HTTPException(status_code=404, detail="PDF not found")

        if not os.path.exists(pdf_doc.file_path):
            raise HTTPException(status_code=404, detail="PDF file not found on disk")

        return pdf_doc.file_path
