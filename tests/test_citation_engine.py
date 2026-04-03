"""Tests for the Citation Engine — build, attach, format, summarize.

18+ tests organized by function.
"""

import pytest

from app.models import Citation, PolicyChunk, RuleVerdict
from app.models.rule import LineItemResult, RuleResult
from app.services.citation_engine import (
    attach_citations,
    build_citation,
    citation_summary,
    format_citation_text,
)


# ─── Helpers ────────────────────────────────────────────────────────


def _chunk(
    page: int = 5,
    para: int = 3,
    section: str = "Exclusions",
    text: str = "The insurer shall not be liable for cosmetic procedures.",
) -> PolicyChunk:
    return PolicyChunk(
        chunk_id=f"p{page}_para{para}",
        policy_id="POL-001",
        page_number=page,
        paragraph_number=para,
        text=text,
        section_title=section,
    )


def _rule_result(
    verdict: RuleVerdict = RuleVerdict.FAIL,
    citations: list[Citation] | None = None,
    amount: float = 50000.0,
) -> RuleResult:
    return RuleResult(
        rule_name="R01_exclusion_check",
        rule_description="Check exclusions",
        item_id=1,
        verdict=verdict,
        reason="Test reason",
        original_amount=amount,
        approved_amount=0.0 if verdict == RuleVerdict.FAIL else amount,
        citations=citations or [],
    )


def _line_item_result(
    item_id: int = 1,
    rule_results: list[RuleResult] | None = None,
    amount: float = 50000.0,
) -> LineItemResult:
    return LineItemResult(
        item_id=item_id,
        item_description="Surgery charge",
        original_amount=amount,
        approved_amount=amount,
        rule_results=rule_results or [],
    )


# ─── TestBuildCitation ──────────────────────────────────────────────


class TestBuildCitation:
    def test_maps_fields_correctly(self):
        chunk = _chunk(page=8, para=2, section="Room Rent")
        c = build_citation(chunk)
        assert c.page_number == 8
        assert c.paragraph_number == 2
        assert c.section_title == "Room Rent"

    def test_clause_text_is_full_chunk_text(self):
        chunk = _chunk(text="Full policy text without truncation.")
        c = build_citation(chunk)
        assert c.clause_text == "Full policy text without truncation."

    def test_relevance_score_1_at_distance_0(self):
        c = build_citation(_chunk(), l2_distance=0.0)
        assert c.relevance_score == 1.0

    def test_relevance_score_0_5_at_distance_1(self):
        c = build_citation(_chunk(), l2_distance=1.0)
        assert c.relevance_score == 0.5

    def test_relevance_score_clamped_at_0(self):
        c = build_citation(_chunk(), l2_distance=2.0)
        assert c.relevance_score == 0.0
        # Even higher distance stays at 0
        c2 = build_citation(_chunk(), l2_distance=5.0)
        assert c2.relevance_score == 0.0


# ─── TestAttachCitations ───────────────────────────────────────────


class TestAttachCitations:
    def test_populates_fail_rules_with_empty_citations(self):
        fail_rule = _rule_result(verdict=RuleVerdict.FAIL, citations=[])
        item = _line_item_result(item_id=1, rule_results=[fail_rule])
        chunks = {1: [_chunk()]}
        attach_citations([item], chunks)
        assert len(fail_rule.citations) == 1

    def test_does_not_overwrite_existing_citations(self):
        existing = build_citation(_chunk(page=99, para=99))
        fail_rule = _rule_result(verdict=RuleVerdict.FAIL, citations=[existing])
        item = _line_item_result(item_id=1, rule_results=[fail_rule])
        chunks = {1: [_chunk(page=1, para=1)]}
        attach_citations([item], chunks)
        # Should still be the original citation, not replaced
        assert len(fail_rule.citations) == 1
        assert fail_rule.citations[0].page_number == 99

    def test_does_not_touch_pass_rules(self):
        pass_rule = _rule_result(verdict=RuleVerdict.PASS)
        item = _line_item_result(item_id=1, rule_results=[pass_rule])
        chunks = {1: [_chunk()]}
        attach_citations([item], chunks)
        assert pass_rule.citations == []

    def test_does_not_touch_skip_rules(self):
        skip_rule = _rule_result(verdict=RuleVerdict.SKIP)
        item = _line_item_result(item_id=1, rule_results=[skip_rule])
        chunks = {1: [_chunk()]}
        attach_citations([item], chunks)
        assert skip_rule.citations == []

    def test_no_chunks_leaves_citations_empty(self):
        fail_rule = _rule_result(verdict=RuleVerdict.FAIL)
        item = _line_item_result(item_id=1, rule_results=[fail_rule])
        attach_citations([item], {})
        assert fail_rule.citations == []

    def test_returns_same_list_object(self):
        items = [_line_item_result()]
        result = attach_citations(items, {})
        assert result is items

    def test_multiple_fail_rules_each_get_citation(self):
        fail1 = _rule_result(verdict=RuleVerdict.FAIL, citations=[])
        fail2 = _rule_result(verdict=RuleVerdict.FAIL, citations=[])
        fail2.rule_name = "R04_pre_existing"
        item = _line_item_result(item_id=1, rule_results=[fail1, fail2])
        chunks = {1: [_chunk()]}
        attach_citations([item], chunks)
        assert len(fail1.citations) == 1
        assert len(fail2.citations) == 1


# ─── TestFormatCitationText ─────────────────────────────────────────


class TestFormatCitationText:
    def test_correct_format(self):
        c = build_citation(_chunk(page=18, para=2, section="General Exclusions",
                                  text="Short clause text."))
        result = format_citation_text(c)
        assert result == 'Page 18, General Exclusions, Paragraph 2: "Short clause text."'

    def test_long_text_truncated(self):
        long_text = "A" * 150
        c = build_citation(_chunk(text=long_text))
        result = format_citation_text(c)
        assert result.endswith('..."')
        # The truncated text should be 120 chars + "..."
        assert "A" * 120 + "..." in result

    def test_exactly_120_chars_not_truncated(self):
        text_120 = "B" * 120
        c = build_citation(_chunk(text=text_120))
        result = format_citation_text(c)
        assert "..." not in result
        assert text_120 in result


# ─── TestCitationSummary ───────────────────────────────────────────


class TestCitationSummary:
    def test_empty_list(self):
        assert citation_summary([]) == "No policy clauses cited."

    def test_single_citation(self):
        c = build_citation(_chunk(page=3, para=1, section="Limits",
                                  text="Room rent capped at 1%."))
        result = citation_summary([c])
        assert result.startswith("1 policy clause cited:")
        assert "Page 3" in result

    def test_multiple_citations(self):
        c1 = build_citation(_chunk(page=3, para=1, section="Limits",
                                   text="Room rent capped."))
        c2 = build_citation(_chunk(page=5, para=2, section="Exclusions",
                                   text="Cosmetic surgery excluded."))
        result = citation_summary([c1, c2])
        assert result.startswith("2 policy clauses cited:")
        assert "  •" in result
        assert "Page 3" in result
        assert "Page 5" in result
