"""
Template Service - Handles template CRUD and document generation.
"""
import fitz  # PyMuPDF
import os
import uuid
import logging
from datetime import datetime
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException

from app.config import settings
from app.models.models import PDFDocument, Template, Placeholder
from app.schemas.schemas import (
    TemplateCreate,
    TemplateResponse,
    TemplateListResponse,
    PlaceholderResponse,
    GenerateRequest,
    GenerateResponse,
    ApplyTemplateRequest,
    ApplyTemplateResponse
)
from app.utils.text_detection import measure_text_width, TextDetector

logger = logging.getLogger("pdf_editor.services.template")


class TemplateService:
    """Service for template operations and document generation."""

    @staticmethod
    def create_template(request: TemplateCreate, db: Session) -> TemplateResponse:
        """
        Create a new template with placeholders.

        Args:
            request: Template creation request
            db: Database session

        Returns:
            TemplateResponse with full template details
        """
        # Verify PDF exists
        pdf_doc = db.query(PDFDocument).filter(PDFDocument.id == request.pdf_id).first()
        if not pdf_doc:
            raise HTTPException(status_code=404, detail="PDF not found")

        # Validate placeholder labels are unique
        labels = [p.label for p in request.placeholders]
        if len(labels) != len(set(labels)):
            raise HTTPException(status_code=400, detail="Placeholder labels must be unique")

        # Create template
        template = Template(
            id=str(uuid.uuid4()),
            name=request.name,
            description=request.description,
            pdf_id=request.pdf_id
        )
        db.add(template)

        # Create placeholders
        for p in request.placeholders:
            placeholder = Placeholder(
                id=str(uuid.uuid4()),
                template_id=template.id,
                label=p.label,
                page=p.page,
                x0=p.rect[0],
                y0=p.rect[1],
                x1=p.rect[2],
                y1=p.rect[3],
                detected_text=p.detected_text,
                detection_source=p.detection_source,
                lines_data=[ld.model_dump() for ld in p.lines_data] if p.lines_data else None,
                strict_match=1 if p.strict_match else 0
            )
            db.add(placeholder)

        db.commit()
        db.refresh(template)

        return TemplateService._template_to_response(template, pdf_doc.original_filename)

    @staticmethod
    def get_template(template_id: str, db: Session) -> TemplateResponse:
        """Get a template by ID."""
        template = db.query(Template).filter(Template.id == template_id).first()
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")

        pdf_filename = template.pdf_document.original_filename if template.pdf_document else None
        return TemplateService._template_to_response(template, pdf_filename)

    @staticmethod
    def list_templates(db: Session, skip: int = 0, limit: int = 100) -> List[TemplateListResponse]:
        """List all templates."""
        templates = db.query(Template).offset(skip).limit(limit).all()

        return [
            TemplateListResponse(
                id=t.id,
                name=t.name,
                description=t.description,
                pdf_id=t.pdf_id,
                pdf_filename=t.pdf_document.original_filename if t.pdf_document else None,
                placeholder_count=len(t.placeholders),
                created_at=t.created_at
            )
            for t in templates
        ]

    @staticmethod
    def delete_template(template_id: str, db: Session) -> bool:
        """Delete a template."""
        template = db.query(Template).filter(Template.id == template_id).first()
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")

        db.delete(template)
        db.commit()
        return True

    @staticmethod
    def generate_document(
        template_id: str,
        request: GenerateRequest,
        db: Session
    ) -> tuple:
        """
        Generate a document by applying replacements to a template.

        Args:
            template_id: Template ID
            request: Generation request with replacements
            db: Database session

        Returns:
            Tuple of (file_path, filename, placeholders_replaced)
        """
        logger.info(f"Generating document from template: {template_id}")

        # Get template with placeholders
        template = db.query(Template).filter(Template.id == template_id).first()
        if not template:
            logger.warning(f"Template not found: {template_id}")
            raise HTTPException(status_code=404, detail="Template not found")

        # Verify PDF exists
        pdf_doc = template.pdf_document
        if not pdf_doc:
            logger.error(f"Template PDF document record not found for template: {template_id}")
            raise HTTPException(status_code=404, detail="Template PDF not found")

        if not os.path.exists(pdf_doc.file_path):
            logger.error(f"Template PDF file not found on disk: {pdf_doc.file_path}")
            raise HTTPException(status_code=404, detail="Template PDF file not found on disk")

        # Validate all placeholders have replacement values
        placeholder_labels = {p.label for p in template.placeholders}
        missing = placeholder_labels - set(request.replacements.keys())
        if missing:
            logger.warning(f"Missing replacement values for: {missing}")
            raise HTTPException(
                status_code=400,
                detail=f"Missing replacement values for: {', '.join(missing)}"
            )

        # Generate output filename
        output_id = str(uuid.uuid4())
        output_filename = request.output_filename or f"generated_{output_id}.pdf"
        if not output_filename.lower().endswith('.pdf'):
            output_filename += '.pdf'
        output_path = os.path.join(settings.GENERATED_DIR, f"{output_id}_{output_filename}")

        doc = None
        try:
            # Open source PDF
            logger.debug(f"Opening source PDF: {pdf_doc.file_path}")
            doc = fitz.open(pdf_doc.file_path)

            placeholders_replaced = 0

            # Apply each placeholder replacement
            for placeholder in template.placeholders:
                new_text = request.replacements.get(placeholder.label, "")
                if not new_text:
                    logger.debug(f"Skipping placeholder {placeholder.label}: empty replacement")
                    continue

                logger.debug(f"Replacing placeholder '{placeholder.label}' on page {placeholder.page}")

                page = doc[placeholder.page]
                rect = fitz.Rect(placeholder.x0, placeholder.y0, placeholder.x1, placeholder.y1)

                # Clean the area
                clean_rect = fitz.Rect(
                    rect.x0 - 2,
                    rect.y0 - 2,
                    rect.x1 + 2,
                    rect.y1 + 2
                )

                # Delete any widgets in the area
                widgets_to_delete = []
                for widget in page.widgets():
                    if widget.rect.intersects(clean_rect):
                        widgets_to_delete.append(widget)

                for widget in widgets_to_delete:
                    try:
                        page.delete_widget(widget)
                        logger.debug(f"Deleted widget in area: {widget.rect}")
                    except Exception as e:
                        logger.warning(f"Failed to delete widget: {e}")

                # Use redaction for thorough cleaning (matches GUI behavior)
                try:
                    page.add_redact_annot(clean_rect, fill=(1, 1, 1), text="")
                    page.apply_redactions()
                    logger.debug(f"Applied redaction to clean area: {clean_rect}")
                except Exception as e:
                    logger.warning(f"Redaction failed, using draw_rect fallback: {e}")
                    # Fallback: Draw white rectangle to cover existing content
                    page.draw_rect(clean_rect, color=(1, 1, 1), fill=(1, 1, 1), width=0)

                # Insert new text
                TemplateService._insert_text(
                    page=page,
                    rect=rect,
                    new_text=new_text,
                    lines_data=placeholder.lines_data,
                    strict_match=bool(placeholder.strict_match)
                )

                placeholders_replaced += 1

            # Save output with optimizations
            logger.info(f"Saving generated document to: {output_path}")
            doc.save(output_path, garbage=4, deflate=True, clean=True)

            logger.info(f"Document generated successfully: {placeholders_replaced} placeholders replaced")
            return output_path, output_filename, placeholders_replaced

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error generating document: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Error generating document: {str(e)}")
        finally:
            if doc:
                doc.close()

    @staticmethod
    def _insert_text(
        page: fitz.Page,
        rect: fitz.Rect,
        new_text: str,
        lines_data: Optional[List[Dict]],
        strict_match: bool
    ):
        """
        Insert text into a page area, matching original layout if possible.

        Args:
            page: PyMuPDF page object
            rect: Rectangle area for text
            new_text: Text to insert
            lines_data: Original line layout data
            strict_match: If True, match original line positions
        """
        new_lines = new_text.split('\n')
        lines_data = lines_data or []
        box_width = rect.x1 - rect.x0
        box_height = rect.y1 - rect.y0

        logger.debug(f"Inserting text: '{new_text[:30]}...' into rect {rect}, {len(new_lines)} lines")

        for i, line_text in enumerate(new_lines):
            line_text = line_text.strip()
            if not line_text:
                continue

            # Calculate Y position and font size
            fontsize = 10  # default
            baseline_y = rect.y0 + 12  # default

            if strict_match and i < len(lines_data) and lines_data[i]:
                # Use original baseline
                baseline_y = lines_data[i].get('baseline', rect.y0 + 12)
                fontsize = lines_data[i].get('size', 10)
                logger.debug(f"Line {i}: using original baseline={baseline_y}, size={fontsize}")
            else:
                # Calculate position for extra/all lines
                if lines_data and len(lines_data) > 0:
                    # Deduce line height from existing lines
                    if len(lines_data) > 1:
                        first_baseline = lines_data[0].get('baseline', rect.y0)
                        last_baseline = lines_data[-1].get('baseline', rect.y1)
                        avg_height = (last_baseline - first_baseline) / (len(lines_data) - 1)
                    else:
                        avg_height = lines_data[0].get('size', 12) * 1.2

                    if avg_height <= 0:
                        avg_height = 12

                    if i < len(lines_data):
                        baseline_y = lines_data[i].get('baseline', rect.y0 + (i + 1) * avg_height)
                    else:
                        last_baseline = lines_data[-1].get('baseline', rect.y0)
                        baseline_y = last_baseline + (avg_height * (i - len(lines_data) + 1))

                    fontsize = lines_data[0].get('size', 10)
                else:
                    # No line data - distribute evenly
                    num_lines = max(len(new_lines), 1)
                    h = box_height / num_lines
                    baseline_y = rect.y0 + ((i + 0.8) * h)
                    fontsize = min(h * 0.75, 12)  # Cap at 12pt

            # Ensure fontsize is reasonable
            fontsize = max(6, min(fontsize, 14))

            # Auto-fit text width by reducing font size if needed
            original_fontsize = fontsize
            while fontsize > 4:
                text_len = measure_text_width(line_text, "helv", fontsize)
                if text_len < (box_width - 4):
                    break
                fontsize -= 0.5

            if fontsize != original_fontsize:
                logger.debug(f"Line {i}: reduced fontsize from {original_fontsize} to {fontsize} to fit width")

            # Insert the text
            try:
                page.insert_text(
                    (rect.x0 + 1, baseline_y),
                    line_text,
                    fontname="helv",
                    fontsize=fontsize,
                    color=(0, 0, 0)
                )
                logger.debug(f"Line {i}: inserted '{line_text[:20]}...' at ({rect.x0 + 1}, {baseline_y})")
            except Exception as e:
                logger.error(f"Failed to insert text line {i}: {e}")

    @staticmethod
    def _template_to_response(template: Template, pdf_filename: Optional[str]) -> TemplateResponse:
        """Convert Template model to TemplateResponse."""
        placeholders = []
        for p in template.placeholders:
            placeholders.append(PlaceholderResponse(
                id=p.id,
                label=p.label,
                page=p.page,
                rect=[p.x0, p.y0, p.x1, p.y1],
                detected_text=p.detected_text,
                detection_source=p.detection_source,
                lines_data=p.lines_data,
                strict_match=bool(p.strict_match),
                created_at=p.created_at
            ))

        return TemplateResponse(
            id=template.id,
            name=template.name,
            description=template.description,
            pdf_id=template.pdf_id,
            pdf_filename=pdf_filename,
            placeholders=placeholders,
            created_at=template.created_at,
            updated_at=template.updated_at
        )

    @staticmethod
    def apply_template_to_document(
        template_id: str,
        request: ApplyTemplateRequest,
        db: Session
    ) -> tuple:
        """
        Apply a template to a different PDF document.

        This allows using placeholder positions from one document (template)
        to find and replace text in another document with the same structure.

        Args:
            template_id: Template ID to use
            request: Apply template request with target PDF and replacements
            db: Database session

        Returns:
            Tuple of (file_path, filename, placeholders_replaced, detected_values)
        """
        logger.info(f"Applying template {template_id} to PDF {request.target_pdf_id}")

        # Get template with placeholders
        template = db.query(Template).filter(Template.id == template_id).first()
        if not template:
            logger.warning(f"Template not found: {template_id}")
            raise HTTPException(status_code=404, detail="Template not found")

        # Verify target PDF exists
        target_pdf = db.query(PDFDocument).filter(PDFDocument.id == request.target_pdf_id).first()
        if not target_pdf:
            logger.warning(f"Target PDF not found: {request.target_pdf_id}")
            raise HTTPException(status_code=404, detail="Target PDF not found")

        if not os.path.exists(target_pdf.file_path):
            logger.error(f"Target PDF file not found on disk: {target_pdf.file_path}")
            raise HTTPException(status_code=404, detail="Target PDF file not found on disk")

        # Validate all placeholders have replacement values
        placeholder_labels = {p.label for p in template.placeholders}
        missing = placeholder_labels - set(request.replacements.keys())
        if missing:
            logger.warning(f"Missing replacement values for: {missing}")
            raise HTTPException(
                status_code=400,
                detail=f"Missing replacement values for: {', '.join(missing)}"
            )

        # Generate output filename
        output_id = str(uuid.uuid4())
        output_filename = request.output_filename or f"applied_{output_id}.pdf"
        if not output_filename.lower().endswith('.pdf'):
            output_filename += '.pdf'
        output_path = os.path.join(settings.GENERATED_DIR, f"{output_id}_{output_filename}")

        doc = None
        detected_values = {}

        try:
            # Open target PDF
            logger.debug(f"Opening target PDF: {target_pdf.file_path}")
            doc = fitz.open(target_pdf.file_path)

            placeholders_replaced = 0

            # Apply each placeholder replacement
            for placeholder in template.placeholders:
                new_text = request.replacements.get(placeholder.label, "")

                # Check if page exists in target document
                if placeholder.page >= len(doc):
                    logger.warning(f"Page {placeholder.page} doesn't exist in target PDF (has {len(doc)} pages)")
                    continue

                page = doc[placeholder.page]
                rect = fitz.Rect(placeholder.x0, placeholder.y0, placeholder.x1, placeholder.y1)

                # Optionally detect text at this position first
                if request.detect_and_replace:
                    detected_text, detection_source, lines_data = TextDetector.detect_text(page, rect)
                    detected_values[placeholder.label] = detected_text
                    logger.debug(f"Detected text at {placeholder.label}: '{detected_text[:50] if detected_text else 'empty'}...'")

                if not new_text:
                    logger.debug(f"Skipping placeholder {placeholder.label}: empty replacement")
                    continue

                logger.debug(f"Replacing placeholder '{placeholder.label}' on page {placeholder.page}")

                # Clean the area
                clean_rect = fitz.Rect(
                    rect.x0 - 2,
                    rect.y0 - 2,
                    rect.x1 + 2,
                    rect.y1 + 2
                )

                # Delete any widgets in the area
                widgets_to_delete = []
                for widget in page.widgets():
                    if widget.rect.intersects(clean_rect):
                        widgets_to_delete.append(widget)

                for widget in widgets_to_delete:
                    try:
                        page.delete_widget(widget)
                        logger.debug(f"Deleted widget in area: {widget.rect}")
                    except Exception as e:
                        logger.warning(f"Failed to delete widget: {e}")

                # Use redaction for thorough cleaning
                try:
                    page.add_redact_annot(clean_rect, fill=(1, 1, 1), text="")
                    page.apply_redactions()
                    logger.debug(f"Applied redaction to clean area: {clean_rect}")
                except Exception as e:
                    logger.warning(f"Redaction failed, using draw_rect fallback: {e}")
                    page.draw_rect(clean_rect, color=(1, 1, 1), fill=(1, 1, 1), width=0)

                # Insert new text using the template's lines_data for positioning
                TemplateService._insert_text(
                    page=page,
                    rect=rect,
                    new_text=new_text,
                    lines_data=placeholder.lines_data,
                    strict_match=bool(placeholder.strict_match)
                )

                placeholders_replaced += 1

            # Save output with optimizations
            logger.info(f"Saving generated document to: {output_path}")
            doc.save(output_path, garbage=4, deflate=True, clean=True)

            logger.info(f"Template applied successfully: {placeholders_replaced} placeholders replaced")
            return output_path, output_filename, placeholders_replaced, detected_values if request.detect_and_replace else None

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error applying template: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Error applying template: {str(e)}")
        finally:
            if doc:
                doc.close()

    @staticmethod
    def detect_text_at_template_positions(
        template_id: str,
        target_pdf_id: str,
        db: Session
    ) -> Dict[str, str]:
        """
        Detect text at template placeholder positions in a target PDF.

        This is useful for previewing what text exists at template positions
        before applying replacements.

        Args:
            template_id: Template ID
            target_pdf_id: Target PDF ID
            db: Database session

        Returns:
            Dict mapping placeholder labels to detected text
        """
        logger.info(f"Detecting text at template {template_id} positions in PDF {target_pdf_id}")

        # Get template with placeholders
        template = db.query(Template).filter(Template.id == template_id).first()
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")

        # Get target PDF
        target_pdf = db.query(PDFDocument).filter(PDFDocument.id == target_pdf_id).first()
        if not target_pdf:
            raise HTTPException(status_code=404, detail="Target PDF not found")

        if not os.path.exists(target_pdf.file_path):
            raise HTTPException(status_code=404, detail="Target PDF file not found on disk")

        doc = None
        detected_values = {}

        try:
            doc = fitz.open(target_pdf.file_path)

            for placeholder in template.placeholders:
                if placeholder.page >= len(doc):
                    detected_values[placeholder.label] = f"[Page {placeholder.page} not found]"
                    continue

                page = doc[placeholder.page]
                rect = fitz.Rect(placeholder.x0, placeholder.y0, placeholder.x1, placeholder.y1)

                detected_text, detection_source, lines_data = TextDetector.detect_text(page, rect)
                detected_values[placeholder.label] = detected_text

            return detected_values

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error detecting text: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Error detecting text: {str(e)}")
        finally:
            if doc:
                doc.close()
