"""Onboarding wizard step 8 (configure) -- placeholder check_action
toggles, persisted so they're forward-compatible with the real option list
once it exists (founder call: ship placeholder toggles now, the real
strictness/action-type semantics are a fast-follow, not blocking
onboarding on nailing them down today). Nullable JSONB, not a handful of
dedicated boolean columns -- the shape of these settings is explicitly
provisional and will change once the real option list lands; a JSON blob
means that doesn't need its own migration.

Revision ID: 0042
Revises: 0041
Create Date: 2026-07-30
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orgs", sa.Column("check_action_settings", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("orgs", "check_action_settings")
