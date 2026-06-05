from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class FxRate(Base):
    __tablename__ = "fx_rates"
    __table_args__ = (UniqueConstraint("base_currency", "quote_currency", name="uq_fx_pair"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    quote_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    rate_micro: Mapped[int] = mapped_column(BigInteger, nullable=False)  # base units per 1 quote unit, x1e6
    as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
