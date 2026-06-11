from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    google_sub: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
    base_currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="INR", server_default="INR")
    # Cropped square avatar as a data URL (data:image/...;base64,...), set via the crop
    # tool. Stored server-side so every member sees each contributor's photo, and so it
    # travels with a backup. Capped small (~256px) at the API layer.
    avatar: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Admin can manage users + run backup/restore (see services/admin.py). The first
    # registered user is bootstrapped admin by migration de8admin01.
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    # A disabled account cannot sign in and its live session stops resolving (current_user
    # returns None) — data is retained, the block is reversible.
    disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    def __repr__(self) -> str:
        return f"<User {self.email}>"
