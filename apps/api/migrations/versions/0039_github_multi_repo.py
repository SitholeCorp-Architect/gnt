"""github_connections goes from one-repo-per-org to N-repos-per-org — the
App install flow's own callback used to hard-reject any installation that
wasn't scoped to exactly one repository (see routers/github.py's old
`if len(repos) != 1` check), which was always a placeholder: GitHub's own
install UI already lets someone grant access to several repos in one
install, and list_installation_repos already returns the full list.

org_id's old table-wide unique constraint is dropped (an App-connected org
can now have one row per enabled repo) and replaced with a unique index
scoped to installation_id IS NULL — the legacy PAT flow (routers/
github.py's connect_github) is untouched, still exactly one row per org,
and this is what lets its own ON CONFLICT (org_id) upsert keep working.
`enabled` lets an org that granted access to more repos than it wants gnt
active on turn specific ones off without losing the row (and without
re-running the GitHub install flow to regrant a narrower set).

installation_id's own unique index (migration 0033) goes non-unique for the
same reason -- one install can now back several rows (one per granted
repo), all sharing that installation_id, and the old constraint made a
second-repo insert 23505 outright.

Revision ID: 0039
Revises: 0038
Create Date: 2026-07-30
"""

import sqlalchemy as sa

from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("github_connections_org_id_key", "github_connections", type_="unique")
    op.add_column(
        "github_connections",
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.create_index(
        "ix_github_connections_org_id_pat_unique",
        "github_connections",
        ["org_id"],
        unique=True,
        postgresql_where=sa.text("installation_id IS NULL"),
    )
    op.drop_index("ix_github_connections_installation_id", table_name="github_connections")
    op.create_index(
        "ix_github_connections_installation_id", "github_connections", ["installation_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_github_connections_installation_id", table_name="github_connections")
    op.create_index(
        "ix_github_connections_installation_id", "github_connections", ["installation_id"], unique=True
    )
    op.drop_index("ix_github_connections_org_id_pat_unique", table_name="github_connections")
    op.drop_column("github_connections", "enabled")
    op.create_unique_constraint("github_connections_org_id_key", "github_connections", ["org_id"])
