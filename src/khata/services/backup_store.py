"""Automatic-backup storage + scheduling logic.

Auto-backups are whole-instance JSON snapshots (same format as the manual download /
restore) written to a `backups/` dir next to the SQLite file as `auto-<stamp>.json`,
pruned to the configured retention. The scheduler (khata/scheduler.py) calls `tick`
hourly; `claim_due` makes the "is it time?" decision atomic across gunicorn workers so
two workers never produce a double backup.
"""
import json
import os
import re
from datetime import datetime, timedelta

from sqlalchemy import select, update, or_
from sqlalchemy.orm import Session

from ..models import BackupConfig
from . import backup

_AUTO_RE = re.compile(r"^auto-\d{8}-\d{6}\.json$")


def backups_dir(database_url: str) -> str:
    """The `backups/` dir next to the SQLite file (0o700), created if missing."""
    base = "."
    if database_url.startswith("sqlite:///"):
        db_path = database_url[len("sqlite:///"):]
        base = os.path.dirname(os.path.abspath(db_path)) or "."
    d = os.path.join(base, "backups")
    os.makedirs(d, mode=0o700, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def get_config(session: Session) -> BackupConfig:
    cfg = session.get(BackupConfig, 1)
    if cfg is None:                       # metadata-created DBs have no seed row
        cfg = BackupConfig(id=1)
        session.add(cfg)
        session.flush()
    return cfg


def safe_backup_name(name: str) -> str | None:
    """Accept only a bare `auto-YYYYMMDD-HHMMSS.json` basename (no path traversal)."""
    name = os.path.basename(name or "")
    return name if _AUTO_RE.match(name) else None


def list_backups(directory: str) -> list[dict]:
    out = []
    if os.path.isdir(directory):
        for fn in os.listdir(directory):
            if not _AUTO_RE.match(fn):
                continue
            p = os.path.join(directory, fn)
            try:
                st = os.stat(p)
            except OSError:
                continue
            out.append({"filename": fn, "size": st.st_size,
                        "created_at": datetime.fromtimestamp(st.st_mtime).isoformat()})
    out.sort(key=lambda r: r["filename"], reverse=True)   # newest first (stamp sorts)
    return out


def prune(directory: str, retention: int) -> int:
    files = sorted((f["filename"] for f in list_backups(directory)), reverse=True)
    doomed = files[max(0, retention):]
    for fn in doomed:
        try:
            os.remove(os.path.join(directory, fn))
        except OSError:
            pass
    return len(doomed)


def write_snapshot(session: Session, directory: str, *, stamp: str) -> dict:
    """Serialize the whole instance to auto-<stamp>.json (0o600)."""
    data = backup.export_all(session)
    fn = f"auto-{stamp}.json"
    path = os.path.join(directory, fn)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh, separators=(",", ":"))
    return {"filename": fn, "size": os.path.getsize(path)}


def run_backup(session: Session, *, database_url: str, retention: int, stamp: str) -> dict:
    """Write a snapshot then prune to `retention`. Returns {filename, size, pruned}."""
    directory = backups_dir(database_url)
    res = write_snapshot(session, directory, stamp=stamp)
    res["pruned"] = prune(directory, retention)
    return res


# ── scheduling decision (pure + testable) ──

def claim_threshold(cfg: BackupConfig, now: datetime) -> datetime:
    """The cutoff for `last_run_at`: a backup is due only if the last one ran before this.
    Daily → start of today; weekly → 7 days ago. (`now` is naive server-local.)"""
    if cfg.frequency == "weekly":
        return now - timedelta(days=7)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def is_due(cfg: BackupConfig, now: datetime) -> bool:
    """Whether a backup should run right now (before claiming). Enabled, past the
    configured hour-of-day, and not already run this period."""
    if not cfg.enabled:
        return False
    if now.hour < (cfg.hour or 0):
        return False
    last = cfg.last_run_at
    return last is None or last < claim_threshold(cfg, now)


def claim_due(session: Session, *, now: datetime) -> bool:
    """Atomically claim the current backup slot. Returns True for exactly one caller
    (the one whose UPDATE flips last_run_at); concurrent workers get False."""
    cfg = get_config(session)
    if not cfg.enabled or now.hour < (cfg.hour or 0):
        return False
    threshold = claim_threshold(cfg, now)
    res = session.execute(
        update(BackupConfig).where(
            BackupConfig.id == 1,
            or_(BackupConfig.last_run_at.is_(None), BackupConfig.last_run_at < threshold),
        ).values(last_run_at=now))
    session.commit()
    return res.rowcount == 1
