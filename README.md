# PDF Editor API

A FastAPI backend service for editing PDF documents through text replacement. This API enables creating templates with placeholders from master PDFs and generating new documents by applying replacement values.

## Features

- **Upload PDFs**: Store PDF documents for processing
- **View Pages**: Render PDF pages as images (base64 or binary)
- **Text Detection**: Extract text from selected areas using multiple methods:
  - Form fields (widgets)
  - Precise text layout extraction
  - Word clustering
  - OCR (requires Tesseract)
- **Templates**: Create reusable templates with placeholder definitions
- **Document Generation**: Generate new PDFs by applying replacement values

## Quick Start

### 1. Install Dependencies

```bash
cd pdf_editor_api
pip install -r requirements.txt
```

### 2. Configure Environment

Copy the example env file and adjust settings:

```bash
cp .env.example .env
```

Key settings:
- `TESSERACT_CMD`: Path to Tesseract OCR (optional, for scanned PDFs)
- `CORS_ORIGINS`: Allowed frontend origins
- `MAX_FILE_SIZE_MB`: Maximum upload file size

### 3. Run the Server

```bash
# Development mode with auto-reload
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Or run directly
python -m app.main
```

### 4. Access API Documentation

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## API Endpoints

### PDF Operations

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/pdf/upload` | Upload a PDF file |
| GET | `/api/pdf/{id}/info` | Get PDF metadata |
| GET | `/api/pdf/{id}/page/{num}` | Get page as image |
| POST | `/api/pdf/{id}/detect-text` | Detect text in selected area |
| DELETE | `/api/pdf/{id}` | Delete a PDF |

### Template Operations

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/template/create` | Create a template with placeholders |
| GET | `/api/template/list` | List all templates |
| GET | `/api/template/{id}` | Get template details |
| DELETE | `/api/template/{id}` | Delete a template |
| POST | `/api/template/{id}/generate` | Generate PDF with replacements |

## Usage Example

### 1. Upload a PDF

```bash
curl -X POST "http://localhost:8000/api/pdf/upload" \
  -F "file=@invoice_template.pdf"
```

Response:
```json
{
  "id": "abc123-...",
  "filename": "abc123-....pdf",
  "original_filename": "invoice_template.pdf",
  "page_count": 2,
  "file_size": 125000
}
```

### 2. View a Page

```bash
# Get page 0 as base64 image
curl "http://localhost:8000/api/pdf/abc123/page/0?zoom=1.5"
```

### 3. Detect Text in Area

```bash
curl -X POST "http://localhost:8000/api/pdf/abc123/detect-text" \
  -H "Content-Type: application/json" \
  -d '{"page": 0, "x0": 100, "y0": 200, "x1": 300, "y1": 250}'
```

Response:
```json
{
  "detected_text": "John Doe",
  "detection_source": "Precise Layout",
  "lines_data": [
    {"text": "John Doe", "baseline": 215.5, "size": 12}
  ],
  "rect": [100, 200, 300, 250]
}
```

### 4. Create a Template

```bash
curl -X POST "http://localhost:8000/api/template/create" \
  -H "Content-Type: application/json" \
  -d '{
    "pdf_id": "abc123",
    "name": "Invoice Template",
    "placeholders": [
      {
        "label": "customer_name",
        "page": 0,
        "rect": [100, 200, 300, 250],
        "detected_text": "John Doe",
        "lines_data": [{"text": "John Doe", "baseline": 215.5, "size": 12}]
      },
      {
        "label": "invoice_date",
        "page": 0,
        "rect": [400, 100, 500, 130]
      }
    ]
  }'
```

### 5. Generate Document

```bash
curl -X POST "http://localhost:8000/api/template/template123/generate" \
  -H "Content-Type: application/json" \
  -d '{
    "replacements": {
      "customer_name": "Jane Smith",
      "invoice_date": "2025-01-15"
    }
  }' \
  --output generated_invoice.pdf
```

## React Frontend Integration

### Coordinate Conversion

When selecting areas on the frontend, convert screen coordinates to PDF coordinates:

```javascript
// Screen to PDF coordinates
const pdfX = screenX / zoomLevel;
const pdfY = screenY / zoomLevel;

// PDF to Screen coordinates (for displaying placeholders)
const screenX = pdfX * zoomLevel;
const screenY = pdfY * zoomLevel;
```

### Example React Component

```jsx
import { useState } from 'react';

function PDFEditor({ pdfId }) {
  const [zoom, setZoom] = useState(1.5);
  const [selection, setSelection] = useState(null);

  const handleSelectionComplete = async (rect) => {
    // Convert to PDF coordinates
    const pdfRect = {
      page: currentPage,
      x0: rect.x0 / zoom,
      y0: rect.y0 / zoom,
      x1: rect.x1 / zoom,
      y1: rect.y1 / zoom
    };

    // Detect text
    const response = await fetch(`/api/pdf/${pdfId}/detect-text`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(pdfRect)
    });

    const data = await response.json();
    console.log('Detected:', data.detected_text);
  };

  return (/* ... */);
}
```

## Project Structure

```
pdf_editor_api/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app entry point
│   ├── config.py            # Settings from environment
│   ├── database.py          # SQLite database setup
│   ├── models/              # SQLAlchemy models
│   ├── schemas/             # Pydantic schemas
│   ├── services/            # Business logic
│   ├── routes/              # API endpoints
│   └── utils/               # Text detection utilities
├── uploads/                 # Uploaded PDF storage
├── generated/               # Generated PDF storage
├── requirements.txt
└── .env
```

## Database

Uses SQLite by default. The database file (`pdf_editor.db`) is created automatically on first run.

Tables:
- `pdf_documents`: Uploaded PDF metadata
- `templates`: Template definitions
- `placeholders`: Placeholder areas for each template

## Requirements

- Python 3.8+
- PyMuPDF (fitz) for PDF processing
- Pillow for image handling
- Tesseract OCR (optional, for scanned documents)




 Summary of Fixes

  1. Added Comprehensive Logging (app/config.py)

  - Added setup_logging() function with proper formatting
  - Created logger instance for the entire application
  - Added LOG_LEVEL setting

  2. Fixed PDF Routes (app/routes/pdf_routes.py)

  - Fixed deprecated regex parameter by using Literal["base64", "binary"] type hint
  - Added proper error handling with try/except blocks
  - Added logging for all endpoints
  - Added /list endpoint to list all uploaded PDFs
  - Reordered routes so /list comes before /{pdf_id} routes

  3. Fixed Template Routes (app/routes/template_routes.py)

  - Added proper error handling with try/except blocks
  - Added logging for all endpoints
  - HTTPExceptions are now properly re-raised

  4. Fixed PDF Service (app/services/pdf_service.py)

  - Added logging throughout
  - Fixed resource cleanup with finally blocks to ensure PDF documents are closed
  - Added list_pdfs() method
  - Better error messages and logging

  5. Fixed Template Service (app/services/template_service.py)

  - Added logging throughout
  - Fixed generate_document() with proper resource cleanup
  - Changed from draw_rect to add_redact_annot + apply_redactions (matches GUI behavior)
  - Fixed _insert_text() method with better null checking and logging
  - Added proper bounds for fontsize

  6. Updated Main Application (app/main.py)

  - Added global exception handler for unhandled exceptions
  - Added request logging middleware
  - Fixed download endpoint to return proper 404 errors
  - Added startup/shutdown event logging
  - Added proper CORS handling for wildcard origins

  7. Fixed Text Detection Utility (app/utils/text_detection.py)

  - Added logging for OCR availability
  - Added logging for each detection method attempted
  - Better error handling in OCR detection

  8. CORS Configuration (app/config.py)

  - Added wildcard (*) support for CORS origins
  - Better handling of CORS origins list

  API Endpoints Now Available

  | Method | Endpoint                                  | Description                       |
  |--------|-------------------------------------------|-----------------------------------|
  | POST   | /api/pdf/upload                           | Upload a PDF file                 |
  | GET    | /api/pdf/list                             | List all uploaded PDFs            |
  | GET    | /api/pdf/{pdf_id}/info                    | Get PDF metadata                  |
  | GET    | /api/pdf/{pdf_id}/page/{page_num}         | Get page as image                 |
  | POST   | /api/pdf/{pdf_id}/detect-text             | Detect text in area               |
  | DELETE | /api/pdf/{pdf_id}                         | Delete a PDF                      |
  | POST   | /api/template/create                      | Create a template                 |
  | GET    | /api/template/list                        | List all templates                |
  | GET    | /api/template/{template_id}               | Get template details              |
  | DELETE | /api/template/{template_id}               | Delete a template                 |
  | POST   | /api/template/{template_id}/generate      | Generate document                 |
  | POST   | /api/template/{template_id}/generate-json | Generate document (JSON response) |
  | GET    | /api/download/{file_id}                   | Download generated file           |
  | GET    | /health                                   | Health check                      |
  | GET    | /docs                                     | Swagger UI                        |

  To run the API:
  cd E:\work\supertruck-repo\COI_Mananagement\pdf-engine
  uvicorn app.main:app --reload