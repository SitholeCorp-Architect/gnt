"""routers/gitlab_webhook.py -- the shared-secret X-Gitlab-Token check.
Deliberately narrow: no rule-processing pipeline is wired up yet (see that
module's own docstring), so this covers exactly what exists -- the
receiver authenticates deliveries correctly and fails closed when
GITLAB_WEBHOOK_SECRET is unset, same discipline
test_github_webhook.py's own signature tests apply to its HMAC check.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from gnt.config import get_settings
from gnt.routers import gitlab_webhook as webhook_router


@pytest.fixture
def webhook_client(test_app_factory):
    app = test_app_factory([webhook_router.router])
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_webhook_rejects_when_secret_is_not_configured(webhook_client):
    async with webhook_client as c:
        r = await c.post("/v1/gitlab/webhook", headers={"X-Gitlab-Token": "anything"}, json={})
    assert r.status_code == 401


async def test_webhook_rejects_a_missing_token_header(webhook_client, monkeypatch):
    monkeypatch.setattr(get_settings(), "gitlab_webhook_secret", "real-secret")
    async with webhook_client as c:
        r = await c.post("/v1/gitlab/webhook", json={})
    assert r.status_code == 401


async def test_webhook_rejects_a_wrong_token(webhook_client, monkeypatch):
    monkeypatch.setattr(get_settings(), "gitlab_webhook_secret", "real-secret")
    async with webhook_client as c:
        r = await c.post("/v1/gitlab/webhook", headers={"X-Gitlab-Token": "wrong-secret"}, json={})
    assert r.status_code == 401


async def test_webhook_accepts_the_configured_secret(webhook_client, monkeypatch):
    monkeypatch.setattr(get_settings(), "gitlab_webhook_secret", "real-secret")
    async with webhook_client as c:
        r = await c.post("/v1/gitlab/webhook", headers={"X-Gitlab-Token": "real-secret"}, json={})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
