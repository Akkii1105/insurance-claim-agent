# Insurance Claim Settlement Agent

> **Hackathon Project** — Automated insurance claim adjudication with deterministic rules and exact policy citations.

## What It Does

1. **Ingests** hospital bill PDFs (text-based or scanned via OCR)
2. **Parses** insurance policy PDFs into searchable, indexed chunks
3. **Matches** bill line items against relevant policy clauses using semantic search
4. **Applies** deterministic rules (exclusions, waiting periods, caps, sub-limits)
5. **Decides** approve/reject with exact citations (page, paragraph, clause text)
6. **Generates** a downloadable PDF report with full audit trail

## Key Design Principle

> AI/ML is used for extraction and matching. The final approve/reject decision is **deterministic, auditable, and testable** — never a black-box LLM call.

## Architecture

```
Bill PDF ──→ [Bill Processor] ──→ Structured Bill JSON
                                          │
Policy PDF ──→ [Policy Processor] ──→ FAISS Index
                                          │
                              ┌───────────┘
                              ▼
                    [Semantic Matcher] ──→ Matched Clauses
                              │
                              ▼
                      [Rule Engine] ──→ Rule Results
                              │
                              ▼
                   [Decision Engine] ──→ Claim Decision
                              │
                              ▼
                    [Report Generator] ──→ PDF Report
```

## Quick Start

```bash
# 1. Clone and setup
git clone <repo-url>
cd insurance-claim-agent
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/Mac

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure
copy .env.example .env       # Edit paths for Tesseract/Poppler if needed

# 4. Run
uvicorn app.main:app --reload

# 5. Test
pytest
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| _More endpoints will be added in Step 9_ | | |

## Tech Stack

| Component | Technology |
|-----------|-----------|
| API | FastAPI + Uvicorn |
| PDF Text Extraction | pdfplumber |
| OCR Fallback | pdf2image + pytesseract |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) |
| Vector Search | FAISS |
| Report Generation | fpdf2 |
| Config | pydantic-settings |
| Testing | pytest + httpx |

## Project Structure

```
insurance-claim-agent/
├── app/
│   ├── main.py              # FastAPI entrypoint
│   ├── config.py            # Settings
│   ├── models/              # Pydantic schemas
│   ├── services/            # Business logic
│   ├── api/                 # Route handlers
│   └── utils/               # Helpers
├── tests/                   # Test suite
├── data/                    # Sample PDFs
├── storage/                 # FAISS indexes
├── reports/                 # Generated reports
├── requirements.txt
└── .env.example
```

## License

MIT
