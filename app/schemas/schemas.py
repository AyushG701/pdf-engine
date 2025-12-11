from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime


# =============================================================================
# Line Data (for text positioning)
# =============================================================================

class LineData(BaseModel):
    """Represents a single line of detected text with layout info."""
    text: str
    baseline: float  # Y-coordinate of text baseline
    size: Optional[float] = None  # Font size


# =============================================================================
# PDF Document Schemas
# =============================================================================

class PDFUploadResponse(BaseModel):
    """Response after uploading a PDF."""
    id: str
    filename: str
    original_filename: str
    page_count: int
    file_size: int
    created_at: datetime

    class Config:
        from_attributes = True


class PDFInfoResponse(BaseModel):
    """PDF document metadata."""
    id: str
    filename: str
    original_filename: str
    page_count: int
    file_size: int
    created_at: datetime
    # Page dimensions (first page)
    width: Optional[float] = None
    height: Optional[float] = None

    class Config:
        from_attributes = True


class PDFPageResponse(BaseModel):
    """Response for page image request."""
    page_number: int
    total_pages: int
    width: float
    height: float
    image_base64: Optional[str] = None  # If returning base64
    image_url: Optional[str] = None  # If returning URL


# =============================================================================
# Text Detection Schemas
# =============================================================================

class TextDetectionRequest(BaseModel):
    """Request to detect text in a selected area."""
    page: int = Field(..., ge=0, description="Page number (0-indexed)")
    x0: float = Field(..., description="Left coordinate")
    y0: float = Field(..., description="Top coordinate")
    x1: float = Field(..., description="Right coordinate")
    y1: float = Field(..., description="Bottom coordinate")


class TextDetectionResponse(BaseModel):
    """Response with detected text and layout info."""
    detected_text: str
    detection_source: str  # "Form Field", "Precise Layout", "Clustered Words", "OCR", "Empty"
    lines_data: List[LineData]
    rect: List[float]  # [x0, y0, x1, y1]


# =============================================================================
# Placeholder Schemas
# =============================================================================

class PlaceholderCreate(BaseModel):
    """Data for creating a placeholder within a template."""
    label: str = Field(..., min_length=1, max_length=100, description="Unique identifier like 'customer_name'")
    page: int = Field(..., ge=0, description="Page number (0-indexed)")
    rect: List[float] = Field(..., min_length=4, max_length=4, description="[x0, y0, x1, y1]")
    detected_text: Optional[str] = None
    detection_source: Optional[str] = None
    lines_data: Optional[List[LineData]] = None
    strict_match: bool = True


class PlaceholderResponse(BaseModel):
    """Placeholder details in response."""
    id: str
    label: str
    page: int
    rect: List[float]
    detected_text: Optional[str]
    detection_source: Optional[str]
    lines_data: Optional[List[Dict[str, Any]]]
    strict_match: bool
    created_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# Template Schemas
# =============================================================================

class TemplateCreate(BaseModel):
    """Request to create a template with placeholders."""
    pdf_id: str
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    placeholders: List[PlaceholderCreate]


class TemplateResponse(BaseModel):
    """Full template details."""
    id: str
    name: str
    description: Optional[str]
    pdf_id: str
    pdf_filename: Optional[str] = None
    placeholders: List[PlaceholderResponse]
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class TemplateListResponse(BaseModel):
    """Lightweight template info for listing."""
    id: str
    name: str
    description: Optional[str]
    pdf_id: str
    pdf_filename: Optional[str]
    placeholder_count: int
    created_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# Document Generation Schemas
# =============================================================================

class GenerateRequest(BaseModel):
    """Request to generate a document from template."""
    replacements: Dict[str, str] = Field(
        ...,
        description="Map of placeholder labels to replacement values"
    )
    output_filename: Optional[str] = None


class GenerateResponse(BaseModel):
    """Response after document generation."""
    id: str
    filename: str
    download_url: str
    placeholders_replaced: int
    created_at: datetime


# =============================================================================
# Apply Template to Different Document
# =============================================================================

class ApplyTemplateRequest(BaseModel):
    """Request to apply a template to a different PDF document."""
    target_pdf_id: str = Field(..., description="ID of the PDF to apply template to")
    replacements: Dict[str, str] = Field(
        ...,
        description="Map of placeholder labels to replacement values"
    )
    output_filename: Optional[str] = None
    detect_and_replace: bool = Field(
        default=False,
        description="If True, detect text at template positions and replace. If False, just use positions for replacement."
    )


class ApplyTemplateResponse(BaseModel):
    """Response after applying template to a different document."""
    id: str
    filename: str
    download_url: str
    placeholders_replaced: int
    detected_values: Optional[Dict[str, str]] = None  # Detected text at each position
    created_at: datetime
