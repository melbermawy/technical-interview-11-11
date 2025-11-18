"""Citation extraction from tool provenance.

Extracts citations from Choice provenance and deduplicates them for final output.
"""

from backend.app.models.itinerary import Citation
from backend.app.models.plan import Choice


def extract_citations_from_choices(choices: list[Choice]) -> list[Citation]:
    """Extract unique citations from choice provenance.

    Args:
        choices: List of choices with provenance metadata

    Returns:
        Deduplicated list of citations, sorted for deterministic ordering
    """
    # Use dict for deduplication by (source, ref_id) key
    citation_map: dict[tuple[str, str], Citation] = {}

    for choice in choices:
        prov = choice.provenance

        # Build citation claim from choice context
        claim = f"{choice.kind.value}: {choice.option_ref}"

        # Build ref string following SPEC §9 format
        # For tools: "tool_name#id"
        # For other sources: use ref_id directly
        ref = prov.ref_id if prov.ref_id else f"{prov.source}#unknown"

        # Create citation key for deduplication
        key = (prov.source, ref)

        # Only add if not already present
        if key not in citation_map:
            citation_map[key] = Citation(
                claim=claim,
                provenance=prov,
            )

    # Sort by source then ref for deterministic ordering
    citations = sorted(
        citation_map.values(),
        key=lambda c: (c.provenance.source, c.provenance.ref_id or ""),
    )

    return citations
