"""Citation Engine — builds, attaches, and formats policy citations.

Pure utility layer. No imports from rule_engine or decision_engine.
Transforms PolicyChunks into Citation objects and attaches them to
FAIL rule results that lack citations.
"""

from app.models import Citation, PolicyChunk, RuleVerdict
from app.models.rule import LineItemResult, RuleResult


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


# ── Attach citations to FAIL rules ─────────────────────────────────


def attach_citations(
    line_item_results: list[LineItemResult],
    matched_chunks_per_item: dict[int, list[PolicyChunk]],
) -> list[LineItemResult]:
    """Attach policy citations to FAIL rules that lack them.

    For each LineItemResult, finds RuleResults with verdict=FAIL and
    empty citations list, then attaches a citation from the best-matching
    chunk (first in the list, since chunks are sorted closest-first).

    Rules that already have citations are NOT overwritten.
    PASS and SKIP rules are never touched.

    Args:
        line_item_results: Results from run_rules().
        matched_chunks_per_item: Dict mapping item_id → matched PolicyChunks.

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
            if not chunks:
                continue  # No chunks available

            # Attach citation from the closest-matching chunk
            citation = build_citation(chunks[0], l2_distance=0.0)
            rule_result.citations.append(citation)

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
