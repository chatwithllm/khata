"""loans inline collateral (gold weight / rate / market value)

Revision ID: cb5goldcoll01
Revises: ca4loankind01
Create Date: 2026-06-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'cb5goldcoll01'
down_revision: Union[str, None] = 'ca4loankind01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('loans') as batch:
        batch.add_column(sa.Column('collateral_qty_micro', sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column('collateral_unit', sa.String(length=12), nullable=True))
        batch.add_column(sa.Column('collateral_rate_minor', sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column('collateral_rate_basis', sa.String(length=12), nullable=True))
        batch.add_column(sa.Column('collateral_value_minor', sa.BigInteger(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('loans') as batch:
        batch.drop_column('collateral_value_minor')
        batch.drop_column('collateral_rate_basis')
        batch.drop_column('collateral_rate_minor')
        batch.drop_column('collateral_unit')
        batch.drop_column('collateral_qty_micro')
