"""plan_shares — public read-only share links

Revision ID: sh1share01
Revises: fxsnapshot01
Create Date: 2026-06-19
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "sh1share01"
down_revision: Union[str, None] = "fxsnapshot01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "plan_shares",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("plans.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(8), nullable=False, server_default="summary"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_plan_shares_plan_id", "plan_shares", ["plan_id"])
    op.create_index("ix_plan_shares_token", "plan_shares", ["token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_plan_shares_token", table_name="plan_shares")
    op.drop_index("ix_plan_shares_plan_id", table_name="plan_shares")
    op.drop_table("plan_shares")
