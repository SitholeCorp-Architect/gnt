"""Step 10 (routers/onboarding.py's GET /summary and POST /complete) --
the done screen's stat tiles and the "no card, no completion" gate.
"""

import uuid

import pytest
from sqlalchemy import select

from gnt.db.models import GithubConnection, Org
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


async def test_summary_counts_only_enabled_repos_and_reports_the_real_mcp_url(
    admin_session, db_session, org_a
):
    # A unique repo_url per test run, not the "acme/rules" placeholder
    # several other test files (e.g. test_tasks_contradictions.py) commit
    # for real outside this fixture's rolled-back transaction -- avoids
    # colliding with a leftover row from an earlier, unrelated test run
    # against the same persistent local test database.
    suffix = uuid.uuid4().hex[:8]
    await ensure_org(db_session, org_a)
    db_session.add_all(
        [
            GithubConnection(
                org_id=org_a,
                repo_url=f"https://github.com/acme/rules-{suffix}",
                default_branch="main",
                installation_id=1,
                pat_encrypted=None,
                webhook_secret_encrypted=None,
                installed_by_user_id="admin_a",
                enabled=True,
            ),
            GithubConnection(
                org_id=org_a,
                repo_url=f"https://github.com/acme/disabled-{suffix}",
                default_branch="main",
                installation_id=1,
                pat_encrypted=None,
                webhook_secret_encrypted=None,
                installed_by_user_id="admin_a",
                enabled=False,
            ),
        ]
    )
    row = (await db_session.execute(select(Org).where(Org.id == org_a))).scalar_one()
    row.rules_imported_count = 4
    await db_session.commit()

    async with admin_session as client:
        r = await client.get("/v1/onboarding/summary")
        assert r.status_code == 200
        body = r.json()
        assert body["repos_connected"] == 1
        assert body["rules_imported"] == 4
        assert body["mcp_endpoint_url"].endswith("/mcp")


async def test_complete_requires_admin(member_session):
    async with member_session as client:
        r = await client.post("/v1/onboarding/complete")
        assert r.status_code == 403


async def test_complete_refuses_without_a_real_stripe_customer(admin_session, db_session, org_a):
    await ensure_org(db_session, org_a)
    await db_session.commit()

    async with admin_session as client:
        r = await client.post("/v1/onboarding/complete")
        assert r.status_code == 402

    row = (await db_session.execute(select(Org).where(Org.id == org_a))).scalar_one()
    assert row.onboarding_completed is False


async def test_complete_marks_onboarding_done_once_a_real_customer_exists(admin_session, db_session, org_a):
    await ensure_org(db_session, org_a)
    row = (await db_session.execute(select(Org).where(Org.id == org_a))).scalar_one()
    row.stripe_customer_id = "cus_fake123"
    await db_session.commit()

    async with admin_session as client:
        r = await client.post("/v1/onboarding/complete")
        assert r.status_code == 200
        assert r.json() == {"ok": True}

    row = (await db_session.execute(select(Org).where(Org.id == org_a))).scalar_one()
    assert row.onboarding_completed is True
