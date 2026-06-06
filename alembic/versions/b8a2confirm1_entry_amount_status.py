"""ledger_entries.amount_status + counter_amount_minor (contribution agreement)

Revision ID: b8a2confirm1
Revises: b7a1m3status1
Create Date: 2026-06-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b8a2confirm1'
down_revision: Union[str, None] = 'b7a1m3status1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # amount_status: agreed | pending | countered. server_default 'agreed' so existing
    # entries keep counting as confirmed; new third-party-attributed entries start 'pending'.
    # counter_amount_minor holds the contributor's proposed correction while negotiating.
    with op.batch_alter_table('ledger_entries') as batch:
        batch.add_column(sa.Column('amount_status', sa.String(length=12),
                                   nullable=False, server_default='agreed'))
        batch.add_column(sa.Column('counter_amount_minor', sa.BigInteger(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('ledger_entries') as batch:
        batch.drop_column('counter_amount_minor')
        batch.drop_column('amount_status')
