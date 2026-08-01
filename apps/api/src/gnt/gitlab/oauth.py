"""GitLab OAuth 2.0 authorization-code flow — a genuine confidential-client
app (GitLab issues a client_secret, unlike Linear's PKCE-only public app),
so this follows gnt/notion/oauth.py's client_secret exchange shape rather
than gnt/linear/oauth.py's PKCE one. State signing (JWT + a dedicated
state secret, org_id + user_id + a short TTL + a nonce) matches Linear's
own build_authorize_url/verify_state pattern — same short-TTL, nonce-
bearing, signed token, just carrying no code_verifier since there's no
PKCE here.

GitLab access tokens expire in ~2 hours and come with a refresh_token
(docs.gitlab.com/ee/api/oauth2.html) — unlike Linear's/Notion's
effectively-long-lived tokens, so this also owns refresh_access_token(),
which those two connectors don't need.

Not configured until GITLAB_CLIENT_ID/GITLAB_CLIENT_SECRET/
GITLAB_STATE_SECRET/GITLAB_TOKEN_ENCRYPTION_KEY are all set (config.py) —
same "external integration hasn't gone live yet" convention as
github_app_id/github_app_private_key (see gnt/github/app_auth.py's own
_require_configured), not linear_client_id's always-required convention,
since there's no real GitLab OAuth App to point at yet.
"""

import secrets
import time
from dataclasses import dataclass

import httpx
import jwt

from gnt.config import get_settings

_AUTHORIZE_URL = "https://gitlab.com/oauth/authorize"
_TOKEN_URL = "https://gitlab.com/oauth/token"
# `api` is the narrowest GitLab OAuth scope that can create merge requests
# through the REST API — read_api/read_repository are read-only, and
# write_repository only covers git push over HTTP, not the API calls gnt's
# propose-a-rule-as-a-PR flow needs. See this connector's own rollout
# notes for the full scope comparison.
_SCOPE = "api"
_STATE_TTL_SECONDS = 60 * 10


class GitlabOAuthError(Exception):
    pass


class GitlabNotConfiguredError(GitlabOAuthError):
    pass


@dataclass(frozen=True)
class GitlabOAuthResult:
    access_token: str
    refresh_token: str | None
    expires_in: int | None


@dataclass(frozen=True)
class GitlabState:
    org_id: str
    user_id: str


def is_configured() -> bool:
    settings = get_settings()
    return bool(
        settings.gitlab_client_id
        and settings.gitlab_client_secret
        and settings.gitlab_state_secret
        and settings.gitlab_token_encryption_key
    )


def _require_configured() -> None:
    if not is_configured():
        raise GitlabNotConfiguredError(
            "GitLab isn't configured on this deploy (GITLAB_CLIENT_ID/GITLAB_CLIENT_SECRET/"
            "GITLAB_STATE_SECRET/GITLAB_TOKEN_ENCRYPTION_KEY unset)"
        )


def _redirect_uri() -> str:
    return f"{get_settings().api_origin}/v1/gitlab/oauth/callback"


def build_authorize_url(org_id: str, user_id: str) -> str:
    _require_configured()
    settings = get_settings()
    now = int(time.time())
    state = jwt.encode(
        {
            "org_id": org_id,
            "user_id": user_id,
            "nonce": secrets.token_urlsafe(8),
            "iat": now,
            "exp": now + _STATE_TTL_SECONDS,
        },
        settings.gitlab_state_secret,
        algorithm="HS256",
    )
    params = httpx.QueryParams(
        {
            "response_type": "code",
            "client_id": settings.gitlab_client_id,
            "redirect_uri": _redirect_uri(),
            "scope": _SCOPE,
            "state": state,
        }
    )
    return f"{_AUTHORIZE_URL}?{params}"


def verify_state(state: str) -> GitlabState:
    """Returns the org_id/user_id encoded in a state token minted by
    build_authorize_url, or raises GitlabOAuthError if it's missing,
    expired, or tampered with."""
    _require_configured()
    try:
        claims = jwt.decode(state, get_settings().gitlab_state_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise GitlabOAuthError("invalid or expired state") from exc

    org_id = claims.get("org_id")
    user_id = claims.get("user_id")
    if not org_id or not user_id:
        raise GitlabOAuthError("state missing org_id or user_id")
    return GitlabState(org_id=org_id, user_id=user_id)


async def exchange_code(code: str) -> GitlabOAuthResult:
    _require_configured()
    settings = get_settings()
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            _TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": _redirect_uri(),
                "client_id": settings.gitlab_client_id,
                "client_secret": settings.gitlab_client_secret,
            },
        )
    body = response.json()
    access_token = body.get("access_token")
    if not response.is_success or not access_token:
        raise GitlabOAuthError(body.get("error_description") or body.get("error") or "gitlab oauth exchange failed")
    return GitlabOAuthResult(
        access_token=access_token,
        refresh_token=body.get("refresh_token"),
        expires_in=body.get("expires_in"),
    )


async def refresh_access_token(refresh_token: str) -> GitlabOAuthResult:
    """Exchanges a refresh_token for a fresh access_token — GitLab's access
    tokens expire after ~2 hours (expires_in on the original exchange),
    unlike Linear's/Notion's effectively-long-lived tokens, so a caller
    that needs to act outside that window has to refresh first. No caller
    in this scaffold does that yet (nothing here calls the GitLab API at
    all — connecting an account is as far as this ticket goes), but
    GitlabConnection already persists refresh_token_encrypted/
    token_expires_at for whichever future caller needs them."""
    _require_configured()
    settings = get_settings()
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            _TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": settings.gitlab_client_id,
                "client_secret": settings.gitlab_client_secret,
            },
        )
    body = response.json()
    access_token = body.get("access_token")
    if not response.is_success or not access_token:
        raise GitlabOAuthError(body.get("error_description") or body.get("error") or "gitlab oauth refresh failed")
    return GitlabOAuthResult(
        access_token=access_token,
        refresh_token=body.get("refresh_token"),
        expires_in=body.get("expires_in"),
    )
