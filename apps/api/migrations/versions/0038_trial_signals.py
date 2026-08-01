"""trial_signals — free-trial abuse-prevention signals (device fingerprint
+ IP + card fingerprint, weighted into a composite risk score). See
db/models.py's TrialSignal docstring for why this is its own table
(fields populate at two different points in the real signup flow) and
why it deliberately has no RLS (scoring one org's risk means reading
recent signals across every OTHER org, which an RLS-scoped session could
never do). gnt.trial_risk owns the read/write logic; config.py's
trial_risk_* fields (weights, lookback window, score thresholds) own the
tunable numbers.

Revision ID: 0038
Revises: 0037
Create Date: 2026-07-28
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trial_signals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("orgs.id"), nullable=False, unique=True),
        sa.Column("signup_ip", sa.String(), nullable=True),
        sa.Column("device_fingerprint", sa.String(), nullable=True),
        sa.Column("card_fingerprint", sa.String(), nullable=True),
        sa.Column("risk_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("risk_status", sa.String(), nullable=False, server_default="clean"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_trial_signals_org_id", "trial_signals", ["org_id"])
    op.create_index("ix_trial_signals_signup_ip", "trial_signals", ["signup_ip"])
    op.create_index("ix_trial_signals_device_fingerprint", "trial_signals", ["device_fingerprint"])
    op.create_index("ix_trial_signals_card_fingerprint", "trial_signals", ["card_fingerprint"])
    # Deliberately no RLS policy here — see this table's own TrialSignal
    # docstring in db/models.py, and migration 0007's mcp_api_keys/
    # slack_connections exemptions for the identical reasoning.


def downgrade() -> None:
    op.drop_table("trial_signals")
