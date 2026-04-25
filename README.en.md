[简体中文](README.md) | [English](README.en.md)

# PaddleOCR Web UI

A web document OCR service based on PaddleOCR, supporting 24 file formats with a visual interface and REST API.

---

## Features

**File Processing**
- **24 Format Support**: PDF, images (jpg/png/bmp/tiff/webp), Office documents (doc/docx/xls/xlsx/ppt/pptx/odt/ods/odp/rtf/csv/txt/html), CAD drawings (dwg/dxf)
- **Office Conversion**: LibreOffice headless converts to PDF before OCR; falls back to python-docx/openpyxl extraction when LibreOffice is unavailable
- **CAD Recognition**: cad2x tool converts DWG/DXF to PDF for OCR, supports Chinese encoding and fonts
- **Image Extraction**: Images from OCR results are automatically extracted and saved to images/ directory with relative path references in Markdown
- **Multi-format Output**: Markdown, structured JSON (per-page per-block), plain text, DOCX, ZIP package download
- **Source File Preservation**: Source files and converted PDFs are preserved in the result directory for reference

**Task Management**
- **Task Queue**: 3-level priority queue (admin > API > user) with configurable concurrency
- **Two-phase Progress**: Office documents show two-phase progress (convert PDF + OCR); images/PDF show single progress bar
- **Real-time Progress**: WebSocket push with HTTP polling fallback; progress estimation based on historical data
- **Batch Operations**: Multi-file upload, batch ZIP download, batch delete

**System Administration**
- **Admin Panel**: User management, API Key management (create/revoke/view/copy)
- **Hot Settings**: Timeouts, concurrency, etc. can be modified in admin panel, take effect immediately without restart, auto-persist to .env
- **Log Viewer**: Real-time log viewer in admin panel with level-based coloring and auto-refresh
- **SSO Login**: Supports OOS unified login with admin whitelist

**Technical**
- **Streaming Transfer**: Chunked upload (4MB) + chunked base64 encoding for large files
- **Docker Deployment**: Dockerfile includes LibreOffice for one-click build and deploy

---

## Quick Start

### Docker (Recommended)

```bash
cd docker
docker compose up -d --build
```

Or build manually:

```bash
docker build -t paddleocr-ui -f docker/Dockerfile .
docker run -d -p 5553:5553 \
  -v ./data:/app/data \
  -e DB_HOST=your-db-host \
  -e DB_PASSWORD=your-password \
  paddleocr-ui
```

### Manual Deploy

**Dependencies:**
- Python 3.12+
- PostgreSQL (or openGauss-lite)
- LibreOffice (optional, needed for Office formats)
- Node.js 18+ (frontend build)

```bash
# Install backend dependencies
pip install -r requirements.txt

# Build frontend
cd frontend && npm install && npm run build && cp -r dist/* ../static/

# Configuration
cp .env.example .env
# Edit .env with your settings

# Initialize database
python -m backend.init_db

# Start
python -m backend.main
```

Visit http://localhost:5553 to use.

---

## Supported Formats

### Direct OCR

| Format | Description |
|--------|-------------|
| pdf | PDF documents |
| jpg / jpeg | JPEG images |
| png | PNG images |
| bmp | BMP images |
| tiff / tif | TIFF images |
| webp | WebP images |

### Via LibreOffice Conversion

| Format | Description |
|--------|-------------|
| doc / docx | Word documents |
| xls / xlsx | Excel spreadsheets |
| ppt / pptx | PowerPoint presentations |
| odt / ods / odp | OpenDocument formats |
| rtf / csv / txt / html | Other documents |

---

## API Usage

### Authentication

All API requests require an API Key:

```
X-API-Key: ak_xxxxxxxxxxxxx
```

### Submit Task

```bash
curl -X POST http://localhost:5553/api/v1/tasks \
  -H "X-API-Key: YOUR_KEY" \
  -F "file=@document.pdf" \
  -F "task_type=ocr" \
  -F 'output_formats=["markdown","json"]'
```

### Query Status

```bash
curl http://localhost:5553/api/v1/tasks/98 -H "X-API-Key: YOUR_KEY"
```

### Download Result

```bash
# ZIP package (source + images + results)
curl -O http://localhost:5553/api/v1/files/98/download?format=zip \
  -H "X-API-Key: YOUR_KEY"

# Other formats: md, json, txt, docx
curl -O http://localhost:5553/api/v1/files/98/download?format=json \
  -H "X-API-Key: YOUR_KEY"
```

For detailed API docs, see [docs/API.md](docs/API.md).

---

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Vue 3     │────▶│   FastAPI    │────▶│  PaddleOCR  │
│  Frontend   │◀────│   Backend    │◀────│  HPS Service │
└─────────────┘     └──────┬───────┘     └─────────────┘
                    ┌──────┴───────┐
                    │  PostgreSQL  │
                    │  (openGauss) │
                    └──────────────┘
```

- **Frontend**: Vue 3 + Element Plus + Pinia
- **Backend**: FastAPI + SQLAlchemy async + WebSocket
- **OCR Engine**: PaddleOCR HPS pipeline service
- **Doc Conversion**: LibreOffice headless
- **Task Queue**: asyncio.PriorityQueue (3-level priority)

---

## Admin Panel

| Module | Function |
|--------|----------|
| User Management | View users, set admin rights |
| API Key Management | Create, revoke, view keys |
| System Settings | Timeouts, concurrency (hot-reload) |
| System Logs | Real-time log viewer with coloring |

---

## Configuration

All settings via `.env` file or environment variables, see [.env.example](.env.example).

---

## License

MIT
