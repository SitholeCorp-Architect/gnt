"""Onboarding wizard step 2 (organization) — website and company_size on
orgs. name/slug stay Better Auth's (org identity, already exists); these
two are pure descriptive metadata about the org, same "identity lives in
Better Auth, everything else lives here" split migration 0036's
survey_challenges/survey_referral already follow -- see that migration's
own docstring.

Revision ID: 0037
Revises: 0036
Create Date: 2026-07-30
"""

import sqlalchemy as sa

from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orgs", sa.Column("website", sa.Text(), nullable=True))
    op.add_column("orgs", sa.Column("company_size", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("orgs", "company_size")
    op.drop_column("orgs", "website")
