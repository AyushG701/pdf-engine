"""
PDF Routes - Endpoints for PDF upload, viewing, and text detection.
"""
import logging
from typing import Literal
from fastapi import APIRouter, Depends, UploadFile, File, Query, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.pdf_service import PDFService
from app.schemas.schemas import (
    PDFUploadResponse,
    PDFInfoResponse,
    PDFPageResponse,
    TextDetectionRequest,
    TextDetectionResponse
)

logger = logging.getLogger("pdf_editor.routes.pdf")

router = APIRouter(prefix="/pdf", tags=["PDF"])


@router.post("/upload", response_model=PDFUploadResponse)
async def upload_pdf(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Upload a PDF file.

    The file will be stored and can be used to create templates.
    Returns the document ID and metadata.
    """
    logger.info(f"Uploading PDF: {file.filename}")
    try:
        result = await PDFService.upload_pdf(file, db)
        logger.info(f"PDF uploaded successfully: {result.id}")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading PDF: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to upload PDF: {str(e)}")


@router.get("/list")
def list_pdfs(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db)
):
    """
    List all uploaded PDFs.

    Returns a list of uploaded PDF documents with their metadata.
    """
    logger.debug(f"Listing PDFs: skip={skip}, limit={limit}")
    try:
        return PDFService.list_pdfs(db, skip=skip, limit=limit)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing PDFs: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list PDFs: {str(e)}")


@router.get("/{pdf_id}/info", response_model=PDFInfoResponse)
def get_pdf_info(
    pdf_id: str,
    db: Session = Depends(get_db)
):
    """
    Get PDF document metadata.

    Returns page count, file size, and page dimensions.
    """
    logger.debug(f"Getting info for PDF: {pdf_id}")
    try:
        return PDFService.get_pdf_info(pdf_id, db)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting PDF info: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get PDF info: {str(e)}")


@router.get("/{pdf_id}/page/{page_num}")
def get_page_image(
    pdf_id: str,
    page_num: int,
    zoom: float = Query(default=1.5, ge=0.25, le=5.0),
    format: Literal["base64", "binary"] = Query(default="base64"),
    db: Session = Depends(get_db)
):
    """
    Get a PDF page as an image.

    Args:
        pdf_id: PDF document ID
        page_num: Page number (0-indexed)
        zoom: Zoom factor (0.25 to 5.0)
        format: Response format - "base64" (JSON) or "binary" (PNG)

    Returns:
        If format=base64: JSON with base64 image data
        If format=binary: Raw PNG image
    """
    logger.debug(f"Getting page {page_num} for PDF: {pdf_id}, zoom: {zoom}, format: {format}")
    try:
        as_base64 = format == "base64"
        img_data, total_pages, page_number, width, height = PDFService.get_page_image(
            pdf_id, page_num, db, zoom=zoom, as_base64=as_base64
        )

        if as_base64:
            return PDFPageResponse(
                page_number=page_number,
                total_pages=total_pages,
                width=width,
                height=height,
                image_base64=img_data
            )
        else:
            return Response(
                content=img_data,
                media_type="image/png",
                headers={
                    "X-Page-Number": str(page_number),
                    "X-Total-Pages": str(total_pages),
                    "X-Width": str(width),
                    "X-Height": str(height)
                }
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting page image: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to render page: {str(e)}")


@router.post("/{pdf_id}/detect-text", response_model=TextDetectionResponse)
def detect_text(
    pdf_id: str,
    request: TextDetectionRequest,
    db: Session = Depends(get_db)
):
    """
    Detect text within a selected area of a PDF page.

    Send the coordinates of a rectangle selection to extract text.
    The response includes the detected text, detection method used,
    and line layout data for precise replacement.

    Coordinates should be in PDF points (not pixels).
    To convert from screen pixels: pdf_coord = pixel_coord / zoom_level
    """
    logger.debug(f"Detecting text in PDF: {pdf_id}, page: {request.page}, rect: [{request.x0}, {request.y0}, {request.x1}, {request.y1}]")
    try:
        result = PDFService.detect_text_in_area(pdf_id, request, db)
        logger.debug(f"Text detected: '{result.detected_text[:50]}...' via {result.detection_source}" if result.detected_text else "No text detected")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error detecting text: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to detect text: {str(e)}")


@router.delete("/{pdf_id}")
def delete_pdf(
    pdf_id: str,
    db: Session = Depends(get_db)
):
    """
    Delete a PDF document.

    This will also delete all associated templates and placeholders.
    """
    logger.info(f"Deleting PDF: {pdf_id}")
    try:
        PDFService.delete_pdf(pdf_id, db)
        logger.info(f"PDF deleted successfully: {pdf_id}")
        return {"message": "PDF deleted successfully", "id": pdf_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting PDF: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete PDF: {str(e)}")


@router.get("/{pdf_id}/debug-text/{page_num}")
def debug_page_text(
    pdf_id: str,
    page_num: int,
    db: Session = Depends(get_db)
):
    """
    Debug endpoint: Get all text on a page with coordinates.
    Useful for understanding PDF structure and coordinate system.
    """
    import fitz
    from app.models.models import PDFDocument
    import os

    pdf_doc = db.query(PDFDocument).filter(PDFDocument.id == pdf_id).first()
    if not pdf_doc:
        raise HTTPException(status_code=404, detail="PDF not found")

    if not os.path.exists(pdf_doc.file_path):
        raise HTTPException(status_code=404, detail="PDF file not found on disk")

    doc = None
    try:
        doc = fitz.open(pdf_doc.file_path)

        if page_num < 0 or page_num >= len(doc):
            raise HTTPException(status_code=400, detail=f"Invalid page number. PDF has {len(doc)} pages")

        page = doc[page_num]

        # Get page info
        page_rect = page.rect
        page_info = {
            "width": page_rect.width,
            "height": page_rect.height,
            "mediabox": [page.mediabox.x0, page.mediabox.y0, page.mediabox.x1, page.mediabox.y1],
        }

        # Get all words on the page
        words = page.get_text("words")
        word_list = []
        for w in words[:100]:  # Limit to first 100 words
            word_list.append({
                "text": w[4],
                "x0": round(w[0], 2),
                "y0": round(w[1], 2),
                "x1": round(w[2], 2),
                "y1": round(w[3], 2),
            })

        # Get all text blocks
        blocks = page.get_text("dict")["blocks"]
        block_list = []
        for i, block in enumerate(blocks[:20]):  # Limit to first 20 blocks
            if block.get("type") == 0:  # Text block
                block_text = ""
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        block_text += span.get("text", "") + " "
                block_list.append({
                    "index": i,
                    "bbox": [round(block["bbox"][j], 2) for j in range(4)],
                    "text_preview": block_text[:100].strip(),
                })

        # Check for form fields/widgets
        widgets = list(page.widgets())
        widget_list = []
        for w in widgets[:20]:
            widget_list.append({
                "field_name": w.field_name,
                "field_value": str(w.field_value) if w.field_value else None,
                "rect": [round(w.rect.x0, 2), round(w.rect.y0, 2), round(w.rect.x1, 2), round(w.rect.y1, 2)],
            })

        return {
            "page_info": page_info,
            "total_words": len(words),
            "sample_words": word_list,
            "total_blocks": len(blocks),
            "sample_blocks": block_list,
            "total_widgets": len(widgets),
            "sample_widgets": widget_list,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in debug-text: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if doc:
            doc.close()
