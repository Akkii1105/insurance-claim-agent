"""Citation Engine — builds, attaches, and formats policy citations.

Pure utility layer. No imports from rule_engine or decision_engine.
Transforms PolicyChunks into Citation objects and attaches them to
FAIL rule results that lack citations.

Includes a fallback mechanism: when FAISS semantic search returns no
matched chunks for a failed rule, the engine searches ALL policy chunks
by section-title keywords relevant to the rule type, ensuring every
rejection has an exact page-and-paragraph citation.
"""

import logging
from typing import Optional

from app.models import Citation, PolicyChunk, RuleVerdict
from app.models.rule import LineItemResult, RuleResult

logger = logging.getLogger(__name__)


# ── Rule → Section keyword mapping for fallback citations ───────────
# When FAISS returns no matched chunks, we search all policy chunks
# for a section title that matches the rule's domain.

_RULE_SECTION_KEYWORDS: dict[str, list[str]] = {
    "R01_exclusion_check": ["exclusion", "excluded", "not covered", "not liable"],
    "R02_waiting_period": ["waiting period", "waiting", "commencement", "coverage begins"],
    "R03_room_icu_sublimit": ["room rent", "room", "icu", "sub-limit", "accommodation"],
    "R04_pre_existing_condition": ["pre-existing", "pre existing", "pre_existing", "prior condition"],
    "R05_claim_cap": ["sum insured", "coverage limit", "maximum", "sum assured"],
    "R06_covered_procedure": ["covered procedure", "surgical procedure", "covered"],
    "R07_day_care_check": ["day care", "day-care", "daycare", "24 hour"],
    "R08_consumables_exclusion": ["consumable", "disposable", "non-reusable"],
    "R09_co_payment": ["co-payment", "copayment", "co payment", "patient share"],
    "R10_network_hospital": ["network", "empanelled", "hospital", "non-empanelled"],
    "R11_duplicate_claim": ["duplicate", "prior claim", "re-submission"],
    "R12_document_completeness": ["document", "supporting", "required document"],
}


# ── Build a Citation from a PolicyChunk ─────────────────────────────


def build_citation(
    chunk: PolicyChunk,
    l2_distance: float = 0.0,
) -> Citation:
    """Construct a Citation from a PolicyChunk.

    Converts L2 distance to a 0–1 relevance score:
        distance 0.0 → score 1.0
        distance 2.0 → score 0.0
        Clamped at 0.0 minimum.

    Args:
        chunk: The policy chunk to cite.
        l2_distance: L2 distance from FAISS search (lower = more relevant).

    Returns:
        A fully populated Citation object.
    """
    relevance_score = max(0.0, round(1.0 - (l2_distance / 2.0), 4))

    return Citation(
        policy_id=chunk.policy_id,
        chunk_id=chunk.chunk_id,
        page_number=chunk.page_number,
        paragraph_number=chunk.paragraph_number,
        section_title=chunk.section_title,
        clause_text=chunk.text,
        relevance_score=relevance_score,
    )


# ── Fallback: find a chunk by section-title keywords ────────────────


def _find_fallback_chunk(
    rule_name: str,
    all_chunks: list[PolicyChunk],
) -> Optional[PolicyChunk]:
    """Find the best fallback chunk by matching rule-specific keywords
    against chunk section titles and text.

    Args:
        rule_name: The rule name (e.g. "R01_exclusion_check").
        all_chunks: All policy chunks (not just FAISS-matched ones).

    Returns:
        The best matching PolicyChunk, or None if no match found.
    """
    keywords = _RULE_SECTION_KEYWORDS.get(rule_name, [])
    if not keywords or not all_chunks:
        return None

    # First pass: match against section_title (strongest signal)
    for chunk in all_chunks:
        if chunk.section_title:
            title_lower = chunk.section_title.lower()
            for kw in keywords:
                if kw in title_lower:
                    return chunk

    # Second pass: match against chunk text body
    for chunk in all_chunks:
        text_lower = chunk.text.lower()
        for kw in keywords:
            if kw in text_lower:
                return chunk

    return None


def _extract_title_from_text(text: str) -> Optional[str]:
    """Extract an ALL-CAPS section title from the beginning of a chunk.

    Many PDF extractors merge the heading into the paragraph body,
    producing text like:
        "GENERAL EXCLUSIONS The insurer shall not be liable..."

    This function finds the ALL CAPS prefix and converts it to title case.

    Args:
        text: The chunk's full text.

    Returns:
        Title-cased section name (e.g. "General Exclusions"), or None.
    """
    import re
    # Match 2+ ALL-CAPS words at the start, followed by non-caps text
    match = re.match(r'^([A-Z][A-Z\s\-&/]{3,}[A-Z])\s+[A-Z][a-z]', text)
    if match:
        raw_title = match.group(1).strip()
        # Convert "GENERAL EXCLUSIONS" → "General Exclusions"
        return raw_title.title()
    return None


# ── Attach citations to FAIL rules ─────────────────────────────────


def attach_citations(
    line_item_results: list[LineItemResult],
    matched_chunks_per_item: dict[int, list[PolicyChunk]],
    all_chunks: list[PolicyChunk] | None = None,
) -> list[LineItemResult]:
    """Attach policy citations to FAIL rules that lack them.

    For each LineItemResult, finds RuleResults with verdict=FAIL and
    empty citations list, then attaches a citation from the best-matching
    chunk (first in the list, since chunks are sorted closest-first).

    Fallback: if no FAISS-matched chunks exist for an item, searches
    all_chunks by section-title keywords relevant to the rule type.
    This ensures every rejection has an exact page-and-paragraph citation.

    Rules that already have citations are NOT overwritten.
    PASS and SKIP rules are never touched.

    Args:
        line_item_results: Results from run_rules().
        matched_chunks_per_item: Dict mapping item_id → matched PolicyChunks.
        all_chunks: All policy chunks for fallback citation search.

    Returns:
        The same list (mutated in place).
    """
    for item_result in line_item_results:
        chunks = matched_chunks_per_item.get(item_result.item_id, [])

        for rule_result in item_result.rule_results:
            # Only touch FAIL rules with no citations
            if rule_result.verdict != RuleVerdict.FAIL:
                continue
            if rule_result.citations:  # Already has citations — don't overwrite
                continue

            if chunks:
                # Primary path: citation from FAISS-matched chunk
                citation = build_citation(chunks[0], l2_distance=0.0)
                rule_result.citations.append(citation)
            elif all_chunks:
                # Fallback path: search all chunks by section-title keywords
                fallback = _find_fallback_chunk(rule_result.rule_name, all_chunks)
                if fallback:
                    # If chunk has no section_title, try to extract it from the
                    # beginning of the chunk text (ALL CAPS prefix pattern)
                    effective_chunk = fallback
                    if not effective_chunk.section_title:
                        inferred_title = _extract_title_from_text(
                            effective_chunk.text
                        )
                        if inferred_title:
                            effective_chunk = effective_chunk.model_copy(
                                update={"section_title": inferred_title}
                            )
                    citation = build_citation(effective_chunk, l2_distance=1.0)
                    rule_result.citations.append(citation)
                    logger.info(
                        "Fallback citation for %s -> page %d, %s",
                        rule_result.rule_name,
                        effective_chunk.page_number,
                        effective_chunk.section_title or "General",
                    )

    return line_item_results


# ── Format a citation as human-readable text ────────────────────────


def format_citation_text(citation: Citation) -> str:
    """Format a Citation as a display string.

    Returns:
        Format: 'Page {n}, {section}, Paragraph {p}: "{text}"'
        Where text is truncated to 120 chars with "..." if longer.
    """
    text = citation.clause_text
    if len(text) > 120:
        text = text[:120] + "..."

    section = citation.section_title or "General"
    return (
        f'Page {citation.page_number}, {section}, '
        f'Paragraph {citation.paragraph_number}: "{text}"'
    )


# ── Summarize multiple citations ───────────────────────────────────


def citation_summary(citations: list[Citation]) -> str:
    """Produce a human-readable summary of a list of citations.

    Returns:
        - Empty list → "No policy clauses cited."
        - 1 citation → "1 policy clause cited: {formatted}"
        - 2+ citations → header + bullet list
    """
    if not citations:
        return "No policy clauses cited."

    if len(citations) == 1:
        return f"1 policy clause cited: {format_citation_text(citations[0])}"

    header = f"{len(citations)} policy clauses cited:"
    lines = [f"  • {format_citation_text(c)}" for c in citations]
    return header + "\n" + "\n".join(lines)
