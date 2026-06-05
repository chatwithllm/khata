from sqlalchemy import BigInteger, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


class Retirement(Base):
    __tablename__ = "retirements"

    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"), primary_key=True)
    current_balance_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    monthly_contribution_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    employer_match_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    annual_return_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=800)
    inflation_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=600)
    current_age: Mapped[int] = mapped_column(Integer, nullable=False)
    retirement_age: Mapped[int] = mapped_column(Integer, nullable=False)

    plan: Mapped["Plan"] = relationship(back_populates="retirement")
