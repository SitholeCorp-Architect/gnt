"""GET /v1/onboarding/status's onboarding_completed field -- the one real
"is this org done" signal both the web (lib/onboarding-wizard.ts's
isWizardCompleteForWeb) and the CLI now read, replacing the old
connected_cli/connected_github/rules_proposed proxy this endpoint used to
be the sole computer of. Pins that this field is a direct, honest read of
orgs.onboarding_completed -- not re-derived from anything else in this
response -- so it can never disagree with what routers/onboarding.py's own
POST /complete actually set.
"""

from sqlalchemy import select

from gnt.db.models import Org
from gnt.db.org import ensure_org
from tests.conftest import make_org_client


async def test_onboarding_completed_is_false_for_a_freshly_created_org(test_app_factory, db_session, org_a):
    """ensure_org itself sets onboarding_completed=False on creation (see
    db/org.py) -- a brand-new signup must show as not-done, or CLI/web
    would both skip the wizard for every new org."""
    await ensure_org(db_session, org_a)
    await db_session.commit()

    from gnt.routers import brain as brain_router

    async with make_org_client(test_app_factory, org_a, routers=[brain_router.router]) as client:
        r = await client.get("/v1/onboarding/status")
        assert r.status_code == 200
        assert r.json()["onboarding_completed"] is False


async def test_onboarding_completed_reflects_the_wizard_actually_finishing(test_app_factory, db_session, org_a):
    """Once the wizard flips onboarding_completed true (same row POST
    /complete gates on), this field must actually reflect that -- it isn't
    allowed to fall back on connected_cli/connected_github/rules_proposed
    the way the endpoint used to compute "done" before this field existed."""
    await ensure_org(db_session, org_a)
    row = (await db_session.execute(select(Org).where(Org.id == org_a))).scalar_one()
    row.onboarding_completed = True
    await db_session.commit()

    from gnt.routers import brain as brain_router

    async with make_org_client(test_app_factory, org_a, routers=[brain_router.router]) as client:
        r = await client.get("/v1/onboarding/status")
        assert r.status_code == 200
        assert r.json()["onboarding_completed"] is True
