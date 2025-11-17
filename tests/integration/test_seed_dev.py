"""Integration tests for dev seeding helper.

NOTE: These tests verify the seeding logic works correctly.
Due to JSONB/SQLite incompatibility in the models, full integration tests
require PostgreSQL. These tests verify the seeding function can be imported
and has correct IDs defined.
"""

import uuid

from backend.app.db.seed_dev import DEV_ORG_ID, DEV_USER_ID, seed_dev_org_and_user


def test_dev_ids_match_stub_auth() -> None:
    """Test that dev IDs match the stub auth defaults."""
    # These must match the IDs in backend/app/api/auth.py
    assert DEV_ORG_ID == uuid.UUID("00000000-0000-0000-0000-000000000001")
    assert DEV_USER_ID == uuid.UUID("00000000-0000-0000-0000-000000000002")


def test_seed_function_exists() -> None:
    """Test that seed_dev_org_and_user function is importable."""
    assert callable(seed_dev_org_and_user)
    assert seed_dev_org_and_user.__doc__ is not None
