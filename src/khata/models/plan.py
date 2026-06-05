from datetime import date, datetime, timezone

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    asset: Mapped["AssetPurchase | None"] = relationship(
        back_populates="plan", uselist=False, cascade="all, delete-orphan")
    loan: Mapped["Loan | None"] = relationship(
        back_populates="plan", uselist=False, cascade="all, delete-orphan")
    holding: Mapped["Holding | None"] = relationship(
        back_populates="plan", uselist=False, cascade="all, delete-orphan")
    chit: Mapped["Chit | None"] = relationship(
        back_populates="plan", uselist=False, cascade="all, delete-orphan")
    installments: Mapped[list["Installment"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", order_by="Installment.seq")
    ledger_entries: Mapped[list["LedgerEntry"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan",
        order_by="LedgerEntry.occurred_at")
    memberships: Mapped[list["PlanMembership"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan")


class AssetPurchase(Base):
    __tablename__ = "asset_purchases"

    plan_id: Mapped[int] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), primary_key=True)
    total_price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)

    plan: Mapped["Plan"] = relationship(back_populates="asset")


class Installment(Base):
    __tablename__ = "installments"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    planned_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    plan: Mapped["Plan"] = relationship(back_populates="installments")
