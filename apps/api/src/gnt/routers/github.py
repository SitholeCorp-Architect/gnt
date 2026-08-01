import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, SecretStr
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from gnt.auth.better_auth import OrgContext, get_current_org, require_admin
from gnt.config import get_settings
from gnt.db.models import GithubConnection
from gnt.db.org import ensure_org
from gnt.db.session import get_session
from gnt.github.app_auth import (
    GithubAppError,
    build_install_state,
    get_app_slug,
    get_primary_connection,
    list_installation_repos,
    uninstall_app,
    verify_install_state,
)
from gnt.github.client import GithubClientError, create_webhook, verify_repo_access
from gnt.github.crypto import encrypt_token
from gnt.onboarding_metrics import log_onboarding_event
from gnt.store_client import StoreClientError, register_github_source, sync_github_source

router = APIRouter(prefix="/v1/settings/github", tags=["github"])


class ConnectGithubRequest(BaseModel):
    repo_url: str
    pat: SecretStr


def _serialize(connection: GithubConnection) -> dict:
    # Never the PAT, not even encrypted — matches settings.py's mcp-keys
    # convention of only returning a secret once, at mint time. Here: never
    # at all, since the PAT stays a write-only secret from the API's
    # perspective.
    return {
        "repo_url": connection.repo_url,
        "default_branch": connection.default_branch,
        "connected": True,
        "connection_type": "app" if connection.installation_id is not None else "pat",
    }


@router.post("", status_code=201)
async def connect_github(
    body: ConnectGithubRequest,
    org: OrgContext = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    pat = body.pat.get_secret_value()
    try:
        default_branch = await verify_repo_access(body.repo_url, pat)
    except GithubClientError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # register_github_source and create_webhook both run on every connect
    # call, not just the first one — register is idempotent (see
    # NativeStore.registerGithubSource), but create_webhook is not: a
    # reconnect (e.g. after rotating the PAT) creates a second webhook on
    # the same repo instead of finding and reusing the first. Known,
    # accepted limitation for now — duplicate deliveries are harmless
    # (the webhook handler is idempotent against a rule's current status),
    # but the repo accumulates redundant webhook registrations over
    # repeated reconnects. Listing/reusing an existing webhook is future
    # work, not required for the core approve-via-merge flow to work.
    try:
        await register_github_source(org.org_id, body.repo_url, pat)
    except StoreClientError as exc:
        raise HTTPException(status_code=502, detail=f"could not register the repo: {exc}") from exc

    # Best-effort, not required for connect itself to succeed — picks up
    # any rule files already sitting in the repo before this org ever
    # connected gnt (a pre-existing repo, or content added directly on
    # GitHub outside the propose/merge flow). Note this is a genuinely
    # different case from the webhook's own approval flow, which
    # deliberately does NOT call this — see github_webhook.py's comment on
    # why re-syncing after an approval write would clobber it with stale
    # file content instead.
    try:
        await sync_github_source(org.org_id, body.repo_url, pat)
    except StoreClientError:
        pass

    webhook_secret = secrets.token_urlsafe(32)
    webhook_url = f"{get_settings().api_origin}/v1/github/webhook"
    try:
        await create_webhook(body.repo_url, pat, webhook_url, webhook_secret)
    except GithubClientError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    await ensure_org(session, org.org_id)
    stmt = (
        insert(GithubConnection)
        .values(
            org_id=org.org_id,
            repo_url=body.repo_url,
            default_branch=default_branch,
            pat_encrypted=encrypt_token(pat),
            webhook_secret_encrypted=encrypt_token(webhook_secret),
            installed_by_user_id=org.user_id,
        )
        .on_conflict_do_update(
            # Targets migration 0039's partial unique index, not a
            # table-wide one — org_id stopped being globally unique once an
            # App-connected org could have more than one row (see
            # GithubConnection's own docstring). Every row this flow ever
            # writes has installation_id NULL (never set below), so it
            # always matches this index's predicate.
            index_elements=["org_id"],
            index_where=GithubConnection.installation_id.is_(None),
            set_={
                "repo_url": body.repo_url,
                "default_branch": default_branch,
                "pat_encrypted": encrypt_token(pat),
                "webhook_secret_encrypted": encrypt_token(webhook_secret),
                "installed_by_user_id": org.user_id,
            },
        )
        .returning(GithubConnection)
    )
    result = await session.execute(stmt)
    await session.commit()
    connection = result.scalar_one()
    await log_onboarding_event(session, org.org_id, "github_connected")
    return _serialize(connection)


@router.get("")
async def get_github_connection(
    org: OrgContext = Depends(get_current_org),
    session: AsyncSession = Depends(get_session),
):
    # Settings page and the CLI both still speak the single-connection
    # shape this always returned — get_primary_connection is the same
    # "first enabled row" pick every other single-repo call site now uses
    # (see its own docstring), so an org enabled on several repos from
    # onboarding still shows *a* connected repo here rather than crashing.
    connection = await get_primary_connection(session, org.org_id)
    if connection is None:
        return {"connected": False}
    return _serialize(connection)


@router.delete("", status_code=204)
async def disconnect_github(
    org: OrgContext = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    connections = (
        await session.execute(select(GithubConnection).where(GithubConnection.org_id == org.org_id))
    ).scalars().all()
    if not connections:
        raise HTTPException(status_code=404, detail="not connected")
    # One installation grants every App-connected row this org has (they
    # all share the same installation_id) — uninstalling once revokes
    # access to all of them, no need to call per row.
    installation_id = next((c.installation_id for c in connections if c.installation_id is not None), None)
    if installation_id is not None:
        # Best-effort — deleting the rows below is what actually makes
        # `gnt status` and this endpoint report "not connected" again, and
        # that must not hang or fail on a GitHub-side hiccup. Worst case
        # (GitHub unreachable) is the App keeps its grant until the
        # customer removes it from GitHub's own UI, same residual-access
        # gap the old PAT flow always had for a rotated-but-not-revoked
        # token.
        try:
            await uninstall_app(installation_id)
        except GithubAppError:
            pass
    for connection in connections:
        await session.delete(connection)
    await session.commit()


@router.get("/app/install-url")
async def github_app_install_url(
    org: OrgContext = Depends(require_admin),
    origin: str = "web",
):
    """Starts the GitHub App install flow — mints a signed state token
    binding this install to org.org_id (see app_auth.verify_install_state
    for why the callback trusts this instead of whatever org happens to be
    active in the browser that completes it) and points at the App's own
    install URL, fetched live rather than a hardcoded slug."""
    try:
        slug = await get_app_slug()
    except GithubAppError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    state = build_install_state(org.org_id, org.user_id, origin=origin)
    return {"url": f"https://github.com/apps/{slug}/installations/new?state={state}"}


@router.get("/app/callback")
async def github_app_callback(
    session: AsyncSession = Depends(get_session),
    installation_id: int | None = None,
    setup_action: str | None = None,
    state: str | None = None,
):
    """Called server-to-server by apps/web's `/api/github/callback` route
    (the URL actually registered in the App's settings — GitHub redirects
    the browser there, not here) once GitHub redirects back with a real
    installation_id. Every genuine install this app itself started carries
    `state` (see install-url above) — that signature IS the auth for this
    endpoint, there's no session/API-key check here at all, same trust
    model as gnt/slack/oauth.py's own oauth_callback. `setup_action` values
    other than "install" (a pending "request" awaiting an org owner's
    approval, or a repo-selection "update" from GitHub's own installation
    settings page, which doesn't carry state at all) aren't handled here —
    out of scope for this connect flow; re-running `gnt connect github`
    covers the update case in practice."""
    if setup_action != "install" or not installation_id or not state:
        raise HTTPException(status_code=400, detail="incomplete or unsupported install callback")
    try:
        install_state = verify_install_state(state)
    except GithubAppError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        repos = await list_installation_repos(installation_id)
    except GithubAppError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not repos:
        # Genuinely possible (GitHub lets you grant an App zero repos from
        # its own install picker), not just a defensive check -- there's
        # nothing to connect, so this fails loud rather than silently
        # writing zero rows and reporting "connected" to a caller.
        raise HTTPException(
            status_code=422,
            detail="no repositories were granted to the app -- re-run the install and select at least one",
        )

    # One row per granted repo -- see migration 0039 for why org_id is no
    # longer globally unique on this table and repo_url (still unique
    # across every org) is the right ON CONFLICT target here instead.
    # Every row starts enabled: GitHub's own install picker already is the
    # repo-selection step, so there's nothing left to opt into by default;
    # routers/onboarding.py's POST /repos is what lets an org narrow that
    # down afterward.
    rows = []
    for repo in repos:
        default_branch = repo.get("default_branch")
        # Same discipline as github/client.py's verify_repo_access: guessing
        # "main" here would silently reintroduce the exact bug that
        # function's own docstring exists to fix -- fail loud if GitHub's
        # response doesn't say what the real default branch is, don't
        # assume it. One bad repo in the batch fails the whole callback
        # rather than silently connecting a partial set.
        if not isinstance(default_branch, str) or not default_branch:
            raise HTTPException(
                status_code=502, detail=f"GitHub did not return a default branch for {repo['full_name']}"
            )
        rows.append(
            {
                "org_id": install_state.org_id,
                "repo_url": f"https://github.com/{repo['full_name']}",
                "default_branch": default_branch,
                "installation_id": installation_id,
                "pat_encrypted": None,
                "webhook_secret_encrypted": None,
                "installed_by_user_id": install_state.user_id,
                "enabled": True,
            }
        )

    org_id = install_state.org_id
    await ensure_org(session, org_id)
    stmt = insert(GithubConnection).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["repo_url"],
        set_={
            "org_id": stmt.excluded.org_id,
            "default_branch": stmt.excluded.default_branch,
            "installation_id": stmt.excluded.installation_id,
            # Cleared on (re)connect via the App flow, same as an
            # `--upgrade` swapping a PAT-connected row over -- an org is on
            # exactly one flow at a time, see GithubConnection's own
            # docstring.
            "pat_encrypted": None,
            "webhook_secret_encrypted": None,
            "installed_by_user_id": stmt.excluded.installed_by_user_id,
            "enabled": True,
        },
    ).returning(GithubConnection)
    result = await session.execute(stmt)
    await session.commit()
    connections = result.scalars().all()
    await log_onboarding_event(session, org_id, "github_connected")
    return {
        "ok": True,
        "origin": install_state.origin,
        "repo_urls": [c.repo_url for c in connections],
    }
