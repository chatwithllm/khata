import json
import os
from datetime import datetime, timezone

from flask import Blueprint, Response, current_app, g, jsonify, request, session
from sqlalchemy import select

from ..models import User
from ..services import backup
from .auth import current_user

bp = Blueprint("backup", __name__, url_prefix="/api")


def _is_operator(user) -> bool:
    """Backup/restore expose and rewrite the WHOLE instance (every user, incl. password
    hashes so logins survive a restore). Restricted to an ADMIN (`users.is_admin`). For
    backward compatibility the legacy operator definition still grants access:
    KHATA_OPERATOR_EMAILS (comma-separated) if set, else the first registered user. The
    de8admin01 migration bootstraps that first user as an admin, so the two converge."""
    if getattr(user, "is_admin", False) and not getattr(user, "disabled", False):
        return True
    allow = os.environ.get("KHATA_OPERATOR_EMAILS", "").strip()
    if allow:
        emails = {e.strip().lower() for e in allow.split(",") if e.strip()}
        return (user.email or "").lower() in emails
    first_id = g.db.scalar(select(User.id).order_by(User.id).limit(1))
    return first_id is not None and user.id == first_id


def _require_operator():
    user = current_user()
    if user is None:
        return None, (jsonify(error="unauthenticated"), 401)
    if not _is_operator(user):
        return None, (jsonify(error="forbidden",
                              detail="backup/restore is restricted to the instance operator"), 403)
    return user, None


def _pre_restore_dir() -> str:
    """Where to drop the automatic pre-restore snapshot — a 'backups' dir next to the
    SQLite file, falling back to the working dir. Locked to owner-only (0o700)."""
    url = current_app.config["KHATA"].database_url
    base = "."
    if url.startswith("sqlite:///"):
        db_path = url[len("sqlite:///"):]
        base = os.path.dirname(os.path.abspath(db_path)) or "."
    d = os.path.join(base, "backups")
    os.makedirs(d, mode=0o700, exist_ok=True)
    try:
        os.chmod(d, 0o700)  # tighten even if it pre-existed with looser perms
    except OSError:
        pass
    return d


@bp.get("/backup")
def download_backup():
    """Whole-instance JSON snapshot, as a file download. Operator-only — the file contains
    every user's data and password hashes, so the caller must be the instance operator."""
    user, err = _require_operator()
    if err:
        return err
    data = backup.export_all(g.db)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    body = json.dumps(data, separators=(",", ":"))
    return Response(body, mimetype="application/json", headers={
        "Content-Disposition": f'attachment; filename="khata-backup-{stamp}.json"',
        "Cache-Control": "no-store"})


@bp.post("/restore")
def restore_backup():
    """REPLACE this instance's data with an uploaded backup (wipe + load). Operator-only —
    a restore recreates users with arbitrary password hashes, so an untrusted caller could
    inject a backdoor account. Auto-saves a pre-restore snapshot first. Accepts a
    multipart file field 'file' or a raw JSON body."""
    user, err = _require_operator()
    if err:
        return err

    # Read the uploaded backup (multipart file or raw JSON body).
    data = None
    if "file" in request.files:
        try:
            data = json.load(request.files["file"].stream)
        except (ValueError, UnicodeDecodeError):
            return jsonify(error="invalid", detail="uploaded file is not valid JSON"), 400
    else:
        data = request.get_json(silent=True)
    if data is None:
        return jsonify(error="invalid", detail="no backup provided"), 400

    # Safety net: snapshot current state before mutating. Owner-only file (0o600). Best-effort.
    pre_restore_saved = False
    try:
        snapshot = backup.export_all(g.db)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        path = os.path.join(_pre_restore_dir(), f"pre-restore-{stamp}.json")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(snapshot, fh, separators=(",", ":"))
        pre_restore_saved = True
    except OSError:
        pre_restore_saved = False  # couldn't write the safety file — proceed anyway

    try:
        stats = backup.import_replace(g.db, data)
        g.db.commit()
    except backup.BackupError as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    except Exception:
        g.db.rollback()
        raise

    # The restore may have removed or re-id'd the operator's account. Re-point the
    # session at the restored row (matched by email) — or log them out if it's gone.
    logged_out = False
    restored = g.db.scalar(select(User).where(User.email == user.email))
    if restored is not None:
        session["user_id"] = restored.id
    else:
        session.clear()
        logged_out = True
    # Note: do NOT leak the absolute server path — just whether the safety net was written.
    return jsonify(ok=True, stats=stats, pre_restore_saved=pre_restore_saved,
                   logged_out=logged_out), 200
