"""ledger-entry audit trail (create / edit / delete history)

Revision ID: audit01
Revises: fxsnapshot01
Create Date: 2026-06-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "audit01"
down_revision: Union[str, None] = "fxsnapshot01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ledger_entry_audit",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("plans.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("entry_id", sa.Integer(),
                  sa.ForeignKey("ledger_entries.id", ondelete="SET NULL"),
                  nullable=True, index=True),
        sa.Column("action", sa.String(8), nullable=False),
        sa.Column("changed_by_user_id", sa.Integer(),
                  sa.ForeignKey("users.id"), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot", sa.Text(), nullable=False),
        sa.Column("diff", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("ledger_entry_audit")
