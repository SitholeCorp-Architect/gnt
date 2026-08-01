"""Step 5's repo picker (routers/onboarding.py's GET /github/repos and
POST /repos) -- lists what an org's GitHub App install granted access to
and lets it narrow that down to the subset it actually wants gnt active
on, without losing the rows for anything it unchecks.
"""

import pytest
from sqlalchemy import select

from gnt.db.models import GithubConnection
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


async def _seed_connections(db_session, org_id: str, installation_id: int = 555) -> None:
    await ensure_org(db_session, org_id)
    db_session.add_all(
        [
            GithubConnection(
                org_id=org_id,
                repo_url="https://github.com/acme/rules",
                default_branch="main",
                installation_id=installation_id,
                pat_encrypted=None,
                webhook_secret_encrypted=None,
                installed_by_user_id="admin_a",
            ),
            GithubConnection(
                org_id=org_id,
                repo_url="https://github.com/acme/other",
                default_branch="trunk",
                installation_id=installation_id,
                pat_encrypted=None,
                webhook_secret_encrypted=None,
                installed_by_user_id="admin_a",
            ),
        ]
    )
    await db_session.commit()


async def test_list_repos_is_empty_before_any_install(admin_session):
    async with admin_session as client:
        r = await client.get("/v1/onboarding/github/repos")
        assert r.status_code == 200
        assert r.json() == []


async def test_list_repos_returns_every_granted_repo_enabled_by_default(admin_session, db_session, org_a):
    await _seed_connections(db_session, org_a)
    async with admin_session as client:
        r = await client.get("/v1/onboarding/github/repos")
        assert r.status_code == 200
        body = sorted(r.json(), key=lambda row: row["repo_url"])
        assert body == [
            {"repo_url": "https://github.com/acme/other", "default_branch": "trunk", "enabled": True},
            {"repo_url": "https://github.com/acme/rules", "default_branch": "main", "enabled": True},
        ]


async def test_list_repos_excludes_a_legacy_pat_connection(admin_session, db_session, org_a):
    """installation_id NULL means the legacy PAT flow -- that single row
    never went through this picker and shouldn't show up as if it did."""
    await ensure_org(db_session, org_a)
    db_session.add(
        GithubConnection(
            org_id=org_a,
            repo_url="https://github.com/acme/pat-repo",
            default_branch="main",
            installation_id=None,
            pat_encrypted="x",
            webhook_secret_encrypted="y",
            installed_by_user_id="admin_a",
        )
    )
    await db_session.commit()

    async with admin_session as client:
        r = await client.get("/v1/onboarding/github/repos")
        assert r.status_code == 200
        assert r.json() == []


async def test_select_repos_requires_admin(member_session):
    async with member_session as client:
        r = await client.post("/v1/onboarding/repos", json={"repo_urls": ["https://github.com/acme/rules"]})
        assert r.status_code == 403


async def test_select_repos_404s_on_a_repo_url_not_owned_by_this_org(admin_session, db_session, org_a):
    await _seed_connections(db_session, org_a)
    async with admin_session as client:
        r = await client.post("/v1/onboarding/repos", json={"repo_urls": ["https://github.com/not/mine"]})
        assert r.status_code == 404


async def test_select_repos_enables_the_chosen_subset_and_disables_the_rest(admin_session, db_session, org_a):
    await _seed_connections(db_session, org_a)
    async with admin_session as client:
        r = await client.post("/v1/onboarding/repos", json={"repo_urls": ["https://github.com/acme/rules"]})
        assert r.status_code == 200
        assert r.json() == {"ok": True, "enabled_count": 1}

    rows = (
        await db_session.execute(select(GithubConnection).where(GithubConnection.org_id == org_a))
    ).scalars().all()
    by_url = {row.repo_url: row.enabled for row in rows}
    assert by_url == {
        "https://github.com/acme/rules": True,
        "https://github.com/acme/other": False,
    }
