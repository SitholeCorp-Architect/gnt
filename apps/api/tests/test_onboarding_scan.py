"""Steps 6-7's scan (routers/onboarding.py's POST /scan) and rules import
(POST /rules/import) -- walks an org's connected repos for AI rules files
and converts whichever ones are still checked into draft rules.
"""

import pytest
from sqlalchemy import select

from gnt.db.models import GithubConnection, Org
from gnt.db.org import ensure_org
from tests.conftest import make_org_client


@pytest.fixture
def onboarding_and_rules_routers():
    from gnt.routers import onboarding as onboarding_router
    from gnt.routers import rules as rules_router

    return [onboarding_router.router, rules_router.router]


@pytest.fixture
def admin_session(test_app_factory, org_a, onboarding_and_rules_routers):
    return make_org_client(
        test_app_factory, org_a, user_id="admin_a", role="admin", routers=onboarding_and_rules_routers
    )


@pytest.fixture
def member_session(test_app_factory, org_a, onboarding_and_rules_routers):
    return make_org_client(
        test_app_factory, org_a, user_id="member_a", role=None, routers=onboarding_and_rules_routers
    )


async def _seed_connection(db_session, org_id: str, repo_url: str = "https://github.com/acme/rules") -> None:
    await ensure_org(db_session, org_id)
    db_session.add(
        GithubConnection(
            org_id=org_id,
            repo_url=repo_url,
            default_branch="main",
            installation_id=555,
            pat_encrypted=None,
            webhook_secret_encrypted=None,
            installed_by_user_id="admin_a",
        )
    )
    await db_session.commit()


@pytest.fixture
def _fake_repo_token(monkeypatch):
    async def _get_repo_token(connection):
        return "fake-token"

    monkeypatch.setattr("gnt.onboarding_scan.get_repo_token", _get_repo_token)


async def test_scan_requires_admin(member_session):
    async with member_session as client:
        r = await client.post("/v1/onboarding/scan")
        assert r.status_code == 403


async def test_scan_409s_with_no_connected_repos(admin_session):
    async with admin_session as client:
        r = await client.post("/v1/onboarding/scan")
        assert r.status_code == 409


async def test_scan_returns_only_matching_rule_files_at_any_depth(
    admin_session, db_session, org_a, _fake_repo_token, monkeypatch
):
    async def _fake_tree(repo_url, pat, ref):
        return ["README.md", "CLAUDE.md", "packages/api/AGENTS.md", "src/index.ts", ".github/copilot-instructions.md"]

    contents = {
        "CLAUDE.md": "root rules",
        "packages/api/AGENTS.md": "api agent rules",
        ".github/copilot-instructions.md": "copilot rules",
    }

    async def _fake_content(repo_url, pat, path, ref):
        return contents[path]

    monkeypatch.setattr("gnt.onboarding_scan.list_repo_tree", _fake_tree)
    monkeypatch.setattr("gnt.onboarding_scan.get_file_content", _fake_content)

    await _seed_connection(db_session, org_a)

    async with admin_session as client:
        r = await client.post("/v1/onboarding/scan")
        assert r.status_code == 200
        body = r.json()
        assert body["repos_scanned"] == 1
        assert body["repos_failed"] == []
        paths = sorted(f["path"] for f in body["files"])
        assert paths == [".github/copilot-instructions.md", "CLAUDE.md", "packages/api/AGENTS.md"]
        by_path = {f["path"]: f["content"] for f in body["files"]}
        assert by_path["CLAUDE.md"] == "root rules"


async def test_scan_reports_a_failed_repo_without_losing_the_other(
    admin_session, db_session, org_a, _fake_repo_token, monkeypatch
):
    from gnt.github.client import GithubClientError

    async def _fake_tree(repo_url, pat, ref):
        if repo_url.endswith("broken"):
            raise GithubClientError("boom")
        return ["CLAUDE.md"]

    async def _fake_content(repo_url, pat, path, ref):
        return "rules"

    monkeypatch.setattr("gnt.onboarding_scan.list_repo_tree", _fake_tree)
    monkeypatch.setattr("gnt.onboarding_scan.get_file_content", _fake_content)

    await _seed_connection(db_session, org_a, repo_url="https://github.com/acme/rules")
    await _seed_connection(db_session, org_a, repo_url="https://github.com/acme/broken")

    async with admin_session as client:
        r = await client.post("/v1/onboarding/scan")
        assert r.status_code == 200
        body = r.json()
        assert body["repos_scanned"] == 1
        assert body["repos_failed"] == ["https://github.com/acme/broken"]
        assert len(body["files"]) == 1


async def test_import_rules_requires_admin(member_session):
    async with member_session as client:
        r = await client.post("/v1/onboarding/rules/import", json={"files": []})
        assert r.status_code == 403


async def test_import_rules_creates_drafts_and_marks_scan_complete(admin_session, db_session, org_a):
    async with admin_session as client:
        r = await client.post(
            "/v1/onboarding/rules/import",
            json={
                "files": [
                    {"repo_url": "https://github.com/acme/rules", "path": "CLAUDE.md", "content": "always test"},
                    {
                        "repo_url": "https://github.com/acme/rules",
                        "path": "packages/api/AGENTS.md",
                        "content": "agent rules",
                    },
                ]
            },
        )
        assert r.status_code == 200
        assert r.json() == {"ok": True, "imported_count": 2}

        listed = await client.get("/v1/rules", params={"status": "draft"})
        assert listed.status_code == 200
        titles = {rule["title"] for rule in listed.json()}
        assert "CLAUDE.md (acme/rules)" in titles
        assert "AGENTS.md (acme/rules)" in titles

    row = (await db_session.execute(select(Org).where(Org.id == org_a))).scalar_one()
    assert row.repo_scan_completed is True
    assert row.rules_imported_count == 2


async def test_import_rules_with_zero_files_still_marks_scan_complete(admin_session, db_session, org_a):
    await ensure_org(db_session, org_a)
    async with admin_session as client:
        r = await client.post("/v1/onboarding/rules/import", json={"files": []})
        assert r.status_code == 200
        assert r.json() == {"ok": True, "imported_count": 0}

    row = (await db_session.execute(select(Org).where(Org.id == org_a))).scalar_one()
    assert row.repo_scan_completed is True
    assert row.rules_imported_count == 0
