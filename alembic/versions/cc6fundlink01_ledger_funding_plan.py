"""ledger_entries.funding_plan_id (cross-plan funding link)

Revision ID: cc6fundlink01
Revises: cb5goldcoll01
Create Date: 2026-06-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'cc6fundlink01'
down_revision: Union[str, None] = 'cb5goldcoll01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('ledger_entries') as batch:
        batch.add_column(sa.Column('funding_plan_id', sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('ledger_entries') as batch:
        batch.drop_column('funding_plan_id')
