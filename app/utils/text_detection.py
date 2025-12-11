"""
Text detection utilities for extracting text from PDF regions.
Implements the same detection logic as the GUI version.
"""
import fitz  # PyMuPDF
from PIL import Image
import io
import os
import logging
from typing import List, Dict, Tuple, Optional
from app.config import settings

logger = logging.getLogger("pdf_editor.utils.text_detection")

# Try to import pytesseract for OCR
try:
    import pytesseract
    if settings.TESSERACT_CMD and os.path.exists(settings.TESSERACT_CMD):
        pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_CMD
        logger.info(f"Tesseract OCR available at: {settings.TESSERACT_CMD}")
    OCR_AVAILABLE = True
except ImportError:
    logger.warning("Tesseract OCR not available - OCR detection disabled")
    OCR_AVAILABLE = False


class TextDetector:
    """
    Detects text within a rectangular region of a PDF page.
    Uses multiple detection methods in order of preference:
    1. Form fields (widgets)
    2. Precise text layout (dict extraction)
    3. Word clustering
    4. OCR (fallback)
    """

    @staticmethod
    def detect_text(
        page: fitz.Page,
        rect: fitz.Rect
    ) -> Tuple[str, str, List[Dict]]:
        """
        Detect text in the given rectangle area of the page.

        Args:
            page: PyMuPDF page object
            rect: Rectangle area to extract text from

        Returns:
            Tuple of (detected_text, detection_source, lines_data)
            - detected_text: The extracted text content
            - detection_source: Method used for detection
            - lines_data: List of line info with baseline positions
        """
        detected_text = ""
        detection_source = "Empty"
        lines_data = []

        logger.debug(f"Detecting text in rect: {rect}")

        # Method 1: Check Form Fields (Widgets)
        logger.debug("Trying Method 1: Form Fields (Widgets)")
        detected_text, lines_data = TextDetector._detect_from_widgets(page, rect)
        if detected_text:
            detection_source = "Form Field"
            logger.info(f"Text detected via Form Field: '{detected_text[:50]}...'")
            return detected_text, detection_source, lines_data

        # Method 2: Precise Text Layout
        logger.debug("Trying Method 2: Precise Text Layout")
        detected_text, lines_data = TextDetector._detect_from_text_dict(page, rect)
        if detected_text:
            detection_source = "Precise Layout"
            logger.info(f"Text detected via Precise Layout: '{detected_text[:50]}...'")
            return detected_text, detection_source, lines_data

        # Method 3: Word Clustering
        logger.debug("Trying Method 3: Word Clustering")
        detected_text, lines_data = TextDetector._detect_from_word_clusters(page, rect)
        if detected_text:
            detection_source = "Clustered Words"
            logger.info(f"Text detected via Clustered Words: '{detected_text[:50]}...'")
            return detected_text, detection_source, lines_data

        # Method 4: OCR (if available)
        if OCR_AVAILABLE:
            logger.debug("Trying Method 4: OCR")
            detected_text, lines_data = TextDetector._detect_from_ocr(page, rect)
            if detected_text:
                detection_source = "OCR"
                logger.info(f"Text detected via OCR: '{detected_text[:50]}...'")
                return detected_text, detection_source, lines_data
        else:
            logger.debug("OCR not available, skipping")

        logger.debug("No text detected in the selected area")
        return detected_text, detection_source, lines_data

    @staticmethod
    def _detect_from_widgets(
        page: fitz.Page,
        rect: fitz.Rect
    ) -> Tuple[str, List[Dict]]:
        """Extract text from form field widgets."""
        for widget in page.widgets():
            if widget.rect.intersects(rect):
                if widget.field_value:
                    text = str(widget.field_value)
                    lines_data = [{
                        'text': text,
                        'baseline': rect.y1 - 2,
                        'size': rect.y1 - rect.y0
                    }]
                    return text, lines_data
        return "", []

    @staticmethod
    def _detect_from_text_dict(
        page: fitz.Page,
        rect: fitz.Rect
    ) -> Tuple[str, List[Dict]]:
        """Extract text using precise text dictionary layout."""
        logger.info(f"[TextDict] Extracting text from rect: {rect}")

        text_dict = page.get_text("dict", clip=rect)
        all_lines = []

        # Log raw text dict structure
        block_count = len(text_dict.get("blocks", []))
        logger.info(f"[TextDict] Found {block_count} blocks")

        if "blocks" in text_dict:
            for i, block in enumerate(text_dict["blocks"]):
                block_type = block.get("type", "unknown")
                logger.debug(f"[TextDict] Block {i}: type={block_type}")

                if "lines" in block:
                    for j, line in enumerate(block["lines"]):
                        spans = line.get("spans", [])
                        line_text = " ".join([s["text"] for s in spans])
                        logger.debug(f"[TextDict] Block {i}, Line {j}: '{line_text[:50]}...' ({len(spans)} spans)")

                        if line_text.strip():
                            # Get line bounding box
                            line_bbox = line.get("bbox", [0, 0, 0, 0])

                            # Capture baseline, y0, y1, and font info from first span
                            first_span = line["spans"][0] if spans else {}
                            all_lines.append({
                                'text': line_text.strip(),
                                'baseline': first_span.get("origin", [0, line_bbox[3]])[1],
                                'y0': line_bbox[1],  # Top of line
                                'y1': line_bbox[3],  # Bottom of line
                                'size': first_span.get("size", 10),
                                'font': first_span.get("font", "helv"),
                                'color': first_span.get("color", 0)  # Color as integer
                            })

        # Sort by Y position (top to bottom)
        all_lines.sort(key=lambda x: x['y0'] if x.get('y0') is not None else x['baseline'])

        logger.info(f"[TextDict] Extracted {len(all_lines)} lines")

        if all_lines:
            detected_text = "\n".join([l['text'] for l in all_lines])
            return detected_text, all_lines

        return "", []

    @staticmethod
    def _detect_from_word_clusters(
        page: fitz.Page,
        rect: fitz.Rect
    ) -> Tuple[str, List[Dict]]:
        """Extract text by clustering words by Y position."""
        logger.info(f"[WordCluster] Extracting words from rect: {rect}")

        words = page.get_text("words", clip=rect)
        logger.info(f"[WordCluster] Found {len(words)} words")

        if not words:
            return "", []

        # Log some sample words for debugging
        for i, w in enumerate(words[:5]):
            logger.debug(f"[WordCluster] Word {i}: '{w[4]}' at ({w[0]:.1f}, {w[1]:.1f}, {w[2]:.1f}, {w[3]:.1f})")

        # Group words by approximate Y position (using center Y for better clustering)
        lines: Dict[float, List] = {}
        for w in words:
            y_center = (w[1] + w[3]) / 2  # Center Y of word
            found = False
            for existing_y in list(lines.keys()):
                if abs(existing_y - y_center) < 5:  # Tolerance
                    lines[existing_y].append(w)
                    found = True
                    break
            if not found:
                lines[y_center] = [w]

        # Sort lines by Y and words by X
        sorted_y = sorted(lines.keys())
        lines_data = []

        for y_center in sorted_y:
            words_in_line = sorted(lines[y_center], key=lambda x: x[0])
            text = " ".join([w[4] for w in words_in_line])

            # Calculate y0 and y1 from all words in the line
            y0 = min(w[1] for w in words_in_line)
            y1 = max(w[3] for w in words_in_line)
            avg_height = y1 - y0

            lines_data.append({
                'text': text,
                'baseline': y1 - (avg_height * 0.2),  # Estimate baseline at 80% down
                'y0': y0,
                'y1': y1,
                'size': avg_height * 0.8  # Estimate font size from line height
            })

        detected_text = "\n".join([l['text'] for l in lines_data])
        logger.info(f"[WordCluster] Extracted {len(lines_data)} lines")
        return detected_text, lines_data

    @staticmethod
    def _detect_from_ocr(
        page: fitz.Page,
        rect: fitz.Rect
    ) -> Tuple[str, List[Dict]]:
        """Extract text using OCR on the page region."""
        try:
            # Render region at high resolution
            mat = fitz.Matrix(3, 3)  # 3x zoom for better OCR
            pix = page.get_pixmap(matrix=mat, clip=rect)
            img = Image.open(io.BytesIO(pix.tobytes("png")))

            # Run OCR
            logger.debug("Running OCR on selected region...")
            ocr_text = pytesseract.image_to_string(img, config='--psm 6').strip()

            if ocr_text:
                logger.debug(f"OCR detected: '{ocr_text[:50]}...'")
                # Estimate line positions from OCR result
                ocr_lines = ocr_text.split('\n')
                lines_data = []
                h = (rect.y1 - rect.y0) / max(len(ocr_lines), 1)

                for i, line in enumerate(ocr_lines):
                    if line.strip():
                        lines_data.append({
                            'text': line.strip(),
                            'baseline': rect.y0 + ((i + 1) * h) - 2,
                            'size': h * 0.8
                        })

                return ocr_text, lines_data
            else:
                logger.debug("OCR returned empty result")
        except Exception as e:
            logger.warning(f"OCR failed: {str(e)}")

        return "", []


def measure_text_width(text: str, fontname: str, fontsize: float) -> float:
    """
    Measure the width of text at a given font size.
    Uses PyMuPDF API or falls back to heuristic estimation.
    """
    # Try PyMuPDF methods
    try:
        if hasattr(fitz, "get_text_length"):
            return fitz.get_text_length(text, fontname=fontname, fontsize=fontsize)
        if hasattr(fitz, "getTextLength"):
            return fitz.getTextLength(text, fontname=fontname, fontsize=fontsize)

        # Try Font object
        try:
            f = fitz.Font(fontname)
            if hasattr(f, "text_length"):
                return f.text_length(text, fontsize)
        except Exception:
            pass
    except Exception:
        pass

    # Fallback: heuristic width calculation
    width = 0.0
    for ch in text:
        if ch == ' ':
            width += 0.35 * fontsize
        elif ch in 'il.,:;|!\'`':
            width += 0.3 * fontsize
        elif ch in 'wmMW@#%&':
            width += 0.9 * fontsize
        else:
            width += 0.6 * fontsize
    return width
