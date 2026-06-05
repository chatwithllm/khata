from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


class Holding(Base):
    __tablename__ = "holdings"

    plan_id: Mapped[int] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), primary_key=True)
    asset_class: Mapped[str] = mapped_column(String(12), nullable=False)  # gold|silver|equity|mf|cash|other
    unit: Mapped[str] = mapped_column(String(16), nullable=False)         # gram|share|unit|...
    symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    purity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    current_price_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    price_as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    plan: Mapped["Plan"] = relationship(back_populates="holding")
