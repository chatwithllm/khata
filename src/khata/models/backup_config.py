from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class BackupConfig(Base):
    """Singleton (id=1) holding the automatic-backup schedule. Edited by admins; read by
    the in-app scheduler each tick. `last_run_at` doubles as the cross-worker claim token
    (see services/backup_store.claim_due) so two gunicorn workers never double-back-up."""
    __tablename__ = "backup_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    # 'daily' | 'weekly'
    frequency: Mapped[str] = mapped_column(String(12), nullable=False, default="daily", server_default="daily")
    # hour-of-day (0-23, server local time) at/after which the backup may run
    hour: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
    # how many auto-* snapshots to keep before pruning oldest
    retention: Mapped[int] = mapped_column(Integer, nullable=False, default=14, server_default="14")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(200), nullable=True)
