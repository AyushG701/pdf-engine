"""
Template Routes - Endpoints for template CRUD and document generation.
"""
import os
import logging
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime

from app.database import get_db
from app.services.template_service import TemplateService
from app.schemas.schemas import (
    TemplateCreate,
    TemplateResponse,
    TemplateListResponse,
    GenerateRequest,
    GenerateResponse,
    ApplyTemplateRequest,
    ApplyTemplateResponse
)

logger = logging.getLogger("pdf_editor.routes.template")

router = APIRouter(prefix="/template", tags=["Template"])


@router.post("/create", response_model=TemplateResponse)
def create_template(
    request: TemplateCreate,
    db: Session = Depends(get_db)
):
    """
    Create a new template with placeholders.

    A template defines a set of text areas (placeholders) in a PDF
    that can be replaced with new values to generate documents.

    Example request:
    ```json
    {
        "pdf_id": "abc123",
        "name": "Invoice Template",
        "placeholders": [
            {
                "label": "customer_name",
                "page": 0,
                "rect": [100, 200, 300, 250],
                "detected_text": "John Doe",
                "lines_data": [{"text": "John Doe", "baseline": 215.5, "size": 12}]
            }
        ]
    }
    ```
    """
    logger.info(f"Creating template: {request.name} with {len(request.placeholders)} placeholders")
    try:
        result = TemplateService.create_template(request, db)
        logger.info(f"Template created successfully: {result.id}")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating template: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create template: {str(e)}")


@router.get("/list", response_model=List[TemplateListResponse])
def list_templates(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db)
):
    """
    List all templates.

    Returns a lightweight list with template names and placeholder counts.
    Use GET /template/{id} for full details including placeholders.
    """
    logger.debug(f"Listing templates: skip={skip}, limit={limit}")
    try:
        return TemplateService.list_templates(db, skip=skip, limit=limit)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing templates: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list templates: {str(e)}")


@router.get("/{template_id}", response_model=TemplateResponse)
def get_template(
    template_id: str,
    db: Session = Depends(get_db)
):
    """
    Get a template by ID.

    Returns full template details including all placeholders
    with their positions and layout data.
    """
    logger.debug(f"Getting template: {template_id}")
    try:
        return TemplateService.get_template(template_id, db)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting template: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get template: {str(e)}")


@router.delete("/{template_id}")
def delete_template(
    template_id: str,
    db: Session = Depends(get_db)
):
    """
    Delete a template.

    This will delete the template and all its placeholders.
    The source PDF will not be deleted.
    """
    logger.info(f"Deleting template: {template_id}")
    try:
        TemplateService.delete_template(template_id, db)
        logger.info(f"Template deleted successfully: {template_id}")
        return {"message": "Template deleted successfully", "id": template_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting template: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete template: {str(e)}")


@router.post("/{template_id}/generate")
def generate_document(
    template_id: str,
    request: GenerateRequest,
    db: Session = Depends(get_db)
):
    """
    Generate a document by applying replacements to a template.

    Provide a map of placeholder labels to replacement values.
    All placeholders must have a replacement value.

    Example request:
    ```json
    {
        "replacements": {
            "customer_name": "Jane Smith",
            "invoice_date": "2025-01-15",
            "total_amount": "$1,234.56"
        },
        "output_filename": "invoice_jane_smith.pdf"
    }
    ```

    Returns the generated PDF file as a download.
    """
    logger.info(f"Generating document from template: {template_id}")
    try:
        output_path, filename, placeholders_replaced = TemplateService.generate_document(
            template_id, request, db
        )
        logger.info(f"Document generated: {filename} ({placeholders_replaced} placeholders replaced)")

        # Return file for download
        return FileResponse(
            path=output_path,
            filename=filename,
            media_type="application/pdf",
            headers={
                "X-Placeholders-Replaced": str(placeholders_replaced)
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating document: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to generate document: {str(e)}")


@router.post("/{template_id}/generate-json", response_model=GenerateResponse)
def generate_document_json(
    template_id: str,
    request: GenerateRequest,
    db: Session = Depends(get_db)
):
    """
    Generate a document and return metadata (not the file).

    Same as /generate but returns JSON with download URL instead
    of the actual file. Useful for async workflows.
    """
    logger.info(f"Generating document (JSON response) from template: {template_id}")
    try:
        output_path, filename, placeholders_replaced = TemplateService.generate_document(
            template_id, request, db
        )

        # Generate a download ID from the path
        download_id = os.path.basename(output_path).split('_')[0]

        logger.info(f"Document generated: {filename} (download_id: {download_id})")
        return GenerateResponse(
            id=download_id,
            filename=filename,
            download_url=f"/api/download/{download_id}",
            placeholders_replaced=placeholders_replaced,
            created_at=datetime.utcnow()
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating document: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to generate document: {str(e)}")


@router.post("/{template_id}/apply", response_model=ApplyTemplateResponse)
def apply_template_to_document(
    template_id: str,
    request: ApplyTemplateRequest,
    db: Session = Depends(get_db)
):
    """
    Apply a template to a different PDF document.

    This allows using placeholder positions defined in one PDF (template)
    to find and replace text in another PDF with the same structure.

    Use case: You have a template with placeholders defined on a sample document.
    When you receive a new document with the same layout, you can apply the
    template to detect and replace text at the same positions.

    Example request:
    ```json
    {
        "target_pdf_id": "new-pdf-id",
        "replacements": {
            "customer_name": "Jane Smith",
            "invoice_date": "2025-01-15"
        },
        "output_filename": "updated_invoice.pdf",
        "detect_and_replace": true
    }
    ```

    If `detect_and_replace` is true, the response includes `detected_values`
    showing what text was found at each placeholder position before replacement.
    """
    logger.info(f"Applying template {template_id} to PDF {request.target_pdf_id}")
    try:
        output_path, filename, placeholders_replaced, detected_values = TemplateService.apply_template_to_document(
            template_id, request, db
        )

        download_id = os.path.basename(output_path).split('_')[0]

        logger.info(f"Template applied: {filename} (download_id: {download_id})")
        return ApplyTemplateResponse(
            id=download_id,
            filename=filename,
            download_url=f"/api/download/{download_id}",
            placeholders_replaced=placeholders_replaced,
            detected_values=detected_values,
            created_at=datetime.utcnow()
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error applying template: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to apply template: {str(e)}")


@router.post("/{template_id}/detect")
def detect_text_at_template_positions(
    template_id: str,
    target_pdf_id: str = Query(..., description="ID of the PDF to detect text in"),
    db: Session = Depends(get_db)
):
    """
    Detect text at template placeholder positions in a different PDF.

    This is useful for previewing what text exists at template positions
    before applying replacements. Use this to verify the template aligns
    correctly with the target document.

    Returns a map of placeholder labels to detected text values.
    """
    logger.info(f"Detecting text at template {template_id} positions in PDF {target_pdf_id}")
    try:
        detected_values = TemplateService.detect_text_at_template_positions(
            template_id, target_pdf_id, db
        )
        return {
            "template_id": template_id,
            "target_pdf_id": target_pdf_id,
            "detected_values": detected_values
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error detecting text: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to detect text: {str(e)}")
