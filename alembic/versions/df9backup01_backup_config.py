"""backup_config — automatic-backup schedule (singleton row)

Revision ID: df9backup01
Revises: de8admin01
Create Date: 2026-06-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'df9backup01'
down_revision: Union[str, None] = 'de8admin01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'backup_config',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('frequency', sa.String(length=12), nullable=False, server_default='daily'),
        sa.Column('hour', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('retention', sa.Integer(), nullable=False, server_default='14'),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_status', sa.String(length=200), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    # seed the singleton (id=1), disabled by default
    op.execute("INSERT INTO backup_config (id, enabled, frequency, hour, retention) "
               "VALUES (1, 0, 'daily', 3, 14)")


def downgrade() -> None:
    op.drop_table('backup_config')
