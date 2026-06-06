from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PlanMembership(Base):
    __tablename__ = "plan_memberships"
    __table_args__ = (UniqueConstraint("plan_id", "user_id", name="uq_plan_member"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="contributor")
    # invited | active | declined — new shares start 'invited' until the user accepts.
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    plan: Mapped["Plan"] = relationship(back_populates="memberships")
