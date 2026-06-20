"""asset seller/buyer + extra_fields/links + attachments.asset_plan_id

Revision ID: as1assetmeta01
Revises: ct1contact01
Create Date: 2026-06-19
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "as1assetmeta01"
down_revision: Union[str, None] = "ct1contact01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("asset_purchases") as b:
        b.add_column(sa.Column("seller_name", sa.Text(), nullable=True))
        b.add_column(sa.Column("seller_contact_id", sa.Integer(), nullable=True))
        b.add_column(sa.Column("buyer_name", sa.Text(), nullable=True))
        b.add_column(sa.Column("buyer_contact_id", sa.Integer(), nullable=True))
        b.add_column(sa.Column("extra_fields", sa.Text(), nullable=True))
        b.add_column(sa.Column("links", sa.Text(), nullable=True))
        b.create_foreign_key("fk_asset_seller_contact", "contacts", ["seller_contact_id"], ["id"],
                             ondelete="SET NULL")
        b.create_foreign_key("fk_asset_buyer_contact", "contacts", ["buyer_contact_id"], ["id"],
                             ondelete="SET NULL")
    with op.batch_alter_table("attachments") as b:
        b.add_column(sa.Column("asset_plan_id", sa.Integer(), nullable=True))
        b.create_foreign_key("fk_attachments_asset_plan", "plans", ["asset_plan_id"], ["id"],
                             ondelete="CASCADE")
        b.create_index("ix_attachments_asset_plan_id", ["asset_plan_id"])


def downgrade() -> None:
    with op.batch_alter_table("attachments", recreate="always") as b:
        b.drop_index("ix_attachments_asset_plan_id")
        b.drop_constraint("fk_attachments_asset_plan", type_="foreignkey")
        b.drop_column("asset_plan_id")
    with op.batch_alter_table("asset_purchases", recreate="always") as b:
        b.drop_constraint("fk_asset_buyer_contact", type_="foreignkey")
        b.drop_constraint("fk_asset_seller_contact", type_="foreignkey")
        for c in ("links", "extra_fields", "buyer_contact_id", "buyer_name",
                  "seller_contact_id", "seller_name"):
            b.drop_column(c)
