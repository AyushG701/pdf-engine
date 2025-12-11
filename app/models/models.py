from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey, Text, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import uuid


def generate_uuid():
    return str(uuid.uuid4())


class PDFDocument(Base):
    """Stores uploaded PDF documents."""
    __tablename__ = "pdf_documents"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer, nullable=False)  # in bytes
    page_count = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    templates = relationship("Template", back_populates="pdf_document", cascade="all, delete-orphan")


class Template(Base):
    """Master document templates with placeholder definitions."""
    __tablename__ = "templates"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    pdf_id = Column(String(36), ForeignKey("pdf_documents.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    pdf_document = relationship("PDFDocument", back_populates="templates")
    placeholders = relationship("Placeholder", back_populates="template", cascade="all, delete-orphan")


class Placeholder(Base):
    """Text areas defined within a template for replacement."""
    __tablename__ = "placeholders"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    template_id = Column(String(36), ForeignKey("templates.id", ondelete="CASCADE"), nullable=False)

    # Identifier for this placeholder (e.g., "customer_name", "invoice_date")
    label = Column(String(100), nullable=False)

    # Position data
    page = Column(Integer, nullable=False)  # 0-indexed page number
    x0 = Column(Float, nullable=False)  # Left coordinate
    y0 = Column(Float, nullable=False)  # Top coordinate
    x1 = Column(Float, nullable=False)  # Right coordinate
    y1 = Column(Float, nullable=False)  # Bottom coordinate

    # Detected text info
    detected_text = Column(Text, nullable=True)
    detection_source = Column(String(50), nullable=True)  # "Form Field", "Precise Layout", etc.

    # Line layout data for precise text positioning (stored as JSON)
    # Format: [{"text": "line text", "baseline": 215.5, "y0": 210, "y1": 222, "size": 12}, ...]
    lines_data = Column(JSON, nullable=True)

    # Options
    strict_match = Column(Integer, default=1)  # 1 = match original layout, 0 = auto-distribute

    # Content type: "text" or "image"
    content_type = Column(String(20), default="text")

    # Whether this placeholder supports multiple lines
    multi_line = Column(Integer, default=0)  # 0 = single line, 1 = multi-line

    # Default styling options (stored as JSON)
    # Format: {"font_size": 12, "font_name": "helv", "font_weight": "normal",
    #          "color": "#000000", "opacity": 1.0, "background_color": "#FFFFFF",
    #          "background_opacity": 1.0, "background_width": null, "background_height": null, "padding": 1}
    style = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    template = relationship("Template", back_populates="placeholders")
