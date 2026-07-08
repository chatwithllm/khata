"""transfer_hops, hop_sources, transfer_hop_audit + ledger_entries.source_hop_id

Revision ID: th1hopchain01
Revises: audit01
Create Date: 2026-07-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'th1hopchain01'
down_revision: Union[str, None] = 'audit01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'transfer_hops',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('plan_id', sa.Integer(),
                  sa.ForeignKey('plans.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('chain_id', sa.BigInteger(), nullable=True, index=True),
        sa.Column('from_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('from_contact_id', sa.Integer(),
                  sa.ForeignKey('contacts.id', ondelete='SET NULL'), nullable=True),
        sa.Column('from_name', sa.Text(), nullable=True),
        sa.Column('to_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('to_contact_id', sa.Integer(),
                  sa.ForeignKey('contacts.id', ondelete='SET NULL'), nullable=True),
        sa.Column('to_name', sa.Text(), nullable=True),
        sa.Column('amount_minor', sa.BigInteger(), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('fx_rate_micro', sa.BigInteger(), nullable=True),
        sa.Column('fx_counter_currency', sa.String(3), nullable=True),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('method', sa.String(20), nullable=True),
        sa.Column('proof_ref', sa.Text(), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('is_terminal', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('receipt_status', sa.String(12), nullable=False, server_default='agreed'),
        sa.Column('counter_amount_minor', sa.BigInteger(), nullable=True),
        sa.Column('resolution', sa.String(12), nullable=True),
        sa.Column('logged_by_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        'hop_sources',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('hop_id', sa.Integer(),
                  sa.ForeignKey('transfer_hops.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('source_hop_id', sa.Integer(),
                  sa.ForeignKey('transfer_hops.id'), nullable=True, index=True),
        sa.Column('amount_minor', sa.BigInteger(), nullable=False),
    )
    op.create_table(
        'transfer_hop_audit',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('plan_id', sa.Integer(),
                  sa.ForeignKey('plans.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('hop_id', sa.Integer(),
                  sa.ForeignKey('transfer_hops.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('action', sa.String(8), nullable=False),
        sa.Column('changed_by_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('changed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('snapshot', sa.Text(), nullable=False),
        sa.Column('diff', sa.Text(), nullable=True),
    )
    with op.batch_alter_table('ledger_entries') as batch:
        batch.add_column(sa.Column('source_hop_id', sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('ledger_entries') as batch:
        batch.drop_column('source_hop_id')
    op.drop_table('transfer_hop_audit')
    op.drop_table('hop_sources')
    op.drop_table('transfer_hops')
