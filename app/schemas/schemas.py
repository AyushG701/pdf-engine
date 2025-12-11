from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Union
from datetime import datetime
from enum import Enum


# =============================================================================
# Enums for styling options
# =============================================================================

class FontWeight(str, Enum):
    NORMAL = "normal"
    BOLD = "bold"


class ContentType(str, Enum):
    TEXT = "text"
    IMAGE = "image"


# =============================================================================
# Line Data (for text positioning)
# =============================================================================

class LineData(BaseModel):
    """Represents a single line of detected text with layout info."""
    text: str
    baseline: float  # Y-coordinate of text baseline
    y0: Optional[float] = None  # Top Y coordinate of the line
    y1: Optional[float] = None  # Bottom Y coordinate of the line
    size: Optional[float] = None  # Font size


# =============================================================================
# Styling Options for Placeholders
# =============================================================================

class PlaceholderStyle(BaseModel):
    """Styling options for a placeholder."""
    font_size: Optional[float] = Field(default=None, description="Font size in points. If None, auto-calculated from box height")
    font_name: str = Field(default="helv", description="Font name (helv, times-roman, courier)")
    font_weight: FontWeight = Field(default=FontWeight.NORMAL, description="Font weight")
    color: str = Field(default="#000000", description="Text color in hex format")
    opacity: float = Field(default=1.0, ge=0.0, le=1.0, description="Text opacity (0-1)")
    background_color: Optional[str] = Field(default="#FFFFFF", description="Background color in hex, None for transparent")
    background_opacity: float = Field(default=1.0, ge=0.0, le=1.0, description="Background opacity (0-1)")
    background_width: Optional[float] = Field(default=None, description="Background width override. None = auto fit to text")
    background_height: Optional[float] = Field(default=None, description="Background height override. None = auto fit to text")
    padding: float = Field(default=1.0, description="Padding around text in points")


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
    # New fields for content type and styling
    content_type: ContentType = Field(default=ContentType.TEXT, description="Type of content: text or image")
    style: Optional[PlaceholderStyle] = Field(default=None, description="Default styling for this placeholder")
    multi_line: bool = Field(default=False, description="Whether this placeholder supports multiple lines")


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
    content_type: ContentType = ContentType.TEXT
    style: Optional[Dict[str, Any]] = None
    multi_line: bool = False
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


class PlaceholderUpdate(BaseModel):
    """Data for updating a placeholder."""
    id: str = Field(..., description="Placeholder ID to update")
    label: Optional[str] = Field(default=None, min_length=1, max_length=100)
    rect: Optional[List[float]] = Field(default=None, min_length=4, max_length=4)
    detected_text: Optional[str] = None
    lines_data: Optional[List[LineData]] = None
    strict_match: Optional[bool] = None
    content_type: Optional[ContentType] = None
    style: Optional[PlaceholderStyle] = None
    multi_line: Optional[bool] = None


class TemplateUpdate(BaseModel):
    """Request to update a template."""
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    # Update existing placeholders
    placeholders: Optional[List[PlaceholderUpdate]] = None
    # Add new placeholders
    add_placeholders: Optional[List[PlaceholderCreate]] = None
    # Remove placeholders by ID
    remove_placeholder_ids: Optional[List[str]] = None


# =============================================================================
# Document Generation Schemas
# =============================================================================

class ReplacementValue(BaseModel):
    """Value for a single placeholder replacement with optional styling."""
    value: str = Field(..., description="The replacement text or base64 image data")
    content_type: ContentType = Field(default=ContentType.TEXT, description="Type of content")
    style: Optional[PlaceholderStyle] = Field(default=None, description="Override styling for this replacement")


class GenerateRequest(BaseModel):
    """Request to generate a document from template."""
    replacements: Dict[str, Union[str, ReplacementValue]] = Field(
        ...,
        description="Map of placeholder labels to replacement values (string or ReplacementValue object)"
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
