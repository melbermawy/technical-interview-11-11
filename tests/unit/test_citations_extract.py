"""Tests for citation extraction (PR-8A)."""

from datetime import datetime

from backend.app.citations.extract import extract_citations_from_choices
from backend.app.models.common import ChoiceKind, Provenance
from backend.app.models.plan import Choice, ChoiceFeatures


def make_choice(
    option_ref: str,
    source: str = "tool",
    ref_id: str | None = None,
    kind: ChoiceKind = ChoiceKind.attraction,
) -> Choice:
    """Helper to create test choice."""
    return Choice(
        kind=kind,
        option_ref=option_ref,
        features=ChoiceFeatures(cost_usd_cents=1000),
        provenance=Provenance(
            source=source,
            ref_id=ref_id or option_ref,
            fetched_at=datetime.utcnow(),
        ),
    )


def test_extract_citations_from_empty_list() -> None:
    """Test that empty choices list returns empty citations."""
    citations = extract_citations_from_choices([])
    assert citations == []


def test_extract_citations_from_single_choice() -> None:
    """Test extracting citation from single choice."""
    choices = [make_choice("louvre_001", source="tool", ref_id="louvre_001")]

    citations = extract_citations_from_choices(choices)

    assert len(citations) == 1
    assert citations[0].claim == "attraction: louvre_001"
    assert citations[0].provenance.source == "tool"
    assert citations[0].provenance.ref_id == "louvre_001"


def test_extract_citations_from_multiple_choices() -> None:
    """Test extracting citations from multiple choices."""
    choices = [
        make_choice("louvre_001", source="tool", ref_id="louvre_001"),
        make_choice("restaurant_002", source="tool", ref_id="restaurant_002"),
        make_choice("hotel_003", source="manual", ref_id="hotel_003", kind=ChoiceKind.lodging),
    ]

    citations = extract_citations_from_choices(choices)

    assert len(citations) == 3
    # Check that all citations are present
    claims = {c.claim for c in citations}
    assert "attraction: louvre_001" in claims
    assert "attraction: restaurant_002" in claims
    assert "lodging: hotel_003" in claims


def test_extract_citations_deduplicates_by_source_and_ref() -> None:
    """Test that duplicate (source, ref_id) pairs are deduplicated."""
    choices = [
        make_choice("louvre_001", source="tool", ref_id="same_ref"),
        make_choice("louvre_002", source="tool", ref_id="same_ref"),  # Same source+ref
        make_choice("louvre_003", source="manual", ref_id="same_ref"),  # Different source
    ]

    citations = extract_citations_from_choices(choices)

    # Should have 2 citations: tool#same_ref and manual#same_ref
    assert len(citations) == 2

    sources = {c.provenance.source for c in citations}
    assert sources == {"tool", "manual"}


def test_extract_citations_sorts_deterministically() -> None:
    """Test that citations are sorted deterministically by source then ref_id."""
    choices = [
        make_choice("choice3", source="tool", ref_id="ref_c"),
        make_choice("choice1", source="manual", ref_id="ref_a"),
        make_choice("choice2", source="tool", ref_id="ref_a"),
    ]

    citations = extract_citations_from_choices(choices)

    # Should be sorted: (manual, ref_a), (tool, ref_a), (tool, ref_c)
    assert len(citations) == 3
    assert citations[0].provenance.source == "manual"
    assert citations[0].provenance.ref_id == "ref_a"
    assert citations[1].provenance.source == "tool"
    assert citations[1].provenance.ref_id == "ref_a"
    assert citations[2].provenance.source == "tool"
    assert citations[2].provenance.ref_id == "ref_c"


def test_extract_citations_handles_none_ref_id() -> None:
    """Test that None ref_id is handled gracefully."""
    # When ref_id is None, make_choice uses option_ref as fallback
    choices = [
        Choice(
            kind=ChoiceKind.attraction,
            option_ref="choice1",
            features=ChoiceFeatures(cost_usd_cents=1000),
            provenance=Provenance(
                source="tool",
                ref_id=None,  # Explicitly None
                fetched_at=datetime.utcnow(),
            ),
        ),
    ]

    citations = extract_citations_from_choices(choices)

    assert len(citations) == 1
    # Citation preserves the None ref_id from original provenance
    assert citations[0].provenance.ref_id is None


def test_extract_citations_preserves_full_provenance() -> None:
    """Test that full provenance metadata is preserved in citations."""
    fetched_time = datetime(2025, 6, 10, 12, 0, 0)
    choices = [
        Choice(
            kind=ChoiceKind.attraction,
            option_ref="test_choice",
            features=ChoiceFeatures(cost_usd_cents=1000),
            provenance=Provenance(
                source="tool",
                ref_id="test_ref",
                fetched_at=fetched_time,
                cache_hit=True,
            ),
        )
    ]

    citations = extract_citations_from_choices(choices)

    assert len(citations) == 1
    prov = citations[0].provenance
    assert prov.source == "tool"
    assert prov.ref_id == "test_ref"
    assert prov.fetched_at == fetched_time
    assert prov.cache_hit is True


def test_extract_citations_claim_includes_kind_and_ref() -> None:
    """Test that citation claim includes both kind and option_ref."""
    choices = [
        Choice(
            kind=ChoiceKind.flight,
            option_ref="AF123",
            features=ChoiceFeatures(cost_usd_cents=50000),
            provenance=Provenance(source="tool", ref_id="flight_ref", fetched_at=datetime.utcnow()),
        ),
        Choice(
            kind=ChoiceKind.lodging,
            option_ref="HotelParis",
            features=ChoiceFeatures(cost_usd_cents=15000),
            provenance=Provenance(
                source="manual", ref_id="hotel_ref", fetched_at=datetime.utcnow()
            ),
        ),
    ]

    citations = extract_citations_from_choices(choices)

    assert len(citations) == 2
    claims = {c.claim for c in citations}
    assert "flight: AF123" in claims
    assert "lodging: HotelParis" in claims


def test_extract_citations_multiple_calls_deterministic() -> None:
    """Test that multiple calls with same input produce same output."""
    choices = [
        make_choice("choice1", source="tool", ref_id="ref1"),
        make_choice("choice2", source="manual", ref_id="ref2"),
    ]

    citations1 = extract_citations_from_choices(choices)
    citations2 = extract_citations_from_choices(choices)

    assert len(citations1) == len(citations2)
    for c1, c2 in zip(citations1, citations2, strict=True):
        assert c1.claim == c2.claim
        assert c1.provenance.source == c2.provenance.source
        assert c1.provenance.ref_id == c2.provenance.ref_id
