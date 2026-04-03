"""Smoke tests for the synthetic evaluation dataset.

Validates data integrity only — no pipeline execution.
These tests run WITHOUT embedding calls.
"""

import json
from pathlib import Path

import pytest

BASE = Path("data/synthetic")

REQUIRED_GT_KEYS = {
    "test_id", "bill_file", "policy_file", "metadata_file",
    "expected_status", "expected_rules_fired",
}

REQUIRED_META_KEYS = {"policy_id"}


@pytest.fixture(scope="module")
def ground_truth() -> list[dict]:
    gt_path = BASE / "ground_truth.json"
    return json.loads(gt_path.read_text(encoding="utf-8"))


class TestDataIntegrity:
    def test_ground_truth_exists(self):
        assert (BASE / "ground_truth.json").exists()

    def test_ground_truth_has_25_entries(self, ground_truth):
        assert len(ground_truth) == 25

    def test_entries_have_required_keys(self, ground_truth):
        for entry in ground_truth:
            missing = REQUIRED_GT_KEYS - set(entry.keys())
            assert not missing, f"{entry.get('test_id', '?')}: missing {missing}"

    def test_all_bill_pdfs_exist(self, ground_truth):
        for entry in ground_truth:
            bill_path = BASE / "bills" / entry["bill_file"]
            assert bill_path.exists(), f"Missing: {bill_path}"

    def test_all_policy_pdfs_exist(self, ground_truth):
        policies = {e["policy_file"] for e in ground_truth}
        for p in policies:
            path = BASE / "policies" / p
            assert path.exists(), f"Missing: {path}"

    def test_all_metadata_jsons_valid(self, ground_truth):
        meta_files = {e["metadata_file"] for e in ground_truth}
        for mf in meta_files:
            path = BASE / mf
            assert path.exists(), f"Missing: {path}"
            data = json.loads(path.read_text(encoding="utf-8"))
            missing = REQUIRED_META_KEYS - set(data.keys())
            assert not missing, f"{mf}: missing {missing}"
