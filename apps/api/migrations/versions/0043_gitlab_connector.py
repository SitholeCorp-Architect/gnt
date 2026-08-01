"""GitLab connector (gitlab-connection-scaffold) -- a new credential-
acquisition path alongside Linear's/Notion's own OAuth connectors, same
shape: apps/api holds an encrypted OAuth token per org, acquired through a
dashboard-driven authorization-code flow (gnt/gitlab/oauth.py).

gitlab_connections is RLS-eligible, same reasoning 0034_notion_linear_
connectors.py gives for notion_connections/linear_connections over
slack_connections/github_connections: no inbound webhook needs to look
this table up by an external id before an org_id is known (see
routers/gitlab_webhook.py's own docstring -- it doesn't even query this
table yet), every read here is already inside an org-scoped session, so
the standard tenant_isolation policy applies.

refresh_token_encrypted/token_expires_at are new columns neither
notion_connections nor linear_connections needed -- GitLab's OAuth access
tokens expire in ~2 hours and come with a refresh_token
(docs.gitlab.com/ee/api/oauth2.html), unlike those two connectors'
effectively-long-lived tokens. project_path/enabled are new too: unlike
Linear's workspace-level connect, GitLab OAuth authorizes an *account*,
not a specific project, so which repo gnt reads rules from is a separate,
not-yet-built selection (see GitlabConnection's own model docstring) --
project_path stays nullable until that selection exists.

Revision ID: 0043
Revises: 0042
Create Date: 2026-07-31
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gitlab_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("orgs.id"), nullable=False, unique=True),
        sa.Column("access_token_encrypted", sa.String(), nullable=False),
        sa.Column("refresh_token_encrypted", sa.String(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("project_path", sa.String(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("installed_by_user_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_gitlab_connections_org_id", "gitlab_connections", ["org_id"])

    op.execute("ALTER TABLE gitlab_connections ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE gitlab_connections FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON gitlab_connections "
        "USING (org_id = current_setting('app.current_org', true)) "
        "WITH CHECK (org_id = current_setting('app.current_org', true))"
    )


def downgrade() -> None:
    op.execute("DROP POLICY tenant_isolation ON gitlab_connections")
    op.execute("ALTER TABLE gitlab_connections NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE gitlab_connections DISABLE ROW LEVEL SECURITY")
    op.drop_table("gitlab_connections")
