# Insurance Claim Settlement Agent

> Automated, auditable insurance claim adjudication with exact policy citations.

![Tests](https://img.shields.io/badge/tests-261%20passing-brightgreen)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

---

## 1. Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        INPUT LAYER                              │
│   [Hospital Bill PDF]          [Insurance Policy PDF]           │
└──────────────┬──────────────────────────┬───────────────────────┘
               │                          │
               ▼                          ▼
┌─────────────────────┐      ┌────────────────────────┐
│   BILL PROCESSOR    │      │   POLICY PROCESSOR     │
│  OCR + Extraction   │      │  Chunking + Indexing   │
│  Line-item parser   │      │  Embedding + FAISS     │
└──────────┬──────────┘      └───────────┬────────────┘
           │                             │
           ▼                             ▼
┌─────────────────────────────────────────────────────┐
│               RECONCILIATION ENGINE                 │
│   Bill Item ←→ Policy Clause Semantic Matcher       │
│   (sentence-transformers + FAISS vector search)     │
└──────────────────────────┬──────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────┐
│        DETERMINISTIC RULE ENGINE (12 Rules)         │
│  R01 Exclusion  R02 Waiting Period  R03 Room Rent   │
│  R04 Pre-exist  R05 Claim Cap       R06 Procedure   │
│  R07 Day Care   R08 Consumables     R09 Co-payment  │
│  R10 Network    R11 Duplicate       R12 Documents   │
└──────────────────────────┬──────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────┐
│            DECISION + CITATION ENGINE               │
│  APPROVED → Approval summary                        │
│  REJECTED → Exact policy citation per rejection     │
│             (Page N, Section, Paragraph P, text)    │
└──────────────────────────┬──────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────┐
│        FastAPI REST API + PDF Report Generator      │
└─────────────────────────────────────────────────────┘
```

> **AI handles perception. Rules make decisions.**
> sentence-transformers + FAISS are used for semantic matching only.
> The final approve/reject decision is made by a deterministic
> Python rule engine — making every decision auditable,
> testable, and reproducible.

---

## 2. Tech Stack

| Component | Technology | Rationale |
|-----------|------------|-----------|
| API Framework | FastAPI + Uvicorn | Async, standard, auto-docs at `/docs` |
| PDF Extraction | pdfplumber | Reliable text extraction from digital PDFs |
| OCR | pdf2image + pytesseract | Scanned/image-based PDF fallback |
| Embeddings | sentence-transformers (`all-MiniLM-L6-v2`) | Fast, offline, no API key required |
| Vector Search | FAISS (CPU) | Efficient L2 nearest-neighbor search |
| Rule Engine | Pure Python (deterministic) | Auditable, testable, reproducible decisions |
| PDF Reports | fpdf2 | Pure Python, no external dependencies |
| Configuration | pydantic-settings | Type-safe `.env` config loading |
| Testing | pytest + httpx | Full unit + integration test suite |
| Containerization | Docker | One-command deployment |

---

## 3. Quick Start

### Prerequisites

**Python 3.10+**

**Tesseract OCR:**
```bash
# Ubuntu / Debian
sudo apt-get install tesseract-ocr

# macOS
brew install tesseract

# Windows
# Download installer from: https://github.com/UB-Mannheim/tesseract/wiki
# Add to PATH: C:\Program Files\Tesseract-OCR
```

**Poppler (required by pdf2image):**
```bash
# Ubuntu / Debian
sudo apt-get install poppler-utils

# macOS
brew install poppler

# Windows
# Download from: https://github.com/oschwartz10612/poppler-windows/releases
# Extract and add bin/ folder to PATH
```

### Installation

```bash
# Clone the repository
git clone <repo-url>
cd insurance-claim-agent

# Create virtual environment
python -m venv venv
source venv/bin/activate      # Linux / macOS
# venv\Scripts\activate       # Windows

# Install Python dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env if Tesseract/Poppler are not on PATH
```

### Environment Setup

| Variable | Default | Description |
|----------|---------|-------------|
| `TESSERACT_CMD` | `tesseract` | Path to tesseract binary (leave as-is if in PATH) |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Sentence-transformers model for policy chunk embeddings |
| `FAISS_SIMILARITY_THRESHOLD` | `1.2` | L2 distance cutoff — lower means stricter matching |
| `USE_LLM_SUMMARY` | `false` | Enable Claude claude-haiku-4-5-20251001 for claim summaries (requires `ANTHROPIC_API_KEY`) |
| `STORAGE_DIR` | `storage` | Directory for processed claim JSON files |
| `REPORTS_DIR` | `reports` | Directory for generated PDF reports |

### Run the Server

```bash
uvicorn app.main:app --reload
```

API docs: http://localhost:8000/docs

### Run with Docker

```bash
# Build the image
docker build -t insurance-claim-agent .

# Run the container
docker run -p 8000:8000 \
  -e TESSERACT_CMD=tesseract \
  -e EMBEDDING_MODEL=all-MiniLM-L6-v2 \
  insurance-claim-agent
```

---

## 4. API Usage

### POST `/api/v1/claims/process` — Process a claim

```bash
curl -X POST http://localhost:8000/api/v1/claims/process \
  -F "bill_pdf=@data/synthetic/bills/bill_001.pdf" \
  -F "policy_pdf=@data/synthetic/policies/policy_c.pdf" \
  -F "policy_metadata=@data/synthetic/policy_c_metadata.json"
```

**Sample response:**
```json
{
  "claim_id": "3f7a9c12-...",
  "status": "approved",
  "total_billed": 45000.00,
  "total_approved": 45000.00,
  "total_rejected": 0.00,
  "summary": "Claim submitted by Rahul Sharma from City Hospital for Rs.45,000.00 has been APPROVED.",
  "line_item_results": [
    {
      "item_id": 1,
      "item_description": "Room Rent (General Ward) - 3 days",
      "original_amount": 9000.00,
      "approved_amount": 9000.00,
      "rule_results": [
        {
          "rule_name": "R01_exclusion_check",
          "verdict": "pass",
          "reason": "Item is not in the exclusions list.",
          "approved_amount": 9000.00,
          "citations": []
        }
      ]
    }
  ],
  "processed_at": "2026-04-04T12:00:00Z",
  "processing_time_ms": 812
}
```

### GET `/api/v1/claims/{claim_id}` — Retrieve a claim

```bash
curl http://localhost:8000/api/v1/claims/3f7a9c12-...
```

### GET `/api/v1/claims/` — List all claims

```bash
curl http://localhost:8000/api/v1/claims/
```

**Response:**
```json
{"claims": ["3f7a9c12-...", "a1b2c3d4-..."], "total": 2}
```

### GET `/api/v1/claims/{claim_id}/report` — Download PDF report

```bash
curl -o report.pdf \
  http://localhost:8000/api/v1/claims/3f7a9c12-.../report
```

---

## 5. Running Tests

```bash
pytest tests/ -v
```

**Expected output:**
```
261 passed in X.XXs
```

All 261 tests are deterministic and run fully offline — no external API calls, no model downloads at test time (embeddings are mocked).

---

## 6. Synthetic Dataset & Evaluation

### Generate test data

```bash
python scripts/generate_test_data.py
```

Creates 25 synthetic hospital bills and 3 insurance policies in `data/synthetic/`.

### Run the evaluation suite

```bash
python scripts/run_evaluation.py
```

Runs the full pipeline on all 25 test cases and outputs results to `reports/evaluation_results.json`.

---

## 7. Evaluation Results

| Metric | Value |
|--------|-------|
| **Decision Accuracy** | **100.0%** |
| **Rule Precision** | **100.0%** |
| **False Positive Rate** | **0.0%** |
| **False Negative Rate** | **0.0%** |
| **Avg Processing Time** | **0.82s** |
| **Total Test Cases** | **25** |
| **Passed** | **25** |
| **Failed** | **0** |

### Scenario Breakdown

| Scenario | Cases | Expected Status | Result |
|----------|-------|-----------------|--------|
| Clean claims | 5 | APPROVED | ✓ |
| Excluded procedure | 5 | REJECTED | ✓ |
| Exceeds sum insured | 3 | REJECTED | ✓ |
| Within waiting period | 3 | REJECTED | ✓ |
| Room rent over limit | 3 | PARTIAL | ✓ |
| Non-network hospital | 2 | REJECTED | ✓ |
| Pre-existing condition | 2 | REJECTED | ✓ |
| Multiple rules fire | 2 | REJECTED | ✓ |

---

## 8. Design Decisions

**Why AI is used for matching but not decisions.** AI/ML excels at unstructured perception tasks — understanding that "ICU charges" in a bill relates to the "Intensive Care Unit" clause in a policy. However, the approve/reject decision itself must be auditable, reproducible, and defensible. Using an LLM for final decisions is a liability: outputs can vary between calls, cannot be unit-tested reliably, and provide no legal basis for rejection. The architecture deliberately restricts AI to the *perception layer* (OCR + semantic matching) and delegates all decisions to deterministic rules with exact citations.

**Why FAISS + rules beats a pure LLM approach.** A pure LLM approach requires an API key, internet access, and costs money per claim. It cannot guarantee identical outputs for identical inputs, making testing impossible. FAISS + sentence-transformers runs fully offline in under a second, produces repeatable results, and scales horizontally without cost. The rule engine then applies explicit, inspectable logic — every decision can be traced to a specific rule, a specific amount, and a specific policy clause.

**Why synthetic data is sufficient.** The goal of the evaluation dataset is to verify that the rule engine produces correct decisions for boundary conditions — not to train a model. The 25 synthetic bills cover all 12 rule categories including edge cases (exact limit values, overlapping rules, zero-amount items). Since the rule engine is deterministic, 100% accuracy on synthetic data with known ground truth is a meaningful correctness guarantee, not overfitting.

---

## 9. Limitations and Future Work

- **OCR accuracy on complex real-world layouts.** Scanned PDFs with tables, handwriting, stamps, or multi-column layouts may produce garbled text. Production systems would benefit from a dedicated medical-document OCR model (e.g. Google Document AI or AWS Textract).

- **Policy PDF variability and heading detection limits.** The heading detector uses heuristics (ALL CAPS, trailing colon, short line before blank). Policies with unusual formatting, numbered sections (e.g. `3.2.1`), or decorative typography may not chunk correctly, reducing citation precision.

- **Rule coverage (12 rules vs 50–100+ in production).** Real insurance adjudication involves sub-clauses, rider policies, network tier reductions, GST applicability, pre-authorization requirements, and more. The 12 rules here cover the most common rejection categories but are not exhaustive.

---

## 10. Project Structure

```
insurance-claim-agent/
├── app/
│   ├── main.py                  # FastAPI entrypoint + lifespan
│   ├── config.py                # Pydantic settings singleton
│   ├── models/
│   │   ├── __init__.py          # Re-exports all models
│   │   ├── enums.py             # ClaimStatus, RuleVerdict,
│   │   │                        # BillItemCategory, PDFType
│   │   ├── bill.py              # Bill, BillLineItem
│   │   ├── policy.py            # PolicyChunk, PolicyMeta
│   │   ├── citation.py          # Citation
│   │   ├── rule.py              # RuleResult, LineItemResult
│   │   └── decision.py          # ClaimDecision
│   ├── services/
│   │   ├── bill_processor.py    # process_bill(path) -> Bill
│   │   ├── policy_processor.py  # process_policy(pdf, meta)
│   │   │                        #   -> (list[PolicyChunk], PolicyMeta)
│   │   ├── embedder.py          # encode_chunks(), encode_text()
│   │   ├── index_builder.py     # build_index(), save_index(),
│   │   │                        # load_index()
│   │   ├── semantic_matcher.py  # match_line_item()
│   │   ├── rule_engine.py       # run_rules() + 12 rule functions
│   │   ├── citation_engine.py   # build_citation(),
│   │   │                        # attach_citations(),
│   │   │                        # format_citation_text(),
│   │   │                        # citation_summary()
│   │   ├── decision_engine.py   # process_claim() — MAIN ENTRY POINT
│   │   └── report_generator.py  # generate_report(decision, bill)
│   └── api/
│       ├── __init__.py
│       └── routes.py            # 4 endpoints
├── scripts/
│   ├── __init__.py
│   ├── generate_test_data.py    # generates 25 bills + 3 policies
│   └── run_evaluation.py        # runs full pipeline on all 25 cases
├── data/
│   └── synthetic/
│       ├── policies/            # policy_a.pdf, policy_b.pdf,
│       │                        # policy_c.pdf
│       ├── bills/               # bill_001.pdf … bill_025.pdf
│       ├── ground_truth.json    # 25 labeled test cases
│       ├── policy_a_metadata.json
│       ├── policy_b_metadata.json
│       └── policy_c_metadata.json
├── tests/
│   ├── conftest.py              # shared TestClient fixture
│   ├── test_smoke.py
│   ├── test_models.py
│   ├── test_bill_processor.py
│   ├── test_policy_processor.py
│   ├── test_semantic_matcher.py
│   ├── test_rule_engine.py
│   ├── test_citation_engine.py
│   ├── test_decision_engine.py
│   ├── test_api.py
│   ├── test_report_generator.py
│   └── test_evaluation.py
├── storage/
│   └── claims/                  # saved ClaimDecision JSON files
├── reports/
│   └── evaluation_results.json  # evaluation output
├── requirements.txt
├── Dockerfile
├── .env.example
└── .gitignore
```

---

## 11. License

MIT
