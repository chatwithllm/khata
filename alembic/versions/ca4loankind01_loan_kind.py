"""loans.kind (loan category: personal/gold/home/vehicle/…)

Revision ID: ca4loankind01
Revises: c9a3avatar01
Create Date: 2026-06-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'ca4loankind01'
down_revision: Union[str, None] = 'c9a3avatar01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('loans') as batch:
        batch.add_column(sa.Column('kind', sa.String(length=16), nullable=False,
                                   server_default='personal'))


def downgrade() -> None:
    with op.batch_alter_table('loans') as batch:
        batch.drop_column('kind')
