"""Dev seeding helper for stub authentication - PR-4A hotfix."""

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.engine import get_async_engine
from backend.app.db.models import Org, User

# Fixed IDs matching stub auth in backend/app/api/auth.py
DEV_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEV_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


async def seed_dev_org_and_user() -> None:
    """Seed dev org and user for stub authentication.

    This function is idempotent - safe to run multiple times.
    Creates:
    - Org with id DEV_ORG_ID if it doesn't exist
    - User with id DEV_USER_ID if it doesn't exist
    """
    async with AsyncSession(get_async_engine()) as session:
        # Check if org exists
        result = await session.execute(select(Org).where(Org.org_id == DEV_ORG_ID))
        org = result.scalar_one_or_none()

        if not org:
            print(f"Creating dev org with id {DEV_ORG_ID}...")
            org = Org(org_id=DEV_ORG_ID, name="Dev Org 1")
            session.add(org)
        else:
            print(f"Dev org already exists: {org.name}")

        # Check if user exists
        user_result = await session.execute(
            select(User).where(User.user_id == DEV_USER_ID)
        )
        user = user_result.scalar_one_or_none()

        if not user:
            print(f"Creating dev user with id {DEV_USER_ID}...")
            user = User(
                user_id=DEV_USER_ID,
                org_id=DEV_ORG_ID,
                email="dev@example.com",
                password_hash="stub",  # Not used in stub auth
            )
            session.add(user)
        else:
            print(f"Dev user already exists: {user.email}")

        await session.commit()
        print("✅ Dev seeding complete")


if __name__ == "__main__":
    asyncio.run(seed_dev_org_and_user())
