"""
Template Service - Handles template CRUD and document generation.
"""
import fitz  # PyMuPDF
import os
import io
import base64
import uuid
import logging
from datetime import datetime
from typing import List, Dict, Optional, Union
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
    ApplyTemplateResponse,
    PlaceholderStyle,
    ReplacementValue,
    ContentType
)
from app.utils.text_detection import measure_text_width, TextDetector

logger = logging.getLogger("pdf_editor.services.template")


def hex_to_rgb(hex_color: str) -> tuple:
    """Convert hex color string to RGB tuple (0-1 range)."""
    hex_color = hex_color.lstrip('#')
    if len(hex_color) == 3:
        hex_color = ''.join([c*2 for c in hex_color])
    r = int(hex_color[0:2], 16) / 255.0
    g = int(hex_color[2:4], 16) / 255.0
    b = int(hex_color[4:6], 16) / 255.0
    return (r, g, b)


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
            # Determine if multi-line based on detected text
            is_multi_line = p.multi_line
            if not is_multi_line and p.detected_text:
                is_multi_line = '\n' in p.detected_text

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
                strict_match=1 if p.strict_match else 0,
                content_type=p.content_type.value if p.content_type else "text",
                multi_line=1 if is_multi_line else 0,
                style=p.style.model_dump() if p.style else None
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
    def update_template(template_id: str, request, db: Session):
        """
        Update a template and its placeholders.

        Args:
            template_id: Template ID
            request: TemplateUpdate request
            db: Database session

        Returns:
            Updated TemplateResponse
        """
        from app.schemas.schemas import TemplateUpdate

        logger.info(f"Updating template: {template_id}")

        template = db.query(Template).filter(Template.id == template_id).first()
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")

        # Update template fields
        if request.name is not None:
            template.name = request.name
        if request.description is not None:
            template.description = request.description

        # Remove placeholders
        if request.remove_placeholder_ids:
            for ph_id in request.remove_placeholder_ids:
                placeholder = db.query(Placeholder).filter(
                    Placeholder.id == ph_id,
                    Placeholder.template_id == template_id
                ).first()
                if placeholder:
                    db.delete(placeholder)
                    logger.debug(f"Removed placeholder: {ph_id}")

        # Update existing placeholders
        if request.placeholders:
            for p_update in request.placeholders:
                placeholder = db.query(Placeholder).filter(
                    Placeholder.id == p_update.id,
                    Placeholder.template_id == template_id
                ).first()
                if not placeholder:
                    logger.warning(f"Placeholder not found for update: {p_update.id}")
                    continue

                if p_update.label is not None:
                    placeholder.label = p_update.label
                if p_update.rect is not None:
                    placeholder.x0 = p_update.rect[0]
                    placeholder.y0 = p_update.rect[1]
                    placeholder.x1 = p_update.rect[2]
                    placeholder.y1 = p_update.rect[3]
                if p_update.detected_text is not None:
                    placeholder.detected_text = p_update.detected_text
                if p_update.lines_data is not None:
                    placeholder.lines_data = [ld.model_dump() for ld in p_update.lines_data]
                if p_update.strict_match is not None:
                    placeholder.strict_match = 1 if p_update.strict_match else 0
                if p_update.content_type is not None:
                    placeholder.content_type = p_update.content_type.value
                if p_update.style is not None:
                    placeholder.style = p_update.style.model_dump()
                if p_update.multi_line is not None:
                    placeholder.multi_line = 1 if p_update.multi_line else 0

                logger.debug(f"Updated placeholder: {p_update.id}")

        # Add new placeholders
        if request.add_placeholders:
            for p in request.add_placeholders:
                is_multi_line = p.multi_line
                if not is_multi_line and p.detected_text:
                    is_multi_line = '\n' in p.detected_text

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
                    strict_match=1 if p.strict_match else 0,
                    content_type=p.content_type.value if p.content_type else "text",
                    multi_line=1 if is_multi_line else 0,
                    style=p.style.model_dump() if p.style else None
                )
                db.add(placeholder)
                logger.debug(f"Added placeholder: {p.label}")

        db.commit()
        db.refresh(template)

        pdf_filename = template.pdf_document.original_filename if template.pdf_document else None
        return TemplateService._template_to_response(template, pdf_filename)

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
                replacement = request.replacements.get(placeholder.label)
                if not replacement:
                    logger.debug(f"Skipping placeholder {placeholder.label}: empty replacement")
                    continue

                # Handle both string and ReplacementValue formats
                if isinstance(replacement, str):
                    replacement_value = replacement
                    replacement_content_type = ContentType.TEXT
                    replacement_style = None
                elif isinstance(replacement, dict):
                    # Already a dict (from JSON)
                    replacement_value = replacement.get('value', '')
                    replacement_content_type = ContentType(replacement.get('content_type', 'text'))
                    replacement_style = replacement.get('style')
                else:
                    # ReplacementValue object
                    replacement_value = replacement.value
                    replacement_content_type = replacement.content_type
                    replacement_style = replacement.style.model_dump() if replacement.style else None

                if not replacement_value:
                    logger.debug(f"Skipping placeholder {placeholder.label}: empty value")
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

                # Merge styles: replacement style overrides placeholder default style
                effective_style = placeholder.style.copy() if placeholder.style else {}
                if replacement_style:
                    effective_style.update(replacement_style)

                # Get background color for redaction (default white)
                bg_color_hex = effective_style.get('background_color', '#FFFFFF')
                bg_rgb = hex_to_rgb(bg_color_hex)
                bg_opacity = effective_style.get('background_opacity', 1.0)

                # Calculate background rect size (can be custom or auto)
                bg_width = effective_style.get('background_width')
                bg_height = effective_style.get('background_height')
                if bg_width and bg_height:
                    # Custom background size
                    bg_rect = fitz.Rect(
                        rect.x0,
                        rect.y0,
                        rect.x0 + bg_width,
                        rect.y0 + bg_height
                    )
                else:
                    # Auto size - use clean_rect
                    bg_rect = clean_rect

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

                # Use redaction for thorough cleaning with custom background color
                try:
                    page.add_redact_annot(clean_rect, fill=bg_rgb, text="")
                    page.apply_redactions()
                    logger.debug(f"Applied redaction with color {bg_color_hex} to area: {clean_rect}")
                except Exception as e:
                    logger.warning(f"Redaction failed, using draw_rect fallback: {e}")
                    # Fallback: Draw rectangle with custom color
                    page.draw_rect(clean_rect, color=bg_rgb, fill=bg_rgb, width=0)

                # If custom background size, draw additional background rect
                if bg_width or bg_height:
                    try:
                        shape = page.new_shape()
                        shape.draw_rect(bg_rect)
                        shape.finish(fill=bg_rgb, fill_opacity=bg_opacity, color=None)
                        shape.commit()
                        logger.debug(f"Drew custom background: {bg_rect}")
                    except Exception as e:
                        logger.warning(f"Custom background failed: {e}")

                # Insert content based on type
                if replacement_content_type == ContentType.IMAGE:
                    TemplateService._insert_image(
                        page=page,
                        rect=rect,
                        image_data=replacement_value,
                        style=effective_style
                    )
                else:
                    TemplateService._insert_text(
                        page=page,
                        rect=rect,
                        new_text=replacement_value,
                        lines_data=placeholder.lines_data,
                        strict_match=bool(placeholder.strict_match),
                        style=effective_style
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
        strict_match: bool,
        style: Optional[Dict] = None
    ):
        """
        Insert text into a page area, matching original layout if possible.

        Args:
            page: PyMuPDF page object
            rect: Rectangle area for text
            new_text: Text to insert
            lines_data: Original line layout data
            strict_match: If True, match original line positions
            style: Optional styling options
        """
        new_lines = new_text.split('\n')
        lines_data = lines_data or []
        box_width = rect.x1 - rect.x0
        box_height = rect.y1 - rect.y0

        # Extract styling options with defaults
        style = style or {}
        style_fontsize = style.get('font_size')  # None means auto-calculate
        style_fontname = style.get('font_name', 'helv')
        style_fontweight = style.get('font_weight', 'normal')
        style_color = hex_to_rgb(style.get('color', '#000000'))
        style_padding = style.get('padding', 1.0)

        # Map font name for bold variant
        fontname = style_fontname
        if style_fontweight == 'bold':
            font_mapping = {
                'helv': 'hebo',  # Helvetica Bold
                'times-roman': 'tibo',  # Times Bold
                'courier': 'cobo',  # Courier Bold
            }
            fontname = font_mapping.get(style_fontname, style_fontname)

        logger.debug(f"Inserting text: '{new_text[:30]}...' into rect {rect}, {len(new_lines)} lines")

        # Note: Background is drawn in generate_document before this is called

        for i, line_text in enumerate(new_lines):
            line_text = line_text.strip()
            if not line_text:
                continue

            # Calculate Y position and font size
            fontsize = style_fontsize or 10  # default
            baseline_y = rect.y0 + 12  # default

            if strict_match and i < len(lines_data) and lines_data[i]:
                # Use original baseline and y0/y1 positions
                line_data = lines_data[i]
                baseline_y = line_data.get('baseline', rect.y0 + 12)

                # If style doesn't override font size, use detected size
                if not style_fontsize:
                    fontsize = line_data.get('size', 10)

                logger.debug(f"Line {i}: using original baseline={baseline_y}, size={fontsize}")
            else:
                # Calculate position for extra/all lines
                if lines_data and len(lines_data) > 0:
                    # Deduce line height from existing lines using y0/y1 if available
                    if len(lines_data) > 1:
                        # Try to use y0/y1 for more accurate spacing
                        first_y0 = lines_data[0].get('y0', lines_data[0].get('baseline', rect.y0) - 10)
                        last_y1 = lines_data[-1].get('y1', lines_data[-1].get('baseline', rect.y1))
                        total_height = last_y1 - first_y0
                        avg_height = total_height / len(lines_data)
                    else:
                        avg_height = lines_data[0].get('size', 12) * 1.2

                    if avg_height <= 0:
                        avg_height = 12

                    if i < len(lines_data):
                        baseline_y = lines_data[i].get('baseline', rect.y0 + (i + 1) * avg_height)
                    else:
                        last_baseline = lines_data[-1].get('baseline', rect.y0)
                        baseline_y = last_baseline + (avg_height * (i - len(lines_data) + 1))

                    if not style_fontsize:
                        fontsize = lines_data[0].get('size', 10)
                else:
                    # No line data - distribute evenly
                    num_lines = max(len(new_lines), 1)
                    h = box_height / num_lines
                    baseline_y = rect.y0 + ((i + 0.8) * h)
                    if not style_fontsize:
                        fontsize = min(h * 0.75, 12)  # Cap at 12pt

            # Ensure fontsize is reasonable (allow up to 72pt if style specifies)
            max_font = style_fontsize if style_fontsize and style_fontsize > 14 else 72
            fontsize = max(4, min(fontsize, max_font))

            # Auto-fit text width by reducing font size if needed
            original_fontsize = fontsize
            while fontsize > 4:
                text_len = measure_text_width(line_text, fontname, fontsize)
                if text_len < (box_width - style_padding * 2):
                    break
                fontsize -= 0.5

            if fontsize != original_fontsize:
                logger.debug(f"Line {i}: reduced fontsize from {original_fontsize} to {fontsize} to fit width")

            # Insert the text
            try:
                # Note: PyMuPDF doesn't directly support text opacity, but we can use overlay
                page.insert_text(
                    (rect.x0 + style_padding, baseline_y),
                    line_text,
                    fontname=fontname,
                    fontsize=fontsize,
                    color=style_color,
                    overlay=True
                )
                logger.debug(f"Line {i}: inserted '{line_text[:20]}...' at ({rect.x0 + style_padding}, {baseline_y})")
            except Exception as e:
                logger.error(f"Failed to insert text line {i}: {e}")

    @staticmethod
    def _insert_image(
        page: fitz.Page,
        rect: fitz.Rect,
        image_data: str,
        style: Optional[Dict] = None
    ):
        """
        Insert an image into a page area.

        Args:
            page: PyMuPDF page object
            rect: Rectangle area for image
            image_data: Base64 encoded image data
            style: Optional styling options (for background)
        """
        style = style or {}
        style_bg_color = style.get('background_color')
        style_bg_opacity = style.get('background_opacity', 1.0)

        logger.debug(f"Inserting image into rect {rect}")

        try:
            # Draw background if specified
            if style_bg_color and style_bg_opacity > 0:
                bg_rgb = hex_to_rgb(style_bg_color)
                page.draw_rect(rect, color=bg_rgb, fill=bg_rgb, width=0)

            # Decode base64 image
            # Remove data URL prefix if present
            if ',' in image_data:
                image_data = image_data.split(',')[1]

            image_bytes = base64.b64decode(image_data)

            # Insert image into the rectangle
            page.insert_image(rect, stream=image_bytes, keep_proportion=True)
            logger.debug(f"Image inserted successfully into {rect}")

        except Exception as e:
            logger.error(f"Failed to insert image: {e}")

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
                content_type=ContentType(p.content_type) if p.content_type else ContentType.TEXT,
                style=p.style,
                multi_line=bool(p.multi_line),
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

                # Get style from placeholder (if any)
                effective_style = placeholder.style.copy() if placeholder.style else {}

                # Get background color for redaction (default white)
                bg_color_hex = effective_style.get('background_color', '#FFFFFF')
                bg_rgb = hex_to_rgb(bg_color_hex)

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

                # Use redaction for thorough cleaning with background color
                try:
                    page.add_redact_annot(clean_rect, fill=bg_rgb, text="")
                    page.apply_redactions()
                    logger.debug(f"Applied redaction with color {bg_color_hex} to area: {clean_rect}")
                except Exception as e:
                    logger.warning(f"Redaction failed, using draw_rect fallback: {e}")
                    page.draw_rect(clean_rect, color=bg_rgb, fill=bg_rgb, width=0)

                # Insert new text using the template's lines_data for positioning
                TemplateService._insert_text(
                    page=page,
                    rect=rect,
                    new_text=new_text,
                    lines_data=placeholder.lines_data,
                    strict_match=bool(placeholder.strict_match),
                    style=effective_style
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
