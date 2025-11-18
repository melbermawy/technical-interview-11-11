"""Unit tests for what-if intent derivation (PR-9A)."""

from datetime import date

from backend.app.models.intent import DateWindow, IntentV1, Preferences
from backend.app.models.what_if import WhatIfPatch
from backend.app.orchestration.what_if import derive_intent_from_what_if


def test_budget_new_budget_overrides_delta() -> None:
    """Test that new_budget_usd_cents takes precedence over budget_delta_usd_cents."""
    base = IntentV1(
        city="Paris",
        date_window=DateWindow(start=date(2025, 6, 10), end=date(2025, 6, 14), tz="Europe/Paris"),
        budget_usd_cents=100000,
        airports=["CDG"],
        prefs=Preferences(),
    )

    patch = WhatIfPatch(
        new_budget_usd_cents=150000,
        budget_delta_usd_cents=50000,  # Should be ignored
    )

    derived = derive_intent_from_what_if(base, patch)

    assert derived.budget_usd_cents == 150000  # new_budget wins


def test_budget_delta_applied_when_no_explicit_new_budget() -> None:
    """Test that budget_delta_usd_cents is applied when new_budget_usd_cents is not set."""
    base = IntentV1(
        city="Paris",
        date_window=DateWindow(start=date(2025, 6, 10), end=date(2025, 6, 14), tz="Europe/Paris"),
        budget_usd_cents=100000,
        airports=["CDG"],
        prefs=Preferences(),
    )

    patch = WhatIfPatch(budget_delta_usd_cents=25000)

    derived = derive_intent_from_what_if(base, patch)

    assert derived.budget_usd_cents == 125000  # 100000 + 25000


def test_budget_does_not_go_negative() -> None:
    """Test that negative budget delta is clamped at 1 (min valid budget)."""
    base = IntentV1(
        city="Paris",
        date_window=DateWindow(start=date(2025, 6, 10), end=date(2025, 6, 14), tz="Europe/Paris"),
        budget_usd_cents=100000,
        airports=["CDG"],
        prefs=Preferences(),
    )

    patch = WhatIfPatch(budget_delta_usd_cents=-150000)  # Would go to -50000

    derived = derive_intent_from_what_if(base, patch)

    assert derived.budget_usd_cents == 1  # Clamped at 1 (min valid budget)


def test_themes_add_and_remove_work_and_preserve_order() -> None:
    """Test that theme add/remove operations work correctly and preserve order."""
    base = IntentV1(
        city="Paris",
        date_window=DateWindow(start=date(2025, 6, 10), end=date(2025, 6, 14), tz="Europe/Paris"),
        budget_usd_cents=100000,
        airports=["CDG"],
        prefs=Preferences(themes=["art", "food", "history"]),
    )

    patch = WhatIfPatch(
        remove_themes=["food"],
        add_themes=["architecture", "nightlife"],
    )

    derived = derive_intent_from_what_if(base, patch)

    # Should remove "food", then add new themes
    assert derived.prefs is not None
    assert derived.prefs.themes == ["art", "history", "architecture", "nightlife"]


def test_themes_add_skips_duplicates() -> None:
    """Test that adding a theme that already exists doesn't create duplicates."""
    base = IntentV1(
        city="Paris",
        date_window=DateWindow(start=date(2025, 6, 10), end=date(2025, 6, 14), tz="Europe/Paris"),
        budget_usd_cents=100000,
        airports=["CDG"],
        prefs=Preferences(themes=["art", "food"]),
    )

    patch = WhatIfPatch(add_themes=["food", "architecture"])

    derived = derive_intent_from_what_if(base, patch)

    # "food" already exists, should not be duplicated
    assert derived.prefs is not None
    assert derived.prefs.themes == ["art", "food", "architecture"]


def test_themes_handle_missing_prefs_gracefully() -> None:
    """Test that derivation works when base.prefs.themes is empty list."""
    base = IntentV1(
        city="Paris",
        date_window=DateWindow(start=date(2025, 6, 10), end=date(2025, 6, 14), tz="Europe/Paris"),
        budget_usd_cents=100000,
        airports=["CDG"],
        prefs=Preferences(themes=[]),  # Prefs with empty themes
    )

    patch = WhatIfPatch(add_themes=["art", "food"])

    derived = derive_intent_from_what_if(base, patch)

    # Should create new Preferences with added themes
    assert derived.prefs is not None
    assert derived.prefs.themes == ["art", "food"]


def test_themes_handle_empty_themes_list() -> None:
    """Test that derivation works when base.prefs.themes is empty."""
    base = IntentV1(
        city="Paris",
        date_window=DateWindow(start=date(2025, 6, 10), end=date(2025, 6, 14), tz="Europe/Paris"),
        budget_usd_cents=100000,
        airports=["CDG"],
        prefs=Preferences(themes=[]),
    )

    patch = WhatIfPatch(add_themes=["art", "food"])

    derived = derive_intent_from_what_if(base, patch)

    assert derived.prefs is not None
    assert derived.prefs.themes == ["art", "food"]


def test_shift_days_moves_start_and_end_consistently() -> None:
    """Test that shift_days moves both start and end dates by the same amount."""
    base = IntentV1(
        city="Paris",
        date_window=DateWindow(start=date(2025, 6, 10), end=date(2025, 6, 14), tz="Europe/Paris"),
        budget_usd_cents=100000,
        airports=["CDG"],
        prefs=Preferences(),
    )

    patch = WhatIfPatch(shift_days=7)

    derived = derive_intent_from_what_if(base, patch)

    assert derived.date_window.start == date(2025, 6, 17)
    assert derived.date_window.end == date(2025, 6, 21)
    assert derived.date_window.tz == "Europe/Paris"  # Timezone preserved


def test_shift_days_negative_shifts_backwards() -> None:
    """Test that negative shift_days moves dates backward."""
    base = IntentV1(
        city="Paris",
        date_window=DateWindow(start=date(2025, 6, 10), end=date(2025, 6, 14), tz="Europe/Paris"),
        budget_usd_cents=100000,
        airports=["CDG"],
        prefs=Preferences(),
    )

    patch = WhatIfPatch(shift_days=-3)

    derived = derive_intent_from_what_if(base, patch)

    assert derived.date_window.start == date(2025, 6, 7)
    assert derived.date_window.end == date(2025, 6, 11)
    assert derived.date_window.tz == "Europe/Paris"


def test_derive_intent_is_pure_and_does_not_mutate_base() -> None:
    """Test that derivation does not mutate the base intent."""
    base = IntentV1(
        city="Paris",
        date_window=DateWindow(start=date(2025, 6, 10), end=date(2025, 6, 14), tz="Europe/Paris"),
        budget_usd_cents=100000,
        airports=["CDG"],
        prefs=Preferences(themes=["art", "food"]),
    )

    # Capture original values
    original_budget = base.budget_usd_cents
    original_themes = base.prefs.themes.copy() if base.prefs and base.prefs.themes else []
    original_start = base.date_window.start
    original_end = base.date_window.end

    patch = WhatIfPatch(
        new_budget_usd_cents=150000,
        add_themes=["architecture"],
        remove_themes=["food"],
        shift_days=7,
    )

    derived = derive_intent_from_what_if(base, patch)

    # Base should be unchanged
    assert base.budget_usd_cents == original_budget
    assert base.prefs is not None
    assert base.prefs.themes == original_themes
    assert base.date_window.start == original_start
    assert base.date_window.end == original_end

    # Derived should have changes
    assert derived.budget_usd_cents == 150000
    assert derived.prefs is not None
    assert derived.prefs.themes == ["art", "architecture"]
    assert derived.date_window.start == date(2025, 6, 17)
    assert derived.date_window.end == date(2025, 6, 21)


def test_empty_patch_produces_identical_intent() -> None:
    """Test that an empty patch produces an intent with same values."""
    base = IntentV1(
        city="Paris",
        date_window=DateWindow(start=date(2025, 6, 10), end=date(2025, 6, 14), tz="Europe/Paris"),
        budget_usd_cents=100000,
        airports=["CDG"],
        prefs=Preferences(themes=["art", "food"]),
    )

    patch = WhatIfPatch()  # All fields None

    derived = derive_intent_from_what_if(base, patch)

    # Should have same values (though not same object)
    assert derived.city == base.city
    assert derived.budget_usd_cents == base.budget_usd_cents
    assert derived.airports == base.airports
    assert derived.date_window.start == base.date_window.start
    assert derived.date_window.end == base.date_window.end
    assert derived.date_window.tz == base.date_window.tz
    assert derived.prefs is not None
    assert base.prefs is not None
    assert derived.prefs.themes == base.prefs.themes


def test_airports_are_unchanged() -> None:
    """Test that airports field is always copied unchanged."""
    base = IntentV1(
        city="Paris",
        date_window=DateWindow(start=date(2025, 6, 10), end=date(2025, 6, 14), tz="Europe/Paris"),
        budget_usd_cents=100000,
        airports=["CDG", "ORY"],
        prefs=Preferences(),
    )

    patch = WhatIfPatch(new_budget_usd_cents=150000)

    derived = derive_intent_from_what_if(base, patch)

    assert derived.airports == ["CDG", "ORY"]


def test_city_is_unchanged() -> None:
    """Test that city field is always copied unchanged."""
    base = IntentV1(
        city="Paris",
        date_window=DateWindow(start=date(2025, 6, 10), end=date(2025, 6, 14), tz="Europe/Paris"),
        budget_usd_cents=100000,
        airports=["CDG"],
        prefs=Preferences(),
    )

    patch = WhatIfPatch(new_budget_usd_cents=150000)

    derived = derive_intent_from_what_if(base, patch)

    assert derived.city == "Paris"


def test_multiple_transformations_applied_together() -> None:
    """Test that multiple transformations can be applied in a single patch."""
    base = IntentV1(
        city="Tokyo",
        date_window=DateWindow(start=date(2025, 7, 1), end=date(2025, 7, 5), tz="Asia/Tokyo"),
        budget_usd_cents=200000,
        airports=["NRT"],
        prefs=Preferences(themes=["food", "temples"]),
    )

    patch = WhatIfPatch(
        budget_delta_usd_cents=50000,
        add_themes=["nightlife"],
        remove_themes=["temples"],
        shift_days=14,
    )

    derived = derive_intent_from_what_if(base, patch)

    assert derived.budget_usd_cents == 250000  # 200000 + 50000
    assert derived.prefs is not None
    assert derived.prefs.themes == ["food", "nightlife"]
    assert derived.date_window.start == date(2025, 7, 15)
    assert derived.date_window.end == date(2025, 7, 19)
    assert derived.date_window.tz == "Asia/Tokyo"


def test_remove_nonexistent_theme_is_noop() -> None:
    """Test that removing a theme that doesn't exist is a no-op."""
    base = IntentV1(
        city="Paris",
        date_window=DateWindow(start=date(2025, 6, 10), end=date(2025, 6, 14), tz="Europe/Paris"),
        budget_usd_cents=100000,
        airports=["CDG"],
        prefs=Preferences(themes=["art", "food"]),
    )

    patch = WhatIfPatch(remove_themes=["architecture"])  # Doesn't exist

    derived = derive_intent_from_what_if(base, patch)

    assert derived.prefs is not None
    assert derived.prefs.themes == ["art", "food"]  # Unchanged


def test_derivation_is_deterministic() -> None:
    """Test that applying the same patch twice produces the same result."""
    base = IntentV1(
        city="Paris",
        date_window=DateWindow(start=date(2025, 6, 10), end=date(2025, 6, 14), tz="Europe/Paris"),
        budget_usd_cents=100000,
        airports=["CDG"],
        prefs=Preferences(themes=["art"]),
    )

    patch = WhatIfPatch(
        budget_delta_usd_cents=25000,
        add_themes=["food"],
        shift_days=3,
    )

    derived1 = derive_intent_from_what_if(base, patch)
    derived2 = derive_intent_from_what_if(base, patch)

    # Should be identical
    assert derived1.budget_usd_cents == derived2.budget_usd_cents
    assert derived1.prefs is not None
    assert derived2.prefs is not None
    assert derived1.prefs.themes == derived2.prefs.themes
    assert derived1.date_window.start == derived2.date_window.start
    assert derived1.date_window.end == derived2.date_window.end
