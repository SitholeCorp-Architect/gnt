"""Onboarding wizard steps 6-7: walk an org's connected repos for AI rules
files and surface what was found so the wizard can offer them as starter
rules. Scoped deliberately narrow (plan section 6's own decision): rule-file
detection only, nothing beyond it (no file counting, no dependency graph)
until ingestion v2 lands. apps/cli/src/prebrain/repo-scan.ts looks similar
but isn't a fit here -- it detects a different file set (README/
CONTRIBUTING/CI configs) against the local filesystem, not the GitHub API.
"""

from dataclasses import dataclass

from gnt.db.models import GithubConnection
from gnt.github.app_auth import GithubAppError, get_repo_token
from gnt.github.client import GithubClientError, get_file_content, list_repo_tree

# Case-insensitive basename match -- GitHub itself is case-sensitive, but a
# repo casing one of these loosely (Claude.md, AGENTS.MD) shouldn't silently
# miss detection over it. Exactly the four files plan section 5 task 6
# names, no "style guides" catch-all -- that was explicitly deferred in
# section 6.
RULE_FILENAMES = {"claude.md", ".cursorrules", "agents.md", "copilot-instructions.md"}


@dataclass(frozen=True)
class DetectedRuleFile:
    repo_url: str
    path: str
    content: str

    @property
    def filename(self) -> str:
        return self.path.rsplit("/", 1)[-1]


async def scan_connection_for_rule_files(connection: GithubConnection) -> list[DetectedRuleFile]:
    """One repo's worth of the scan -- lists its full file tree, keeps
    anything whose basename matches RULE_FILENAMES at any depth (a
    monorepo's CLAUDE.md living in a package subdirectory is exactly as
    real a hit as one at the root), then reads each match's content.
    Raises GithubAppError/GithubClientError on failure -- the caller
    (routers/onboarding.py's POST /scan) decides how to report a
    per-repo failure without losing whatever other repos succeeded."""
    pat = await get_repo_token(connection)
    paths = await list_repo_tree(connection.repo_url, pat, connection.default_branch)
    matches = [path for path in paths if path.rsplit("/", 1)[-1].lower() in RULE_FILENAMES]
    detected = []
    for path in matches:
        content = await get_file_content(connection.repo_url, pat, path, connection.default_branch)
        detected.append(DetectedRuleFile(repo_url=connection.repo_url, path=path, content=content))
    return detected


async def scan_org_repos(
    connections: list[GithubConnection],
) -> tuple[list[DetectedRuleFile], list[str]]:
    """Every enabled connection, best-effort per repo -- one repo's App
    token expiring mid-flow or a transient GitHub hiccup shouldn't lose
    results already found on every other connected repo. Returns
    (detected files across every repo that succeeded, repo_urls that
    failed) so the caller can report a partial result instead of an
    all-or-nothing failure."""
    detected: list[DetectedRuleFile] = []
    failed: list[str] = []
    for connection in connections:
        try:
            detected.extend(await scan_connection_for_rule_files(connection))
        except (GithubAppError, GithubClientError):
            failed.append(connection.repo_url)
    return detected, failed
