"""Test tri-state boolean serialization (indoor, kid_friendly)."""

from datetime import datetime

from backend.app.models import Attraction, ChoiceFeatures, Geo, Provenance


def test_attraction_indoor_true_roundtrip() -> None:
    """Test Attraction.indoor=True round-trips correctly."""
    attraction = Attraction(
        id="test_1",
        name="Indoor Museum",
        venue_type="museum",
        indoor=True,
        kid_friendly=False,
        opening_hours={"0": [], "1": [], "2": [], "3": [], "4": [], "5": [], "6": []},
        location=Geo(lat=48.8606, lon=2.3376),
        provenance=Provenance(source="tool", fetched_at=datetime.now()),
    )

    # Serialize to dict
    data = attraction.model_dump()
    assert data["indoor"] is True

    # Deserialize back
    restored = Attraction(**data)
    assert restored.indoor is True


def test_attraction_indoor_false_roundtrip() -> None:
    """Test Attraction.indoor=False round-trips correctly."""
    attraction = Attraction(
        id="test_2",
        name="Outdoor Park",
        venue_type="park",
        indoor=False,
        kid_friendly=True,
        opening_hours={"0": [], "1": [], "2": [], "3": [], "4": [], "5": [], "6": []},
        location=Geo(lat=48.8566, lon=2.3522),
        provenance=Provenance(source="tool", fetched_at=datetime.now()),
    )

    data = attraction.model_dump()
    assert data["indoor"] is False

    restored = Attraction(**data)
    assert restored.indoor is False


def test_attraction_indoor_none_roundtrip() -> None:
    """Test Attraction.indoor=None round-trips correctly."""
    attraction = Attraction(
        id="test_3",
        name="Mixed Venue",
        venue_type="other",
        indoor=None,
        kid_friendly=None,
        opening_hours={"0": [], "1": [], "2": [], "3": [], "4": [], "5": [], "6": []},
        location=Geo(lat=48.8566, lon=2.3522),
        provenance=Provenance(source="tool", fetched_at=datetime.now()),
    )

    data = attraction.model_dump()
    assert data["indoor"] is None
    assert data["kid_friendly"] is None

    restored = Attraction(**data)
    assert restored.indoor is None
    assert restored.kid_friendly is None


def test_choice_features_indoor_true_roundtrip() -> None:
    """Test ChoiceFeatures.indoor=True round-trips correctly."""
    features = ChoiceFeatures(cost_usd_cents=5000, indoor=True, themes=["art"])

    data = features.model_dump()
    assert data["indoor"] is True

    restored = ChoiceFeatures(**data)
    assert restored.indoor is True


def test_choice_features_indoor_false_roundtrip() -> None:
    """Test ChoiceFeatures.indoor=False round-trips correctly."""
    features = ChoiceFeatures(cost_usd_cents=3000, indoor=False, themes=["outdoor"])

    data = features.model_dump()
    assert data["indoor"] is False

    restored = ChoiceFeatures(**data)
    assert restored.indoor is False


def test_choice_features_indoor_none_roundtrip() -> None:
    """Test ChoiceFeatures.indoor=None round-trips correctly."""
    features = ChoiceFeatures(cost_usd_cents=2000, indoor=None)

    data = features.model_dump()
    assert data["indoor"] is None

    restored = ChoiceFeatures(**data)
    assert restored.indoor is None


def test_attraction_json_serialization() -> None:
    """Test Attraction JSON serialization preserves tri-state."""
    attraction = Attraction(
        id="test_json",
        name="Test Venue",
        venue_type="museum",
        indoor=None,
        kid_friendly=True,
        opening_hours={"0": [], "1": [], "2": [], "3": [], "4": [], "5": [], "6": []},
        location=Geo(lat=48.8566, lon=2.3522),
        provenance=Provenance(source="tool", fetched_at=datetime.now()),
    )

    json_str = attraction.model_dump_json()
    restored = Attraction.model_validate_json(json_str)

    assert restored.indoor is None
    assert restored.kid_friendly is True
