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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    plan: Mapped["Plan"] = relationship(back_populates="ledger_entries", foreign_keys=[plan_id])
