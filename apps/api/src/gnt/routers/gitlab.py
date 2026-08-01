from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from gnt.auth.better_auth import OrgContext, get_current_org, require_admin
from gnt.config import get_settings
from gnt.db.models import GitlabConnection
from gnt.db.org import ensure_org
from gnt.db.rls import scope_to_org
from gnt.db.session import get_session
from gnt.gitlab.crypto import encrypt_token
from gnt.gitlab.oauth import (
    GitlabNotConfiguredError,
    GitlabOAuthError,
    build_authorize_url,
    exchange_code,
    is_configured,
    verify_state,
)

router = APIRouter(prefix="/v1/gitlab", tags=["gitlab"])


def _plain_page(message: str) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><html><head><meta charset=\"utf-8\"><title>gnt.ai</title></head>"
        f"<body style=\"font-family: system-ui, sans-serif; padding: 3rem; text-align: center;\">"
        f"<p>{message}</p><p>You can close this tab.</p></body></html>"
    )


@router.get("/install-url")
async def install_url(
    org: OrgContext = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    try:
        url = build_authorize_url(org.org_id, org.user_id)
    except GitlabNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    await ensure_org(session, org.org_id)
    return {"url": url}


@router.get("/oauth/callback")
async def oauth_callback(
    session: AsyncSession = Depends(get_session),
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    if error or not code or not state:
        return _plain_page("GitLab connection failed — go back to the dashboard and try again.")

    try:
        gitlab_state = verify_state(state)
        result = await exchange_code(code)
    except (GitlabNotConfiguredError, GitlabOAuthError):
        return _plain_page("GitLab connection failed — go back to the dashboard and try again.")

    org_id = gitlab_state.org_id
    await scope_to_org(session, org_id)
    await ensure_org(session, org_id)
    encrypted_access_token = encrypt_token(result.access_token)
    encrypted_refresh_token = encrypt_token(result.refresh_token) if result.refresh_token else None
    token_expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=result.expires_in) if result.expires_in else None
    )
    stmt = (
        insert(GitlabConnection)
        .values(
            org_id=org_id,
            access_token_encrypted=encrypted_access_token,
            refresh_token_encrypted=encrypted_refresh_token,
            token_expires_at=token_expires_at,
            installed_by_user_id=gitlab_state.user_id,
        )
        .on_conflict_do_update(
            index_elements=["org_id"],
            set_={
                "access_token_encrypted": encrypted_access_token,
                "refresh_token_encrypted": encrypted_refresh_token,
                "token_expires_at": token_expires_at,
                "installed_by_user_id": gitlab_state.user_id,
            },
        )
    )
    await session.execute(stmt)
    await session.commit()

    # Linear's/Notion's own callbacks still redirect at /app/settings/
    # organization, stale since the Connect page moved to its own /connect
    # route (connect-settings-client.tsx's own comment) -- not fixing that
    # here (out of scope, existing connectors), but this new one points at
    # the real current route rather than copying the staleness forward.
    return RedirectResponse(f"{get_settings().web_origin}/connect?gitlab=connected")


@router.get("/status")
async def status_(
    org: OrgContext = Depends(get_current_org),
    session: AsyncSession = Depends(get_session),
):
    connection = (
        await session.execute(select(GitlabConnection).where(GitlabConnection.org_id == org.org_id))
    ).scalar_one_or_none()
    if connection is None:
        return {"connected": False, "configured": is_configured()}
    return {"connected": True, "configured": True, "project_path": connection.project_path}


@router.delete("/status", status_code=204)
async def disconnect(
    org: OrgContext = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    connection = (
        await session.execute(select(GitlabConnection).where(GitlabConnection.org_id == org.org_id))
    ).scalar_one_or_none()
    if connection is None:
        raise HTTPException(status_code=404, detail="GitLab isn't connected for this org.")
    await session.delete(connection)
    await session.commit()
