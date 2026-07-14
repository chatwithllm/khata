"""transfer_hops.funding_source + funding_plan_id — provenance of in-transit money

Revision ID: th3hopfund01
Revises: th2hopattach01
Create Date: 2026-07-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'th3hopfund01'
down_revision: Union[str, None] = 'th2hopattach01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('transfer_hops') as batch:
        batch.add_column(sa.Column('funding_source', sa.String(length=20), nullable=True))
        batch.add_column(sa.Column('funding_plan_id', sa.Integer(), nullable=True))
    op.create_index('ix_transfer_hops_funding_plan_id', 'transfer_hops', ['funding_plan_id'])


def downgrade() -> None:
    op.drop_index('ix_transfer_hops_funding_plan_id', table_name='transfer_hops')
    with op.batch_alter_table('transfer_hops') as batch:
        batch.drop_column('funding_plan_id')
        batch.drop_column('funding_source')
