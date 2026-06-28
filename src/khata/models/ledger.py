from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), nullable=False, index=True)
    logged_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    direction: Mapped[str] = mapped_column(String(3), nullable=False, default="out")
    kind: Mapped[str | None] = mapped_column(String(24), nullable=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    quantity_micro: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    funding_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    proof_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Provenance link: when this payment was funded by another plan (e.g. an asset
    # contribution paid out of a loan), point to that source plan. Records the money's
    # chain (loan → asset contribution) without double-counting in either plan's totals.
    funding_plan_id: Mapped[int | None] = mapped_column(ForeignKey("plans.id"), nullable=True)
    # Contribution-amount agreement (two-party): agreed | pending | countered.
    # 'pending' = the attributed contributor (logged_by_user_id) must confirm the amount;
    # 'countered' = they proposed counter_amount_minor and the owner must accept or re-counter.
    # Self-logged / owner-self entries start 'agreed'. The recorded amount_minor always counts
    # toward plan totals; this status only flags attribution accuracy.
    amount_status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="agreed")
    counter_amount_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # FX snapshot: counter-currency units per 1 entry-currency unit, ×1e6, captured at
    # log time (editable later). NULL = no rate known. The counter value is always
    # DERIVED (services/fx.convert) — never stored. See docs/specs/2026-06-11-fx-snapshot-design.md.
    fx_rate_micro: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    fx_counter_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    plan: Mapped["Plan"] = relationship(back_populates="ledger_entries", foreign_keys=[plan_id])
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="entry", cascade="all, delete-orphan",
        order_by="Attachment.created_at")
    audit: Mapped[list["LedgerEntryAudit"]] = relationship(
        back_populates="entry", cascade="all, delete-orphan",
        order_by="LedgerEntryAudit.changed_at")


class LedgerEntryAudit(Base):
    """Immutable record of every create / edit / delete on a ledger entry.
    entry_id goes NULL (SET NULL) when the parent entry is deleted so the
    delete record survives while plan_id lets us query the full plan history."""
    __tablename__ = "ledger_entry_audit"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), nullable=False, index=True)
    entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("ledger_entries.id", ondelete="SET NULL"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(8), nullable=False)   # create | edit | delete
    changed_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    snapshot: Mapped[str] = mapped_column(Text, nullable=False)       # JSON of entry state
    diff: Mapped[str | None] = mapped_column(Text, nullable=True)     # JSON {field:{old,new}} for edits

    entry: Mapped["LedgerEntry | None"] = relationship(back_populates="audit")
