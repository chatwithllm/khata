from datetime import date

from sqlalchemy import BigInteger, Boolean, Date, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import expression

from ..db import Base


class Loan(Base):
    __tablename__ = "loans"

    plan_id: Mapped[int] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), primary_key=True)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)         # given | taken
    # loan category — conveys the loan's nature + what backs it (personal=unsecured,
    # gold/home/vehicle=secured by that asset, etc.). See LOAN_KINDS in services/loans.py.
    kind: Mapped[str] = mapped_column(String(16), nullable=False,
                                      default="personal", server_default="personal")
    counterparty: Mapped[str | None] = mapped_column(Text, nullable=True)
    interest_type: Mapped[str] = mapped_column(String(10), nullable=False)    # none | monthly | yearly
    rate_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    basis: Mapped[str] = mapped_column(String(12), nullable=False, default="reducing")
    repayment: Mapped[str] = mapped_column(String(12), nullable=False, default="bullet")
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    tenure_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    secured: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=expression.false())
    collateral_plan_id: Mapped[int | None] = mapped_column(ForeignKey("plans.id"), nullable=True)
    # Inline collateral details (e.g. for a gold loan, when you don't model the gold as a
    # separate holding): weight + the rate at loan time + market value → drives LTV.
    collateral_qty_micro: Mapped[int | None] = mapped_column(BigInteger, nullable=True)   # weight ×1e6, in collateral_unit
    collateral_unit: Mapped[str | None] = mapped_column(String(12), nullable=True)        # gram | ounce
    collateral_rate_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # price at loan time, per rate_basis
    collateral_rate_basis: Mapped[str | None] = mapped_column(String(12), nullable=True)  # per_gram | per_10gram | per_ounce
    collateral_value_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True) # market value at loan time

    plan: Mapped["Plan"] = relationship(back_populates="loan", foreign_keys=[plan_id])
