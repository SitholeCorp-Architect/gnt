import hmac

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from gnt.config import get_settings

# Separate router from routers/gitlab.py on purpose — same split
# routers/github_webhook.py's own module comment explains for GitHub: that
# one is a session-authenticated, admin-gated settings surface, this one
# has no session/API-key auth at all and is instead authenticated by
# GitLab itself.
#
# Protocol difference from GitHub worth being explicit about: GitLab
# webhooks authenticate with a plain shared-secret header (X-Gitlab-Token)
# GitLab echoes back verbatim on every delivery, not an HMAC-of-payload
# signature like GitHub's X-Hub-Signature-256 — so this is a direct
# constant-time string comparison (hmac.compare_digest), never a
# hmac.new(...).hexdigest() computation the way
# github_webhook.py's _verify_signature does.
#
# One shared secret for the whole deploy (GITLAB_WEBHOOK_SECRET, config.py)
# rather than a per-connection secret — same "one App, one webhook secret"
# shape github_webhook.py's App-connected rows share via
# GITHUB_APP_WEBHOOK_SECRET, not GithubConnection's own per-repo
# webhook_secret_encrypted (the legacy PAT flow's shape).
#
# ponytail: no rule-approval pipeline wired up yet — connecting a GitLab
# project (routers/gitlab.py) doesn't yet collect *which* project to route
# a delivery's rules to (GitlabConnection.project_path is still nullable,
# see that model's own docstring), so there's nothing here to dispatch a
# verified delivery to. This endpoint's job for now is exactly what the
# scaffold needs: prove the shared secret is checked correctly. Wire up
# real delivery handling (mirroring github_webhook.py's merged-PR handler)
# once project selection exists.
router = APIRouter(prefix="/v1/gitlab", tags=["gitlab-webhook"])


@router.post("/webhook")
async def gitlab_webhook(request: Request):
    secret = get_settings().gitlab_webhook_secret
    token = request.headers.get("X-Gitlab-Token")
    # Fail closed, never fall back to an empty-string secret — an unset
    # GITLAB_WEBHOOK_SECRET would otherwise make every delivery's check
    # pass for anyone who knows to send an empty header, silently turning
    # "misconfigured" into "no auth at all" instead of a loud 401. Same
    # discipline github_webhook.py's own App-secret fallback check applies.
    if not secret or not token or not hmac.compare_digest(token, secret):
        return JSONResponse({"error": "invalid signature"}, status_code=401)
    return JSONResponse({"ok": True})
