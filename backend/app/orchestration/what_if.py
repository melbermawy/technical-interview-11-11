"""What-if intent derivation logic (PR-9A)."""

from datetime import timedelta

from backend.app.models.intent import IntentV1, Preferences
from backend.app.models.what_if import WhatIfPatch


def derive_intent_from_what_if(base: IntentV1, patch: WhatIfPatch) -> IntentV1:
    """Derive a new IntentV1 from a base intent and a what-if patch.

    This is a pure function with no I/O or side effects.
    The base intent is never mutated.

    Args:
        base: The source IntentV1 to derive from
        patch: Structured transformations to apply

    Returns:
        New IntentV1 with patch transformations applied

    Budget rules:
        - If patch.new_budget_usd_cents is set: use it (override)
        - Else if patch.budget_delta_usd_cents is set: add delta to base budget (clamped at 1)
        - Else: keep base budget

    Theme rules:
        - Start from base.prefs.themes (or [] if prefs is missing)
        - Remove all themes in patch.remove_themes (if provided)
        - Add all themes in patch.add_themes (if provided), skipping duplicates
        - Preserve order where reasonable

    Date rules:
        - If patch.shift_days is set: add that many days to both start and end
        - Timezone is preserved
    """
    # 1. Derive budget
    if patch.new_budget_usd_cents is not None:
        new_budget = patch.new_budget_usd_cents
    elif patch.budget_delta_usd_cents is not None:
        new_budget = max(1, base.budget_usd_cents + patch.budget_delta_usd_cents)
    else:
        new_budget = base.budget_usd_cents

    # 2. Derive themes
    base_themes = base.prefs.themes if base.prefs and base.prefs.themes else []
    new_themes = list(base_themes)  # Copy to avoid mutation

    # Remove themes
    if patch.remove_themes:
        new_themes = [t for t in new_themes if t not in patch.remove_themes]

    # Add themes (skip duplicates)
    if patch.add_themes:
        for theme in patch.add_themes:
            if theme not in new_themes:
                new_themes.append(theme)

    # 3. Derive date_window
    new_date_window = base.date_window.model_copy(deep=True)
    if patch.shift_days is not None:
        delta = timedelta(days=patch.shift_days)
        new_date_window.start = new_date_window.start + delta
        new_date_window.end = new_date_window.end + delta

    # 4. Build new preferences
    new_prefs = Preferences(themes=new_themes) if base.prefs else Preferences(themes=new_themes)

    # 5. Construct derived intent
    return IntentV1(
        city=base.city,
        date_window=new_date_window,
        budget_usd_cents=new_budget,
        airports=base.airports,  # Airports unchanged
        prefs=new_prefs,
    )
