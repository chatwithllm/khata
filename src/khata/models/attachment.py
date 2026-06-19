from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Attachment(Base):
    """Supporting proof for a ledger entry — a receipt photo, a scanned PDF, a chat
    screenshot. Bytes live in the DB (LargeBinary) so the one-file JSON backup keeps
    round-tripping (the backup serializer base64-encodes the blob on export). Mime is
    validated against the file's magic bytes server-side, not the declared extension.
    """
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    ledger_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("ledger_entries.id", ondelete="CASCADE"), nullable=True, index=True)
    contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), nullable=True, index=True)
    uploaded_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime: Mapped[str] = mapped_column(String(100), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    entry: Mapped["LedgerEntry"] = relationship(back_populates="attachments")
    contact: Mapped["Contact"] = relationship(back_populates="attachments")
