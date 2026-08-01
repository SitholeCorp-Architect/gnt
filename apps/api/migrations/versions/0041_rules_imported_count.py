"""Onboarding wizard's done screen (plan step 10) shows "rules imported"
as a stat tile -- a plain counter on orgs rather than deriving it by
tagging and re-querying apps/store's rule rows, since nothing else needs
to distinguish a scan-imported rule from any other draft rule after the
fact. Written once, by routers/onboarding.py's POST /rules/import.

Revision ID: 0041
Revises: 0040
Create Date: 2026-07-30
"""

import sqlalchemy as sa

from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orgs", sa.Column("rules_imported_count", sa.Integer(), nullable=False, server_default="0")
    )


def downgrade() -> None:
    op.drop_column("orgs", "rules_imported_count")
