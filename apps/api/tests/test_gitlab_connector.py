"""gitlab-connection-scaffold — the GitLab connector's server-side half.
Same coverage shape as test_linear_connector.py (see that file's own
docstring for what's covered here vs. exercised live), plus what's new to
this connector: the "not configured yet" gate every call site
(build_authorize_url, verify_state, install-url, status) falls back to
when GITLAB_CLIENT_ID/SECRET/STATE_SECRET/TOKEN_ENCRYPTION_KEY aren't set
(unset by default in this suite's .env, same as GITHUB_APP_ID/
GITHUB_APP_PRIVATE_KEY -- see test_github_app_auth.py's own
`app_configured` fixture for the identical monkeypatch-the-cached-Settings
pattern this file's `gitlab_configured` fixture follows), and the oauth
callback's bad/expired-state and error-param rejection paths.
"""

import time

import jwt
import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient

from gnt.config import get_settings
from gnt.db.models import GitlabConnection
from gnt.db.org import ensure_org
from gnt.db.rls import scope_to_org
from gnt.gitlab.crypto import decrypt_token, encrypt_token
from gnt.gitlab.oauth import (
    GitlabNotConfiguredError,
    GitlabOAuthError,
    build_authorize_url,
    is_configured,
    verify_state,
)
from gnt.routers import gitlab as gitlab_router
from tests.conftest import make_org_client


@pytest.fixture
def gitlab_configured(monkeypatch):
    """Same pattern test_github_app_auth.py's `app_configured` fixture
    uses: get_settings() is a process-wide @lru_cache'd singleton, so
    monkeypatch.setattr directly on that instance is what makes the
    "configured" state visible to every call site (including inside the
    router, which calls get_settings() fresh on every request) without a
    real GITLAB_CLIENT_ID/SECRET ever touching .env."""
    settings = get_settings()
    monkeypatch.setattr(settings, "gitlab_client_id", "test-client-id")
    monkeypatch.setattr(settings, "gitlab_client_secret", "test-client-secret")
    monkeypatch.setattr(settings, "gitlab_state_secret", "test-state-secret-well-over-32-bytes-long")
    monkeypatch.setattr(settings, "gitlab_token_encryption_key", Fernet.generate_key().decode())
    return settings


async def _connect_project(db_session, org_id: str) -> None:
    await ensure_org(db_session, org_id)
    await db_session.commit()
    await scope_to_org(db_session, org_id)
    db_session.add(
        GitlabConnection(
            org_id=org_id,
            access_token_encrypted=encrypt_token("fake-gitlab-token"),
            installed_by_user_id="user_test",
            project_path="acme/rules",
        )
    )
    await db_session.commit()


def test_is_configured_false_by_default():
    assert is_configured() is False


def test_build_authorize_url_raises_when_not_configured():
    with pytest.raises(GitlabNotConfiguredError):
        build_authorize_url("org_test_x", "user_test_x")


def test_verify_state_round_trips_org_id_and_user_id(gitlab_configured):
    from urllib.parse import parse_qs, urlsplit

    url = build_authorize_url("org_test_x", "user_test_x")
    assert url.startswith("https://gitlab.com/oauth/authorize?")
    assert "client_secret" not in url

    query = parse_qs(urlsplit(url).query)
    result = verify_state(query["state"][0])
    assert result.org_id == "org_test_x"
    assert result.user_id == "user_test_x"


def test_verify_state_rejects_a_tampered_token(gitlab_configured):
    with pytest.raises(GitlabOAuthError):
        verify_state("not-a-real-jwt")


def test_verify_state_rejects_an_expired_token(gitlab_configured):
    expired = jwt.encode(
        {
            "org_id": "org_test_x",
            "user_id": "user_test_x",
            "nonce": "n",
            "iat": int(time.time()) - 1200,
            "exp": int(time.time()) - 600,
        },
        get_settings().gitlab_state_secret,
        algorithm="HS256",
    )
    with pytest.raises(GitlabOAuthError):
        verify_state(expired)


def test_encrypt_decrypt_round_trip(gitlab_configured):
    ciphertext = encrypt_token("gl-pat-real-secret")
    assert ciphertext != "gl-pat-real-secret"
    assert decrypt_token(ciphertext) == "gl-pat-real-secret"


async def test_install_url_returns_503_when_not_configured(test_app_factory, org_a):
    client = make_org_client(test_app_factory, org_a, role="admin", routers=[gitlab_router.router])
    async with client as c:
        r = await c.get("/v1/gitlab/install-url")
    assert r.status_code == 503


async def test_install_url_requires_admin(test_app_factory, org_a, gitlab_configured):
    client = make_org_client(test_app_factory, org_a, role="member", routers=[gitlab_router.router])
    async with client as c:
        r = await c.get("/v1/gitlab/install-url")
    assert r.status_code == 403


async def test_install_url_returns_a_real_authorize_link_for_an_admin(test_app_factory, org_a, gitlab_configured):
    client = make_org_client(test_app_factory, org_a, role="admin", routers=[gitlab_router.router])
    async with client as c:
        r = await c.get("/v1/gitlab/install-url")
    assert r.status_code == 200
    url = r.json()["url"]
    assert url.startswith("https://gitlab.com/oauth/authorize?")
    assert "code_challenge" not in url  # confidential-client flow, no PKCE
    assert "client_secret" not in url


async def test_status_reports_not_connected_and_not_configured_by_default(test_app_factory, org_a):
    client = make_org_client(test_app_factory, org_a, routers=[gitlab_router.router])
    async with client as c:
        r = await c.get("/v1/gitlab/status")
    assert r.status_code == 200
    assert r.json() == {"connected": False, "configured": False}


async def test_status_reports_configured_once_settings_are_set(test_app_factory, org_a, gitlab_configured):
    client = make_org_client(test_app_factory, org_a, routers=[gitlab_router.router])
    async with client as c:
        r = await c.get("/v1/gitlab/status")
    assert r.json() == {"connected": False, "configured": True}


async def test_status_after_a_connection_exists(test_app_factory, db_session, org_a, gitlab_configured):
    await _connect_project(db_session, org_a)
    client = make_org_client(test_app_factory, org_a, routers=[gitlab_router.router])
    async with client as c:
        r = await c.get("/v1/gitlab/status")
    assert r.json() == {"connected": True, "configured": True, "project_path": "acme/rules"}


async def test_status_is_isolated_to_its_own_org(test_app_factory, db_session, org_a, org_b, gitlab_configured):
    await _connect_project(db_session, org_a)
    client_b = make_org_client(test_app_factory, org_b, routers=[gitlab_router.router])
    async with client_b as c:
        r = await c.get("/v1/gitlab/status")
    assert r.json() == {"connected": False, "configured": True}


async def test_disconnect_deletes_the_row(test_app_factory, db_session, org_a, gitlab_configured):
    await _connect_project(db_session, org_a)
    client = make_org_client(test_app_factory, org_a, role="admin", routers=[gitlab_router.router])
    async with client as c:
        delete_r = await c.delete("/v1/gitlab/status")
        status_r = await c.get("/v1/gitlab/status")
    assert delete_r.status_code == 204
    assert status_r.json()["connected"] is False


async def test_disconnect_404s_when_nothing_is_connected(test_app_factory, org_a, gitlab_configured):
    client = make_org_client(test_app_factory, org_a, role="admin", routers=[gitlab_router.router])
    async with client as c:
        r = await c.delete("/v1/gitlab/status")
    assert r.status_code == 404


async def test_disconnect_requires_admin(test_app_factory, org_a, gitlab_configured):
    client = make_org_client(test_app_factory, org_a, role="member", routers=[gitlab_router.router])
    async with client as c:
        r = await c.delete("/v1/gitlab/status")
    assert r.status_code == 403


async def test_oauth_callback_shows_a_failure_page_on_error_param(test_app_factory):
    app = test_app_factory([gitlab_router.router])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/v1/gitlab/oauth/callback", params={"error": "access_denied"})
    assert r.status_code == 200
    assert "failed" in r.text.lower()


async def test_oauth_callback_rejects_a_bad_state(test_app_factory, gitlab_configured):
    app = test_app_factory([gitlab_router.router])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/v1/gitlab/oauth/callback", params={"code": "abc", "state": "not-a-real-jwt"})
    assert r.status_code == 200
    assert "failed" in r.text.lower()


async def test_oauth_callback_rejects_an_expired_state(test_app_factory, gitlab_configured):
    expired = jwt.encode(
        {
            "org_id": "org_test_x",
            "user_id": "user_test_x",
            "nonce": "n",
            "iat": int(time.time()) - 1200,
            "exp": int(time.time()) - 600,
        },
        get_settings().gitlab_state_secret,
        algorithm="HS256",
    )
    app = test_app_factory([gitlab_router.router])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/v1/gitlab/oauth/callback", params={"code": "abc", "state": expired})
    assert r.status_code == 200
    assert "failed" in r.text.lower()


async def test_oauth_callback_fails_cleanly_when_not_configured(test_app_factory):
    app = test_app_factory([gitlab_router.router])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/v1/gitlab/oauth/callback", params={"code": "abc", "state": "whatever"})
    assert r.status_code == 200
    assert "failed" in r.text.lower()
