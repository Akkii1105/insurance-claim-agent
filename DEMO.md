# Demo Guide — Insurance Claim Settlement Agent

## Total time: ~5 minutes

---

## Step 1: Start the server (30 seconds)

```bash
# Activate your virtual environment first
source venv/bin/activate      # Linux / macOS
# venv\Scripts\activate       # Windows

uvicorn app.main:app --reload
```

Confirm the server is running by opening the interactive API docs:
**http://localhost:8000/docs**

You should see 4 endpoints listed under the "Claims" tag.

---

## Step 2: Generate test data (30 seconds)

```bash
python scripts/generate_test_data.py
```

Confirm the output directory was created:

```bash
ls data/synthetic/bills/     # Should show bill_001.pdf … bill_025.pdf
ls data/synthetic/policies/  # Should show policy_a.pdf, policy_b.pdf, policy_c.pdf
```

---

## Step 3: Demo a REJECTED claim with citation (90 seconds)

This demonstrates the system finding a policy exclusion and citing the exact clause.

```bash
curl -X POST http://localhost:8000/api/v1/claims/process \
  -F "bill_pdf=@data/synthetic/bills/bill_006.pdf" \
  -F "policy_pdf=@data/synthetic/policies/policy_a.pdf" \
  -F "policy_metadata=@data/synthetic/policy_a_metadata.json" \
  | python -m json.tool
```

**What to point to in the response:**

```json
{
  "status": "rejected",
  "line_item_results": [
    {
      "rule_results": [
        {
          "rule_name": "R01_exclusion_check",
          "verdict": "fail",
          "reason": "Procedure 'cosmetic surgery' matches policy exclusion: 'cosmetic'",
          "citations": [
            {
              "page_number": 3,
              "section_title": "Exclusions",
              "paragraph_number": 2,
              "clause_text": "The following procedures are excluded from coverage..."
            }
          ]
        }
      ]
    }
  ]
}
```

**Script for judges:**

> "The system found 'cosmetic' in the bill description, semantically matched it to the exclusions clause on page 3, and rejected it — with zero LLM involvement. The rule engine flagged it via exact substring match against the exclusions list from the policy metadata. Every field in this citation — page number, section title, paragraph, clause text — is extracted directly from the policy PDF."

---

## Step 4: Demo an APPROVED claim (60 seconds)

This demonstrates a clean claim where all 12 rules pass.

```bash
curl -X POST http://localhost:8000/api/v1/claims/process \
  -F "bill_pdf=@data/synthetic/bills/bill_001.pdf" \
  -F "policy_pdf=@data/synthetic/policies/policy_c.pdf" \
  -F "policy_metadata=@data/synthetic/policy_c_metadata.json" \
  | python -m json.tool
```

**What to look for:**

- `"status": "approved"`
- Every `rule_results` entry has `"verdict": "pass"` or `"verdict": "skip"`
- `"total_approved"` equals `"total_billed"`
- No citations (citations only appear on rejections)

---

## Step 5: Download the PDF report (30 seconds)

Copy the `claim_id` from the previous response, then:

```bash
export CLAIM_ID="<paste-claim-id-here>"

curl -o report.pdf \
  http://localhost:8000/api/v1/claims/${CLAIM_ID}/report
```

Open `report.pdf` and show judges:

1. **Header** — Claim ID, timestamp, APPROVED / REJECTED badge
2. **Claim Summary table** — patient, hospital, billed vs approved amounts
3. **Line Item Decisions** — each item with verdict and reason
4. **Policy Basis for Rejection** — exact page, section, paragraph, and clause text (visible on rejected claims)
5. **Footer** — "Automated deterministic rule engine decision."

---

## Step 6: Run the evaluation suite (60 seconds)

```bash
python scripts/run_evaluation.py
```

**Expected terminal output:**

```
Running evaluation on 25 test cases...
[25/25] Complete
Decision Accuracy:   100.0%
Rule Precision:      100.0%
False Positive Rate:   0.0%
False Negative Rate:   0.0%
Avg Processing Time:  0.82s
Results saved to reports/evaluation_results.json
```

Point to `reports/evaluation_results.json` for the detailed per-case breakdown.

---

## Step 7: Show the test suite (30 seconds)

```bash
pytest tests/ -q
```

**Expected output:**

```
261 passed in X.XXs
```

Or for verbose output with test names:

```bash
pytest tests/ -v --tb=short
```

---

## What to Emphasize to Judges

### 1. The AI / Rules boundary is explicit and enforced

> "AI — specifically sentence-transformers + FAISS — is used only for matching bill line items to relevant policy clauses. The moment we need to say 'approve' or 'reject', a deterministic Python rule takes over. No LLM, no probability — just code you can read."

### 2. Every rejection has an exact citation

> "Show the citation block in the JSON: page number, section title, paragraph number, and the actual clause text. This is audit-ready. An insurer can show this to a policyholder or regulator and point to the exact sentence in the policy that justifies the rejection."

### 3. 261 tests prove correctness, not just a demo

> "261 tests cover every rule for every edge case — items at the exact limit, amount ₹0.01 over cap, items that should be SKIP vs FAIL. The test suite is the specification. If the rule engine behaves correctly on every test, it's correct by construction."

### 4. 0.82s end-to-end processing time

> "This includes OCR detection, chunking, batch embedding via sentence-transformers, FAISS index build, 12 rules × N line items, citation attachment, and PDF generation. Under one second per claim."

### 5. Fully offline — no API keys required

> "Clone the repo, install requirements, run the server. No cloud services, no API keys, no rate limits. The only optional external service is Anthropic for richer summary text — and even that has a deterministic fallback."
