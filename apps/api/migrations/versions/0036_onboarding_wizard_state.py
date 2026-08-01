"""Onboarding wizard state on orgs — survey answers plus a completion
flag for the new browser wizard (execution plan: profile -> organization
-> survey -> connect -> scan -> configure -> billing -> done).

No onboarding_step pointer column: the wizard's current step is derived
from real state (session.user.name, org existence, survey_completed, and
later GitHub/rules/billing state) rather than a separately-tracked
enum that could drift from what actually happened — same "don't trust a
cached pointer, check the real thing" posture proxy.ts and every
onboarding page's own server-side check already follow in this codebase.

survey_completed is a real column (not "challenges is non-null") because
skipping the survey is an explicit product decision (see plan section 6)
and an empty/null answer has to mean "skipped", not "hasn't gotten there
yet" -- those need to be distinguishable for resume logic to work.

onboarding_completed defaults true via server_default so every org that
already exists today (all of which finished the *old* org-creation ->
billing -> GitHub-App flow before this wizard existed) reads as done and
is never forced into it retroactively. ensure_org's INSERT (db/org.py)
explicitly passes false for genuinely new orgs -- the only path that
should ever start out not-done. Nothing reads this column yet; the guard
that actually enforces it lands with the wizard's done screen (plan task
9), once there's a real chain of steps for it to gate.

Revision ID: 0036
Revises: 0035
Create Date: 2026-07-30
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orgs", sa.Column("survey_challenges", postgresql.ARRAY(sa.Text()), nullable=True))
    op.add_column("orgs", sa.Column("survey_referral", sa.Text(), nullable=True))
    op.add_column(
        "orgs", sa.Column("survey_completed", sa.Boolean(), nullable=False, server_default="false")
    )
    op.add_column(
        "orgs", sa.Column("onboarding_completed", sa.Boolean(), nullable=False, server_default="true")
    )


def downgrade() -> None:
    op.drop_column("orgs", "onboarding_completed")
    op.drop_column("orgs", "survey_completed")
    op.drop_column("orgs", "survey_referral")
    op.drop_column("orgs", "survey_challenges")
