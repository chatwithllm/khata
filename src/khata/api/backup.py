import json
import os
from datetime import datetime, timezone

from flask import Blueprint, Response, current_app, g, jsonify, request

from ..services import backup
from .auth import current_user

bp = Blueprint("backup", __name__, url_prefix="/api")


def _pre_restore_dir() -> str:
    """Where to drop the automatic pre-restore snapshot — a 'backups' dir next to the
    SQLite file, falling back to the working dir. Best-effort: a failed save never blocks
    a restore (the file is just a safety net)."""
    url = current_app.config["KHATA"].database_url
    base = "."
    if url.startswith("sqlite:///"):
        db_path = url[len("sqlite:///"):]
        base = os.path.dirname(os.path.abspath(db_path)) or "."
    d = os.path.join(base, "backups")
    os.makedirs(d, exist_ok=True)
    return d


@bp.get("/backup")
def download_backup():
    """Whole-instance JSON snapshot, as a file download."""
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    data = backup.export_all(g.db)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    body = json.dumps(data, separators=(",", ":"))
    return Response(body, mimetype="application/json", headers={
        "Content-Disposition": f'attachment; filename="khata-backup-{stamp}.json"',
        "Cache-Control": "no-store"})


@bp.post("/restore")
def restore_backup():
    """Merge an uploaded backup into this instance. Auto-saves a pre-restore snapshot
    first so a bad restore is recoverable. Accepts a multipart file field 'file' or a
    raw JSON body."""
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401

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

    # Safety net: snapshot current state before mutating. Best-effort.
    pre_restore_path = None
    try:
        snapshot = backup.export_all(g.db)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        pre_restore_path = os.path.join(_pre_restore_dir(), f"pre-restore-{stamp}.json")
        with open(pre_restore_path, "w") as fh:
            json.dump(snapshot, fh, separators=(",", ":"))
    except OSError:
        pre_restore_path = None  # couldn't write the safety file — proceed anyway

    try:
        stats = backup.import_merge(g.db, data)
        g.db.commit()
    except backup.BackupError as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    except Exception:
        g.db.rollback()
        raise
    return jsonify(ok=True, stats=stats, pre_restore_saved=pre_restore_path), 200
