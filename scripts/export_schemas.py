"""Export JSON schemas for PlanV1 and ItineraryV1."""

import json
from pathlib import Path

from backend.app.models import ItineraryV1, PlanV1


def main() -> None:
    """Export schemas to docs/schemas/."""
    schemas_dir = Path("docs/schemas")
    schemas_dir.mkdir(parents=True, exist_ok=True)

    # Export PlanV1 schema
    plan_schema = PlanV1.model_json_schema()
    plan_path = schemas_dir / "PlanV1.schema.json"
    with open(plan_path, "w") as f:
        json.dump(plan_schema, f, indent=2)
    print(f"Exported PlanV1 schema to {plan_path}")

    # Export ItineraryV1 schema
    itinerary_schema = ItineraryV1.model_json_schema()
    itinerary_path = schemas_dir / "ItineraryV1.schema.json"
    with open(itinerary_path, "w") as f:
        json.dump(itinerary_schema, f, indent=2)
    print(f"Exported ItineraryV1 schema to {itinerary_path}")


if __name__ == "__main__":
    main()
