"""plan_memberships.status (sharing invitations)

Revision ID: b7a1m3status1
Revises: 239bdb8b9bf6
Create Date: 2026-06-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b7a1m3status1'
down_revision: Union[str, None] = '239bdb8b9bf6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # status: invited | active | declined. server_default 'active' so existing
    # memberships keep working; new shares are created 'invited' in code.
    with op.batch_alter_table('plan_memberships') as batch:
        batch.add_column(sa.Column('status', sa.String(length=12),
                                   nullable=False, server_default='active'))


def downgrade() -> None:
    with op.batch_alter_table('plan_memberships') as batch:
        batch.drop_column('status')
