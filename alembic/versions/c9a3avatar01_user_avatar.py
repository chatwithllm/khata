"""users.avatar (cropped profile picture, data URL)

Revision ID: c9a3avatar01
Revises: b8a2confirm1
Create Date: 2026-06-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c9a3avatar01'
down_revision: Union[str, None] = 'b8a2confirm1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('users') as batch:
        batch.add_column(sa.Column('avatar', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('users') as batch:
        batch.drop_column('avatar')
