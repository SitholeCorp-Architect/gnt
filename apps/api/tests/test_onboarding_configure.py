"""Step 8 (routers/onboarding.py's PATCH /configure) -- placeholder
check_action toggles, persisted and marked done. The real option list is
a fast-follow (founder call, plan section 6); this only covers that the
endpoint is admin-gated, persists whatever was submitted, defaults to the
stricter posture, and flips configure_completed.
"""

import pytest
from sqlalchemy import select

from gnt.db.models import Org
from gnt.db.org import ensure_org
from tests.conftest import make_org_client


@pytest.fixture
def onboarding_routers():
    from gnt.routers import onboarding as onboarding_router

    return [onboarding_router.router]


@pytest.fixture
def admin_session(test_app_factory, org_a, onboarding_routers):
    return make_org_client(test_app_factory, org_a, user_id="admin_a", role="admin", routers=onboarding_routers)


@pytest.fixture
def member_session(test_app_factory, org_a, onboarding_routers):
    return make_org_client(test_app_factory, org_a, user_id="member_a", role=None, routers=onboarding_routers)


async def test_configure_requires_admin(member_session):
    async with member_session as client:
        r = await client.patch("/v1/onboarding/configure", json={})
        assert r.status_code == 403


async def test_get_configure_returns_the_stricter_defaults_for_a_never_configured_org(
    member_session, db_session, org_a
):
    """Any member can view the Configure settings page (same as the
    connector cards on Organization settings) -- only PATCH is
    admin-gated. A never-touched org (check_action_settings still NULL)
    reads the same default posture PATCH itself falls back to, not an
    empty/null response the settings page would have nothing to render."""
    await ensure_org(db_session, org_a)
    async with member_session as client:
        r = await client.get("/v1/onboarding/configure")
        assert r.status_code == 200
        assert r.json() == {
            "block_risky_actions": True,
            "require_human_approval": True,
            "comment_with_citations": True,
        }


async def test_get_configure_reflects_a_real_saved_change(admin_session, db_session, org_a):
    await ensure_org(db_session, org_a)
    async with admin_session as client:
        await client.patch(
            "/v1/onboarding/configure",
            json={"block_risky_actions": False, "require_human_approval": True, "comment_with_citations": False},
        )
        r = await client.get("/v1/onboarding/configure")
        assert r.status_code == 200
        assert r.json() == {
            "block_risky_actions": False,
            "require_human_approval": True,
            "comment_with_citations": False,
        }


async def test_configure_defaults_to_the_stricter_posture(admin_session, db_session, org_a):
    await ensure_org(db_session, org_a)
    async with admin_session as client:
        r = await client.patch("/v1/onboarding/configure", json={})
        assert r.status_code == 200
        assert r.json() == {"ok": True}

    row = (await db_session.execute(select(Org).where(Org.id == org_a))).scalar_one()
    assert row.configure_completed is True
    assert row.check_action_settings == {
        "block_risky_actions": True,
        "require_human_approval": True,
        "comment_with_citations": True,
    }


async def test_configure_does_not_mark_onboarding_complete(admin_session, db_session, org_a):
    """Regression pin: this endpoint used to flip onboarding_completed
    itself, which let anyone finishing this step skip straight past POST
    /complete's real stripe_customer_id gate -- see this endpoint's own
    comment. Only that endpoint (test_onboarding_done.py) is allowed to
    set it true now."""
    await ensure_org(db_session, org_a)
    async with admin_session as client:
        r = await client.patch("/v1/onboarding/configure", json={})
        assert r.status_code == 200

    row = (await db_session.execute(select(Org).where(Org.id == org_a))).scalar_one()
    assert row.onboarding_completed is False


async def test_configure_persists_whatever_toggles_were_submitted(admin_session, db_session, org_a):
    await ensure_org(db_session, org_a)
    async with admin_session as client:
        r = await client.patch(
            "/v1/onboarding/configure",
            json={"block_risky_actions": False, "require_human_approval": False, "comment_with_citations": True},
        )
        assert r.status_code == 200

    row = (await db_session.execute(select(Org).where(Org.id == org_a))).scalar_one()
    assert row.check_action_settings == {
        "block_risky_actions": False,
        "require_human_approval": False,
        "comment_with_citations": True,
    }
