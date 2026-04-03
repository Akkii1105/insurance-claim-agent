"""Run evaluation against the synthetic test dataset.

Processes all 25 test cases through the full pipeline and compares
results against ground_truth.json.

Usage: python scripts/run_evaluation.py
"""

import json
import sys
import time
from datetime import datetime, UTC
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.bill_processor import process_bill
from app.services.decision_engine import process_claim
from app.services.embedder import encode_chunks
from app.services.index_builder import build_index
from app.services.policy_processor import process_policy
from app.services.rule_engine import PolicyRuleConfig
from app.services.semantic_matcher import match_line_item


BASE = Path("data/synthetic")
REPORTS_DIR = Path("reports")


def _load_ground_truth() -> list[dict]:
    gt_path = BASE / "ground_truth.json"
    return json.loads(gt_path.read_text(encoding="utf-8"))


def _build_rule_config(metadata_path: Path) -> PolicyRuleConfig:
    """Build PolicyRuleConfig from metadata JSON."""
    raw = json.loads(metadata_path.read_text(encoding="utf-8"))
    return PolicyRuleConfig(
        policy_id=raw.get("policy_id", "UNKNOWN"),
        **{k: v for k, v in raw.items()
           if k != "policy_id" and k in PolicyRuleConfig.model_fields},
    )


def run_single_case(tc: dict) -> dict:
    """Run a single test case and return result."""
    test_id = tc["test_id"]
    bill_path = BASE / "bills" / tc["bill_file"]
    policy_path = BASE / "policies" / tc["policy_file"]
    meta_path = BASE / tc["metadata_file"]

    start = time.monotonic()

    try:
        # Full pipeline
        bill = process_bill(bill_path)
        chunks, policy_meta = process_policy(policy_path, meta_path)
        chunks = encode_chunks(chunks)

        if chunks:
            faiss_index, indexed_chunks = build_index(chunks)
        else:
            faiss_index, indexed_chunks = None, []

        matched = {}
        if faiss_index is not None:
            for item in bill.line_items:
                matched[item.item_id] = match_line_item(
                    item.description, faiss_index, indexed_chunks,
                )

        rule_config = _build_rule_config(meta_path)

        decision = process_claim(
            claim_id=test_id,
            bill=bill,
            meta=rule_config,
            matched_chunks_per_item=matched,
        )

        elapsed = time.monotonic() - start
        actual_status = decision.status.value

        # Collect fired rules (unique rule names with verdict FAIL)
        fired_rules = set()
        for lr in decision.line_item_results:
            for rr in lr.rule_results:
                if rr.verdict.value == "fail":
                    # Extract rule ID (e.g. R01 from R01_exclusion_check)
                    rule_id = rr.rule_name.split("_")[0].upper()
                    fired_rules.add(rule_id)

        # Citation pages
        citation_pages = set()
        for lr in decision.line_item_results:
            for rr in lr.rule_results:
                for cit in rr.citations:
                    citation_pages.add(cit.page_number)

        return {
            "test_id": test_id,
            "expected_status": tc["expected_status"],
            "actual_status": actual_status,
            "status_match": actual_status == tc["expected_status"],
            "expected_rules": tc["expected_rules_fired"],
            "actual_rules": sorted(fired_rules),
            "rules_match": set(tc["expected_rules_fired"]).issubset(fired_rules),
            "citation_pages": sorted(citation_pages),
            "processing_time": round(elapsed, 3),
            "error": None,
            "scenario": tc.get("scenario", ""),
        }

    except Exception as e:
        elapsed = time.monotonic() - start
        return {
            "test_id": test_id,
            "expected_status": tc["expected_status"],
            "actual_status": "ERROR",
            "status_match": False,
            "expected_rules": tc["expected_rules_fired"],
            "actual_rules": [],
            "rules_match": False,
            "citation_pages": [],
            "processing_time": round(elapsed, 3),
            "error": str(e),
            "scenario": tc.get("scenario", ""),
        }


def compute_metrics(results: list[dict]) -> dict:
    """Compute evaluation metrics."""
    total = len(results)
    correct = sum(1 for r in results if r["status_match"])

    # Rule precision: among cases with expected_rules non-empty,
    # how many had all expected rules fire
    cases_with_rules = [r for r in results if r["expected_rules"]]
    rules_correct = sum(1 for r in cases_with_rules if r["rules_match"])
    rule_precision = (rules_correct / len(cases_with_rules) * 100) if cases_with_rules else 100.0

    # False positive: clean claims (expected approved) wrongly rejected
    clean_claims = [r for r in results if r["expected_status"] == "approved"]
    false_positives = sum(1 for r in clean_claims if r["actual_status"] != "approved")
    fp_rate = (false_positives / len(clean_claims) * 100) if clean_claims else 0.0

    # False negative: invalid claims (expected non-approved) wrongly approved
    invalid_claims = [r for r in results if r["expected_status"] != "approved"]
    false_negatives = sum(1 for r in invalid_claims if r["actual_status"] == "approved")
    fn_rate = (false_negatives / len(invalid_claims) * 100) if invalid_claims else 0.0

    avg_time = sum(r["processing_time"] for r in results) / total if total else 0

    return {
        "decision_accuracy": round(correct / total * 100, 1) if total else 0,
        "rule_precision": round(rule_precision, 1),
        "false_positive_rate": round(fp_rate, 1),
        "false_negative_rate": round(fn_rate, 1),
        "avg_processing_time": round(avg_time, 3),
        "total_cases": total,
        "passed": correct,
        "failed": total - correct,
    }


def print_results(results: list[dict], metrics: dict):
    """Print formatted results table."""
    # Per-case results
    print("\n" + "=" * 85)
    print("  PER-CASE RESULTS")
    print("=" * 85)
    for r in results:
        symbol = "PASS" if r["status_match"] else "FAIL"
        marker = f"[OK] {symbol}" if r["status_match"] else f"[XX] {symbol}"
        extra = ""
        if r["error"]:
            extra = f" | ERROR: {r['error'][:50]}"
        elif not r["status_match"]:
            extra = f" | expected_rules: {r['expected_rules']} actual_rules: {r['actual_rules']}"
        print(
            f"  {r['test_id']} | expected: {r['expected_status']:20s} | "
            f"actual: {r['actual_status']:20s} | {marker} | {r['processing_time']:.2f}s{extra}"
        )

    # Summary table
    print("\n")
    print("+" + "-" * 56 + "+")
    print("|" + "  EVALUATION RESULTS SUMMARY".center(56) + "|")
    print("+" + "-" * 30 + "+" + "-" * 25 + "+")
    print(f"| {'Decision Accuracy':<28} | {metrics['decision_accuracy']:>8.1f}%{' ':>14} |")
    print(f"| {'Rule Precision':<28} | {metrics['rule_precision']:>8.1f}%{' ':>14} |")
    print(f"| {'False Positive Rate':<28} | {metrics['false_positive_rate']:>8.1f}%{' ':>14} |")
    print(f"| {'False Negative Rate':<28} | {metrics['false_negative_rate']:>8.1f}%{' ':>14} |")
    print(f"| {'Avg Processing Time':<28} | {metrics['avg_processing_time']:>8.3f}s{' ':>13} |")
    print(f"| {'Total Test Cases':<28} | {metrics['total_cases']:>8d}{' ':>15} |")
    print(f"| {'Passed':<28} | {metrics['passed']:>8d}{' ':>15} |")
    print(f"| {'Failed':<28} | {metrics['failed']:>8d}{' ':>15} |")
    print("+" + "-" * 30 + "+" + "-" * 25 + "+")


def save_results(results: list[dict], metrics: dict):
    """Save full results to reports/evaluation_results.json."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    output = {
        "metrics": metrics,
        "test_cases": results,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    out_path = REPORTS_DIR / "evaluation_results.json"
    out_path.write_text(json.dumps(output, indent=2, default=str), encoding="utf-8")
    print(f"\n  Results saved to: {out_path}")


def main():
    print("=" * 60)
    print("  Insurance Claim Agent - Evaluation Suite")
    print("=" * 60)

    gt = _load_ground_truth()
    print(f"\n  Loaded {len(gt)} test cases from ground_truth.json")
    print(f"  Processing...")

    results = []
    for i, tc in enumerate(gt):
        print(f"    [{i+1:2d}/{len(gt)}] {tc['test_id']} - {tc.get('scenario', '')[:40]}...", end="", flush=True)
        result = run_single_case(tc)
        results.append(result)
        symbol = " [OK]" if result["status_match"] else " [XX]"
        print(f"{symbol} ({result['processing_time']:.2f}s)")

    metrics = compute_metrics(results)
    print_results(results, metrics)
    save_results(results, metrics)


if __name__ == "__main__":
    main()
