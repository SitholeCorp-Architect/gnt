"""Entitlement seam — self-host build. The hosted build's version of this
module gates access behind a Stripe-backed trial/subscription check and
tiered action caps (see gnt.ai). Self-hosting your own instance means you
already own the infrastructure, so there's nothing to meter: every org is
always entitled, and the action cap is a no-op.

action_check.py, mcp_server/auth.py, routers/rules.py, and
routers/skill_packs.py import ONLY from this module, never from a billing
module directly, so this is the one file a fork needs to touch to change
that behavior — everything downstream of it stays the same.

Interface (must keep these 4 names and signatures):
- is_org_entitled(session, org_id) -> bool
- require_entitled_org(...) -> OrgContext   [FastAPI dependency]
- require_entitled_admin(...) -> OrgContext  [FastAPI dependency]
- enforce_plan_action_cap(org_id, *, today=None) -> None  [raises PlanActionCapExceededError]
"""

from datetime import date

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from gnt.auth.better_auth import OrgContext, get_current_org, require_admin
from gnt.db.session import get_session


class PlanActionCapExceededError(RuntimeError):
    """Kept for interface parity with the hosted build -- never raised
    here, since self-host has no plan-based action cap to exceed."""


async def is_org_entitled(session: AsyncSession, org_id: str) -> bool:
    return True


async def require_entitled_org(
    org: OrgContext = Depends(get_current_org),
    session: AsyncSession = Depends(get_session),
) -> OrgContext:
    return org


async def require_entitled_admin(
    org: OrgContext = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> OrgContext:
    return org


async def enforce_plan_action_cap(org_id: str, *, today: date | None = None) -> None:
    return None


__all__ = [
    "is_org_entitled",
    "require_entitled_org",
    "require_entitled_admin",
    "enforce_plan_action_cap",
    "PlanActionCapExceededError",
]
