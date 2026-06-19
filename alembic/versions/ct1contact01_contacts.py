"""contacts + loan.contact_id + attachments.contact_id

Revision ID: ct1contact01
Revises: sh1share01
Create Date: 2026-06-19
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "ct1contact01"
down_revision: Union[str, None] = "sh1share01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "contacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("phone", sa.String(40), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("photo", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_contacts_owner_user_id", "contacts", ["owner_user_id"])
    with op.batch_alter_table("loans") as b:
        b.add_column(sa.Column("contact_id", sa.Integer(), nullable=True))
        b.create_foreign_key("fk_loans_contact", "contacts", ["contact_id"], ["id"],
                             ondelete="SET NULL")
        b.create_index("ix_loans_contact_id", ["contact_id"])
    with op.batch_alter_table("attachments") as b:
        b.alter_column("ledger_entry_id", existing_type=sa.Integer(), nullable=True)
        b.add_column(sa.Column("contact_id", sa.Integer(), nullable=True))
        b.create_foreign_key("fk_attachments_contact", "contacts", ["contact_id"], ["id"],
                             ondelete="CASCADE")
        b.create_index("ix_attachments_contact_id", ["contact_id"])


def downgrade() -> None:
    with op.batch_alter_table("attachments", recreate="always") as b:
        b.drop_index("ix_attachments_contact_id")
        b.drop_constraint("fk_attachments_contact", type_="foreignkey")
        b.drop_column("contact_id")
        b.alter_column("ledger_entry_id", existing_type=sa.Integer(), nullable=False)
    with op.batch_alter_table("loans", recreate="always") as b:
        b.drop_index("ix_loans_contact_id")
        b.drop_constraint("fk_loans_contact", type_="foreignkey")
        b.drop_column("contact_id")
    op.drop_index("ix_contacts_owner_user_id", table_name="contacts")
    op.drop_table("contacts")
