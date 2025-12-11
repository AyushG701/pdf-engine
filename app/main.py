"""
PDF Editor API - FastAPI Application Entry Point

This API allows you to:
1. Upload PDF documents
2. View PDF pages as images
3. Detect text in selected areas
4. Create templates with placeholders
5. Generate new documents with text replacements
"""
import os
import logging
import traceback
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from app.config import settings, logger
from app.database import init_db
from app.routes.pdf_routes import router as pdf_router
from app.routes.template_routes import router as template_router

# Initialize FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    description="""
## PDF Editor API

A service for editing PDF documents through text replacement.

### Features:
- **Upload PDFs**: Store PDF documents for processing
- **View Pages**: Render PDF pages as images for display
- **Text Detection**: Select areas and extract text using multiple methods
- **Templates**: Create reusable templates with placeholder definitions
- **Document Generation**: Generate new PDFs by applying replacements

### Workflow:
1. Upload a master PDF document
2. View the PDF and select text areas
3. Define placeholders with labels (e.g., "customer_name")
4. Save as a template
5. Generate documents by providing replacement values
""",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle all unhandled exceptions."""
    # Log the full exception with traceback
    logger.error(
        f"Unhandled exception on {request.method} {request.url.path}: {str(exc)}",
        exc_info=True
    )

    # Return a proper error response
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail}
        )

    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "message": str(exc) if settings.DEBUG else "An unexpected error occurred"
        }
    )


# Configure CORS - MUST be added before other middleware
# Using wildcard "*" for development to allow all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
    allow_credentials=False,  # Must be False when using "*" for origins
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


# Request logging middleware (added after CORS so CORS processes first)
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all incoming requests."""
    logger.debug(f"Request: {request.method} {request.url.path}")
    try:
        response = await call_next(request)
        logger.debug(f"Response: {request.method} {request.url.path} - {response.status_code}")
        return response
    except Exception as e:
        logger.error(f"Request failed: {request.method} {request.url.path} - {str(e)}")
        raise

# Include routers
app.include_router(pdf_router, prefix="/api")
app.include_router(template_router, prefix="/api")


# Download endpoint for generated files
@app.get("/api/download/{file_id}")
async def download_generated_file(file_id: str):
    """
    Download a generated PDF file by ID.
    """
    logger.debug(f"Download request for file_id: {file_id}")

    # Find file matching the ID
    generated_dir = Path(settings.GENERATED_DIR)
    if not generated_dir.exists():
        logger.warning(f"Generated directory does not exist: {generated_dir}")
        raise HTTPException(status_code=404, detail="File not found")

    for file_path in generated_dir.glob(f"{file_id}_*.pdf"):
        if file_path.exists():
            # Extract original filename from path
            filename = "_".join(file_path.name.split("_")[1:])
            logger.info(f"Serving download: {filename}")
            return FileResponse(
                path=str(file_path),
                filename=filename,
                media_type="application/pdf"
            )

    logger.warning(f"File not found for download: {file_id}")
    raise HTTPException(status_code=404, detail="File not found")


# Health check endpoint
@app.get("/health", tags=["Status"])
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": settings.APP_NAME
    }


# Root endpoint
@app.get("/")
async def root():
    """API root - redirects to documentation."""
    return {
        "message": f"Welcome to {settings.APP_NAME}",
        "docs": "/docs",
        "health": "/health"
    }


# Startup event
@app.on_event("startup")
async def startup_event():
    """Initialize database on startup."""
    logger.info(f"Starting {settings.APP_NAME}...")
    init_db()
    logger.info(f"Database initialized")
    logger.info(f"Upload directory: {os.path.abspath(settings.UPLOAD_DIR)}")
    logger.info(f"Generated directory: {os.path.abspath(settings.GENERATED_DIR)}")
    logger.info(f"CORS origins: {settings.cors_origins_list}")
    logger.info(f"{settings.APP_NAME} ready to accept requests")


# Shutdown event
@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    logger.info(f"Shutting down {settings.APP_NAME}...")


# Run with: uvicorn app.main:app --reload
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG
    )
