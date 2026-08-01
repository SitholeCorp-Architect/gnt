"""Onboarding wizard steps 6-8 (scan, rules import, configure) need their
own "is this step done" markers, same reasoning as migration 0036's
survey_completed: the wizard derives its current step from real state
(apps/web/lib/onboarding-wizard.ts's resolveWizardStep), not a stored
step pointer, and neither step has a state to read that off of otherwise
-- a repo scan can legitimately find zero rule files and still be "done",
and configure's settings can legitimately all be left at their defaults.

Revision ID: 0040
Revises: 0039
Create Date: 2026-07-30
"""

import sqlalchemy as sa

from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orgs", sa.Column("repo_scan_completed", sa.Boolean(), nullable=False, server_default="false")
    )
    op.add_column(
        "orgs", sa.Column("configure_completed", sa.Boolean(), nullable=False, server_default="false")
    )


def downgrade() -> None:
    op.drop_column("orgs", "configure_completed")
    op.drop_column("orgs", "repo_scan_completed")
