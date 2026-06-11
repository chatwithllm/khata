"""users.is_admin + users.disabled (admin role + account disable)

Bootstraps the first registered user (lowest id) as admin so existing
instances keep a working operator after upgrade.

Revision ID: de8admin01
Revises: dd7attach01
Create Date: 2026-06-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'de8admin01'
down_revision: Union[str, None] = 'dd7attach01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('users') as batch:
        batch.add_column(sa.Column('is_admin', sa.Boolean(), nullable=False, server_default='0'))
        batch.add_column(sa.Column('disabled', sa.Boolean(), nullable=False, server_default='0'))
    # Bootstrap: the person who stood the instance up (first user) becomes admin.
    op.execute("UPDATE users SET is_admin = 1 "
               "WHERE id = (SELECT id FROM users ORDER BY id LIMIT 1)")


def downgrade() -> None:
    with op.batch_alter_table('users') as batch:
        batch.drop_column('disabled')
        batch.drop_column('is_admin')
