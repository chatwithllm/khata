from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TransferHop(Base):
    """One hop of money on its way to a plan's seller. Non-terminal hops are
    in-transit and never count toward plan totals; a terminal hop fans out
    into LedgerEntry rows (one per ultimate contributor). Everything that
    consumes upstream money is itself a hop: a forward, a return
    (resolution='returned') or a fee write-off (resolution='fee') — so
    outstanding(hop) = amount − Σ consumed is the only accounting rule."""
    __tablename__ = "transfer_hops"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), nullable=False, index=True)
    # chain groups hops; equals the first hop's id. Set post-flush on roots.
    chain_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    from_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    from_contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    from_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    to_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    to_contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    to_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    fx_rate_micro: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    fx_counter_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    proof_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_terminal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # agreed | pending | countered — pending only when receiver is a registered
    # user other than the logger (mirrors LedgerEntry.amount_status).
    receipt_status: Mapped[str] = mapped_column(
        String(12), nullable=False, server_default="agreed", default="agreed")
    counter_amount_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Nature of THIS hop: NULL = normal transfer; 'returned' = money going back
    # to its origin; 'fee' = written off (kept by an intermediary as commission).
    resolution: Mapped[str | None] = mapped_column(String(12), nullable=True)
    # Funding provenance of THIS hop's own-funds portion (the source_hop_id-NULL
    # HopSource row): where the sender's own money came from. NULL = untagged.
    funding_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    funding_plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("plans.id"), nullable=True)
    logged_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    sources: Mapped[list["HopSource"]] = relationship(
        back_populates="hop", cascade="all, delete-orphan",
        foreign_keys="HopSource.hop_id", order_by="HopSource.id")
    consumers: Mapped[list["HopSource"]] = relationship(
        foreign_keys="HopSource.source_hop_id", viewonly=True)
    audit: Mapped[list["TransferHopAudit"]] = relationship(
        back_populates="hop", cascade="all, delete-orphan",
        order_by="TransferHopAudit.changed_at")
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="hop", cascade="all, delete-orphan",
        order_by="Attachment.created_at")


class HopSource(Base):
    """Where a hop's money came from. source_hop_id NULL = the from-party's
    own funds. Σ amount_minor over a hop's sources == the hop's amount_minor."""
    __tablename__ = "hop_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    hop_id: Mapped[int] = mapped_column(
        ForeignKey("transfer_hops.id", ondelete="CASCADE"), nullable=False, index=True)
    source_hop_id: Mapped[int | None] = mapped_column(
        ForeignKey("transfer_hops.id"), nullable=True, index=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)

    hop: Mapped["TransferHop"] = relationship(
        back_populates="sources", foreign_keys=[hop_id])


class TransferHopAudit(Base):
    """Immutable create/edit/delete records — mirror of LedgerEntryAudit."""
    __tablename__ = "transfer_hop_audit"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), nullable=False, index=True)
    hop_id: Mapped[int | None] = mapped_column(
        ForeignKey("transfer_hops.id", ondelete="SET NULL"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(8), nullable=False)  # create | edit | delete
    changed_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    diff: Mapped[str | None] = mapped_column(Text, nullable=True)

    hop: Mapped["TransferHop | None"] = relationship(back_populates="audit")
