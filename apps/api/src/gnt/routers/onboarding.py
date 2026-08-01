from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gnt.auth.better_auth import OrgContext, get_current_org, require_admin
from gnt.config import get_settings
from gnt.db.models import GithubConnection, Org
from gnt.db.org import ensure_org
from gnt.db.session import get_session
from gnt.onboarding_scan import scan_org_repos
from gnt.routers.rules import CreateRuleRequest, create_draft_rule

router = APIRouter(prefix="/v1/onboarding", tags=["onboarding"])


class SurveyRequest(BaseModel):
    # Both empty is a valid "skipped" submission (plan section 6: survey is
    # skippable) -- survey_completed on the row is what actually records
    # that this step was visited, not whether these came back non-empty.
    challenges: list[str] = []
    referral: str | None = None


@router.post("/survey")
async def submit_survey(
    body: SurveyRequest,
    org: OrgContext = Depends(get_current_org),
    session: AsyncSession = Depends(get_session),
):
    """Step 3 of the onboarding wizard. Any org member can submit this
    (not require_admin-gated) -- it's preference data about why this org
    signed up, not a privileged action."""
    # ensure_org already scopes app.current_org and hasn't committed yet,
    # so the SELECT below runs in the same scoped transaction -- no need
    # to re-scope the way billing.py's checkout() does after its own
    # intermediate commit.
    await ensure_org(session, org.org_id)
    row = (await session.execute(select(Org).where(Org.id == org.org_id))).scalar_one()
    row.survey_challenges = body.challenges
    row.survey_referral = body.referral
    row.survey_completed = True
    await session.commit()
    return {"ok": True}


class OrganizationProfileRequest(BaseModel):
    # name and slug are Better Auth's own (organization.create, already
    # called client-side before this) -- this only covers the descriptive
    # fields that have nowhere else to live. Both optional: the size
    # picker and website field are asked for, not required, to create an
    # org.
    website: str | None = None
    company_size: str | None = None


@router.post("/organization-profile")
async def submit_organization_profile(
    body: OrganizationProfileRequest,
    org: OrgContext = Depends(get_current_org),
    session: AsyncSession = Depends(get_session),
):
    """Step 2's non-identity fields. Called right after
    organization.create on the client -- same non-admin-gated reasoning
    as submit_survey above: at this point in the flow the caller is the
    org's sole member, its own owner."""
    await ensure_org(session, org.org_id)
    row = (await session.execute(select(Org).where(Org.id == org.org_id))).scalar_one()
    row.website = body.website
    row.company_size = body.company_size
    await session.commit()
    return {"ok": True}


@router.get("/github/repos")
async def list_github_repos(
    org: OrgContext = Depends(get_current_org),
    session: AsyncSession = Depends(get_session),
):
    """Step 5's repo picker -- every repo the org's GitHub App install
    granted access to (routers/github.py's app/callback persists one row
    per repo, all enabled by default), so the wizard can show what's
    connected and let the org narrow it down before continuing to the scan
    step. installation_id IS NOT NULL scopes this to the App flow --
    onboarding never uses the legacy PAT flow, but an org that connected
    via `gnt connect github --pat` before ever starting onboarding
    shouldn't see that single PAT row show up here as if it came through
    this picker."""
    connections = (
        await session.execute(
            select(GithubConnection)
            .where(GithubConnection.org_id == org.org_id, GithubConnection.installation_id.is_not(None))
            .order_by(GithubConnection.created_at)
        )
    ).scalars().all()
    return [
        {"repo_url": c.repo_url, "default_branch": c.default_branch, "enabled": c.enabled}
        for c in connections
    ]


class SelectReposRequest(BaseModel):
    repo_urls: list[str] = Field(min_length=1)


@router.post("/repos")
async def select_repos(
    body: SelectReposRequest,
    org: OrgContext = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Step 5's continue button -- flips `enabled` on for exactly the
    repo_urls given and off for every other App-connected row this org
    has, so unchecking a repo in the picker actually turns gnt off for it
    rather than only affecting some default selection. 404s if any
    requested repo_url isn't one of this org's own connections -- same
    tenant-isolation posture as rules.py's _get_org_rule, not a silent
    no-op on a typo'd or another org's URL."""
    connections = (
        await session.execute(
            select(GithubConnection)
            .where(GithubConnection.org_id == org.org_id, GithubConnection.installation_id.is_not(None))
        )
    ).scalars().all()
    by_url = {c.repo_url: c for c in connections}
    missing = [url for url in body.repo_urls if url not in by_url]
    if missing:
        raise HTTPException(status_code=404, detail=f"not a connected repo: {', '.join(missing)}")

    selected = set(body.repo_urls)
    for connection in connections:
        connection.enabled = connection.repo_url in selected
    await session.commit()
    return {"ok": True, "enabled_count": len(selected)}


@router.post("/scan")
async def run_scan(
    org: OrgContext = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Step 6 -- walks every enabled repo's tree for AI rules files and
    returns what it found, content included, so the step 7 reveal screen
    can render a preview without a second round trip. Doesn't write
    anything yet (no rules created, repo_scan_completed not set) -- that's
    POST /rules/import below, once the org has reviewed and possibly
    narrowed the per-file toggles the reveal screen defaults to "all on"."""
    connections = (
        await session.execute(
            select(GithubConnection).where(GithubConnection.org_id == org.org_id, GithubConnection.enabled.is_(True))
        )
    ).scalars().all()
    if not connections:
        raise HTTPException(status_code=409, detail="no repositories connected -- go back and connect at least one")

    detected, failed_repos = await scan_org_repos(connections)
    return {
        "repos_scanned": len(connections) - len(failed_repos),
        "repos_failed": failed_repos,
        "files": [
            {"repo_url": f.repo_url, "path": f.path, "filename": f.filename, "content": f.content}
            for f in detected
        ],
    }


class ScannedFile(BaseModel):
    repo_url: str
    path: str
    content: str


class ImportRulesRequest(BaseModel):
    # Empty is a valid submission -- a scan that found nothing, or an org
    # that unchecked every file on the reveal screen, still gets to
    # continue past this step (plan section 6: import defaults to "all",
    # not "at least one").
    files: list[ScannedFile] = Field(default_factory=list)


@router.post("/rules/import")
async def import_scanned_rules(
    body: ImportRulesRequest,
    org: OrgContext = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Step 7's continue button -- converts whichever scanned files are
    still checked into draft rules (rules.py's create_draft_rule, the same
    path a human hand-authoring a rule goes through) and marks the scan
    step done. apply_privacy_gate stays False (create_draft_rule's own
    default): this is the org's own repo and its own authored file, the
    same "a deliberate action by whoever's exposing this content" posture
    create_rule already takes, not ambient third-party ingestion."""
    await ensure_org(session, org.org_id)
    for f in body.files:
        filename = f.path.rsplit("/", 1)[-1]
        repo_name = f.repo_url.removeprefix("https://github.com/")
        await create_draft_rule(
            org.org_id,
            org.user_id,
            CreateRuleRequest(
                title=f"{filename} ({repo_name})"[:200],
                # CreateRuleRequest caps body at 8000 chars -- an
                # onboarding-scanned rules file this large is a real edge
                # case, not the common one; truncating here beats the
                # import silently failing over one oversized file.
                body=f.content[:8000],
                source=f"Imported from {repo_name}/{f.path} during onboarding",
                tags=["onboarding-import"],
            ),
        )

    row = (await session.execute(select(Org).where(Org.id == org.org_id))).scalar_one()
    row.repo_scan_completed = True
    row.rules_imported_count += len(body.files)
    await session.commit()
    return {"ok": True, "imported_count": len(body.files)}


class ConfigureRequest(BaseModel):
    # Placeholder toggles (founder call, plan section 6: ship these now,
    # the real check_action option list -- which action types require a
    # check, comment format, etc. -- is a fast-follow, not something to
    # block onboarding on nailing down today). All default True: the
    # safer posture out of the box, matching this step's own LivePreview
    # showing a stricter mocked response by default.
    block_risky_actions: bool = True
    require_human_approval: bool = True
    comment_with_citations: bool = True


@router.get("/configure")
async def get_configure(
    org: OrgContext = Depends(get_current_org),
    session: AsyncSession = Depends(get_session),
):
    """The settings-page counterpart to PATCH below -- lets the Configure
    settings page (post-onboarding, ongoing) load whatever's actually
    saved instead of always rendering the same hardcoded defaults PATCH's
    own ConfigureRequest falls back to on a first-ever save. Same
    defaults here when check_action_settings is still NULL (never
    configured at all), so a brand-new org and one that already went
    through the onboarding step read identically until someone actually
    changes something."""
    row = (await session.execute(select(Org).where(Org.id == org.org_id))).scalar_one_or_none()
    return (row.check_action_settings if row and row.check_action_settings else ConfigureRequest().model_dump())


@router.patch("/configure")
async def submit_configure(
    body: ConfigureRequest,
    org: OrgContext = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Step 8. Admin-gated (unlike survey/organization-profile above) --
    unlike those two purely descriptive fields, this is meant to eventually
    gate what an autonomous agent is allowed to do, so it gets the same
    posture as every other real settings change in this router from the
    start rather than needing a follow-up migration once the real option
    list lands."""
    await ensure_org(session, org.org_id)
    row = (await session.execute(select(Org).where(Org.id == org.org_id))).scalar_one()
    row.check_action_settings = body.model_dump()
    # This is the last step resolveWizardStep (apps/web/lib/onboarding-wizard.ts)
    # itself gates on -- billing and the done screen aren't part of that
    # state machine (see that function's own comment). Does NOT set
    # onboarding_completed -- it used to, before POST /complete below
    # existed (this endpoint predates it), and never got reconciled once
    # that endpoint became the real "no card, no completion" gate the
    # plan calls for: unconditionally flipping the same flag here let
    # anyone skip straight past that check the moment they finished this
    # step, which defeated the entire point of gating it on a real
    # stripe_customer_id. configure_completed alone is what the wizard
    # itself needs to move past this step; onboarding_completed is
    # POST /complete's own flag to set now.
    row.configure_completed = True
    await session.commit()
    return {"ok": True}


@router.get("/summary")
async def onboarding_summary(
    org: OrgContext = Depends(get_current_org),
    session: AsyncSession = Depends(get_session),
):
    """Step 10's stat tiles. mcp_endpoint_url is gnt's one real published
    endpoint (config.py's Settings.mcp_url) -- not a per-org
    `gnt.ai/<handle>` URL the way the plan's own draft copy speculated:
    every org hits the same endpoint and authenticates with its own MCP
    API key (routers/settings.py's POST /settings/mcp-keys), so showing a
    fabricated per-org URL here would be actively wrong, not just
    simplified."""
    repos_connected = (
        await session.execute(
            select(func.count())
            .select_from(GithubConnection)
            .where(GithubConnection.org_id == org.org_id, GithubConnection.enabled.is_(True))
        )
    ).scalar_one()
    row = (await session.execute(select(Org).where(Org.id == org.org_id))).scalar_one_or_none()
    return {
        "repos_connected": repos_connected,
        "rules_imported": row.rules_imported_count if row else 0,
        "mcp_endpoint_url": get_settings().mcp_url,
    }


@router.post("/complete")
async def complete_onboarding(
    org: OrgContext = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Step 10's finish button. Gated on a real Stripe customer existing,
    not is_org_entitled/require_entitled_admin -- ensure_org grants every
    org an automatic trial window on its very first org-scoped call,
    independent of whether Checkout ever ran (see db/org.py's own
    docstring), so entitlement alone doesn't prove a card was ever
    entered. stripe_customer_id is only ever set once Checkout actually
    completes -- the real "no card, no completion" check the plan's own
    verification section calls for."""
    await ensure_org(session, org.org_id)
    row = (await session.execute(select(Org).where(Org.id == org.org_id))).scalar_one()
    if row.stripe_customer_id is None:
        raise HTTPException(status_code=402, detail="add a card to finish setting up gnt.ai")
    row.onboarding_completed = True
    await session.commit()
    return {"ok": True}
