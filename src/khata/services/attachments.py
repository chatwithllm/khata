"""Attachments — supporting proof (receipt photos, scanned PDFs, chat screenshots,
signed agreements) attached to either a ledger entry or a contact. Bytes are stored in
the DB; the mime is decided by the file's MAGIC BYTES, never the declared extension (a
tight allowlist: common images, PDF, and Office docs). Anything we can't positively
identify is rejected.
"""
import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Attachment, LedgerEntry

MAX_SIZE = 25 * 1024 * 1024   # 25 MB per file

# Mimes we render inline in the browser; everything else downloads.
INLINE_MIMES = {"image/jpeg", "image/png", "image/gif", "image/webp",
                "image/heic", "application/pdf"}


class AttachmentError(Exception):
    pass


def _sniff(raw: bytes) -> str | None:
    """Return a canonical mime from the file's magic bytes, or None if not allowlisted."""
    if len(raw) < 12:
        return None
    if raw[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    if raw[:4] == b"%PDF":
        return "application/pdf"
    # HEIC/HEIF: ISO-BMFF "ftyp" box with an image brand.
    if raw[4:8] == b"ftyp" and raw[8:12] in (b"heic", b"heix", b"hevc", b"heim",
                                             b"heis", b"hevm", b"mif1", b"heif"):
        return "image/heic"
    # OOXML (docx/xlsx/pptx) — a ZIP; confirm it is actually an Office package, not any zip.
    if raw[:4] == b"PK\x03\x04":
        head = raw[:4000]
        if b"word/" in head:
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if b"xl/" in head:
            return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if b"ppt/" in head:
            return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        return None   # a bare zip is not proof — reject
    # Legacy OLE compound (.doc/.xls/.ppt)
    if raw[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return "application/msword"
    return None


def add_attachment(session: Session, *, uploaded_by: int, filename: str, raw: bytes,
                   entry: LedgerEntry | None = None,
                   contact=None) -> Attachment:
    """Attach a file to exactly one parent: a ledger entry OR a contact (not both, not neither)."""
    if (entry is None) == (contact is None):
        raise AttachmentError("attachment needs exactly one parent (entry or contact)")
    if not raw:
        raise AttachmentError("empty file")
    if len(raw) > MAX_SIZE:
        raise AttachmentError(f"file too large (max {MAX_SIZE // (1024 * 1024)} MB)")
    mime = _sniff(raw)
    if mime is None:
        raise AttachmentError("unsupported file type — images, PDF, or Office documents only")
    name = (filename or "file").strip()[:255] or "file"
    att = Attachment(
        ledger_entry_id=entry.id if entry is not None else None,
        contact_id=contact.id if contact is not None else None,
        uploaded_by_user_id=uploaded_by,
        filename=name, mime=mime, size=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(), data=raw)
    session.add(att)
    session.flush()
    return att


def list_for_entry(session: Session, entry_id: int) -> list[Attachment]:
    return list(session.scalars(
        select(Attachment).where(Attachment.ledger_entry_id == entry_id)
        .order_by(Attachment.created_at, Attachment.id)))


def list_for_contact(session: Session, contact_id: int) -> list[Attachment]:
    return list(session.scalars(
        select(Attachment).where(Attachment.contact_id == contact_id)
        .order_by(Attachment.created_at, Attachment.id)))


def meta(att: Attachment) -> dict:
    return {"id": att.id, "filename": att.filename, "mime": att.mime,
            "size": att.size, "is_image": att.mime.startswith("image/"),
            "inline": att.mime in INLINE_MIMES,
            "uploaded_by": att.uploaded_by_user_id,
            "created_at": att.created_at.isoformat() if att.created_at else None}


def get(session: Session, att_id: int) -> Attachment | None:
    return session.get(Attachment, att_id)


def delete(session: Session, att: Attachment) -> None:
    session.delete(att)
    session.flush()
