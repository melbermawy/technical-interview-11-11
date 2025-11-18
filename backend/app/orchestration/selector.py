"""Real selector node implementation for PR-6B.

Scores Choice objects using only ChoiceFeatures, selects top-k, and logs decisions.
"""

from typing import Any

from backend.app.models.common import ChoiceKind
from backend.app.models.intent import IntentV1
from backend.app.models.plan import Choice


def score_choice(choice: Choice, *, intent: IntentV1) -> float:
    """Score a Choice based on its features and user intent.

    Scoring components:
    1. Cost fit: Penalize choices that consume too much of the budget
    2. Duration penalty: Penalize excessively long travel times
    3. Theme alignment: Reward choices matching user preferences
    4. Indoor/outdoor: Slight preference based on weather or preferences

    Args:
        choice: Choice object with populated ChoiceFeatures
        intent: User intent with budget and preferences

    Returns:
        Float score (higher is better), typically in range [0, 1]
    """
    features = choice.features
    score = 1.0  # Start with perfect score

    # Component 1: Cost fit
    # Penalize based on % of budget consumed
    budget_usd = intent.budget_usd_cents / 100.0
    cost_usd = features.cost_usd_cents / 100.0

    if budget_usd > 0:
        cost_ratio = cost_usd / budget_usd
        if choice.kind == ChoiceKind.flight:
            # Flights can consume up to 40% of budget reasonably
            cost_penalty = max(0, (cost_ratio - 0.4) * 2.0)
        elif choice.kind == ChoiceKind.lodging:
            # Lodging can consume up to 30% of budget reasonably
            cost_penalty = max(0, (cost_ratio - 0.3) * 2.0)
        else:
            # Attractions/transit should be much cheaper
            cost_penalty = max(0, (cost_ratio - 0.1) * 3.0)

        score -= min(cost_penalty, 0.5)  # Cap penalty at 0.5

    # Component 2: Duration penalty
    if features.travel_seconds is not None:
        travel_hours = features.travel_seconds / 3600.0
        if choice.kind == ChoiceKind.flight:
            # Penalize flights over 12 hours
            if travel_hours > 12:
                score -= min((travel_hours - 12) * 0.03, 0.3)
        elif choice.kind == ChoiceKind.transit:
            # Penalize transit over 1 hour
            if travel_hours > 1:
                score -= min((travel_hours - 1) * 0.1, 0.2)

    # Component 3: Theme alignment
    if intent.prefs.themes and features.themes:
        # Reward if any theme matches user preferences
        matching_themes = set(features.themes) & set(intent.prefs.themes)
        if matching_themes:
            score += 0.15 * min(len(matching_themes), 2)  # Max +0.3 for theme match

    # Component 4: Kid-friendly alignment
    if intent.prefs.kid_friendly and "kid_friendly" in features.themes:
        score += 0.1

    # Ensure score stays in reasonable range
    return max(0.0, min(1.0, score))


def _score_components(choice: Choice, *, intent: IntentV1) -> dict[str, Any]:
    """Compute detailed score components for logging.

    Returns dict with component names and their contributions.
    """
    features = choice.features
    components: dict[str, Any] = {}

    # Cost component
    budget_usd = intent.budget_usd_cents / 100.0
    cost_usd = features.cost_usd_cents / 100.0
    if budget_usd > 0:
        cost_ratio = cost_usd / budget_usd
        components["cost_ratio"] = round(cost_ratio, 3)

        if choice.kind == ChoiceKind.flight:
            cost_penalty = max(0, (cost_ratio - 0.4) * 2.0)
        elif choice.kind == ChoiceKind.lodging:
            cost_penalty = max(0, (cost_ratio - 0.3) * 2.0)
        else:
            cost_penalty = max(0, (cost_ratio - 0.1) * 3.0)

        components["cost_penalty"] = round(-min(cost_penalty, 0.5), 3)

    # Duration component
    if features.travel_seconds is not None:
        travel_hours = features.travel_seconds / 3600.0
        components["travel_hours"] = round(travel_hours, 3)

        if choice.kind == ChoiceKind.flight and travel_hours > 12:
            components["duration_penalty"] = round(-min((travel_hours - 12) * 0.03, 0.3), 3)
        elif choice.kind == ChoiceKind.transit and travel_hours > 1:
            components["duration_penalty"] = round(-min((travel_hours - 1) * 0.1, 0.2), 3)

    # Theme component
    if intent.prefs.themes and features.themes:
        matching_themes = set(features.themes) & set(intent.prefs.themes)
        if matching_themes:
            components["theme_bonus"] = round(0.15 * min(len(matching_themes), 2), 3)
            components["matching_themes"] = sorted(matching_themes)

    # Kid-friendly component
    if intent.prefs.kid_friendly and "kid_friendly" in features.themes:
        components["kid_friendly_bonus"] = 0.1

    return components


def select_best_choices(
    *,
    choices: list[Choice],
    intent: IntentV1,
    max_selected: int = 10,
) -> tuple[list[Choice], list[dict[str, Any]]]:
    """Select top-k choices by score and generate decision logs.

    Args:
        choices: List of Choice objects to score and select from
        intent: User intent for scoring
        max_selected: Maximum number of choices to select (default: 10)

    Returns:
        Tuple of:
        - List of selected Choice objects with .score populated
        - List of decision log entries (one per ChoiceKind if applicable)
    """
    if not choices:
        return [], []

    # Score all choices
    scored_choices: list[tuple[Choice, float, dict[str, Any]]] = []
    for choice in choices:
        score = score_choice(choice, intent=intent)
        components = _score_components(choice, intent=intent)
        scored_choices.append((choice, score, components))

    # Sort by score descending, then by option_ref for determinism
    scored_choices.sort(key=lambda x: (-x[1], x[0].option_ref))

    # Select top-k
    selected_tuples = scored_choices[:max_selected]
    rejected_tuples = scored_choices[max_selected:]

    # Build selected list with scores populated
    selected: list[Choice] = []
    for choice, score, _ in selected_tuples:
        # Create new Choice with score populated
        choice_with_score = Choice(
            kind=choice.kind,
            option_ref=choice.option_ref,
            features=choice.features,
            score=score,
            provenance=choice.provenance,
        )
        selected.append(choice_with_score)

    # Build decision logs (group by kind for meaningful logging)
    logs: list[dict[str, Any]] = []
    kinds_seen = set()

    for choice, score, components in selected_tuples:
        if choice.kind in kinds_seen:
            continue
        kinds_seen.add(choice.kind)

        # Find top 2 rejected for this kind
        rejected_for_kind = [
            (c, s, comp) for c, s, comp in rejected_tuples if c.kind == choice.kind
        ][:2]

        log_entry: dict[str, Any] = {
            "kind": choice.kind.value,
            "chosen": {
                "option_ref": choice.option_ref,
                "score": round(score, 4),
                "components": components,
            },
            "rejected": [
                {
                    "option_ref": c.option_ref,
                    "score": round(s, 4),
                    "components": comp,
                }
                for c, s, comp in rejected_for_kind
            ],
        }
        logs.append(log_entry)

    return selected, logs
