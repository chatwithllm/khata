"""attachments.hop_id — proof files on transfer hops (4th attachment parent)

Revision ID: th2hopattach01
Revises: th1hopchain01
Create Date: 2026-07-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'th2hopattach01'
down_revision: Union[str, None] = 'th1hopchain01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('attachments') as batch:
        batch.add_column(sa.Column('hop_id', sa.Integer(), nullable=True))
    op.create_index('ix_attachments_hop_id', 'attachments', ['hop_id'])


def downgrade() -> None:
    op.drop_index('ix_attachments_hop_id', table_name='attachments')
    with op.batch_alter_table('attachments') as batch:
        batch.drop_column('hop_id')
