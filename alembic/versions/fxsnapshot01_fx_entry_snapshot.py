"""ledger-entry FX snapshots + daily-refresh claim row

Revision ID: fxsnapshot01
Revises: df9backup01
Create Date: 2026-06-11
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "fxsnapshot01"
down_revision: Union[str, None] = "df9backup01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # counter-currency units per 1 entry-currency unit, x1e6; NULL = no rate known
    op.add_column("ledger_entries", sa.Column("fx_rate_micro", sa.BigInteger(), nullable=True))
    op.add_column("ledger_entries", sa.Column("fx_counter_currency", sa.String(3), nullable=True))
    op.create_table(
        "fx_refresh_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
    )
    op.execute("INSERT INTO fx_refresh_state (id, last_run_at) VALUES (1, NULL)")


def downgrade() -> None:
    op.drop_table("fx_refresh_state")
    op.drop_column("ledger_entries", "fx_counter_currency")
    op.drop_column("ledger_entries", "fx_rate_micro")
