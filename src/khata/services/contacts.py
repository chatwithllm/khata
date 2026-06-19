from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Contact, Plan, Loan

PHOTO_MAX = 220_000   # ~200KB data-URL cap (mirrors user avatar)


class ContactError(Exception):
    pass


def _clean(v):
    if v is None:
        return None
    v = str(v).strip()
    return v or None


def create_contact(session: Session, *, owner_id, name, phone=None, email=None,
                   address=None, notes=None, photo=None) -> Contact:
    nm = (name or "").strip()
    if not nm:
        raise ContactError("name is required")
    if photo and len(photo) > PHOTO_MAX:
        raise ContactError("photo too large")
    ct = Contact(owner_user_id=owner_id, name=nm[:120], phone=_clean(phone),
                 email=_clean(email), address=_clean(address), notes=_clean(notes),
                 photo=photo or None)
    session.add(ct)
    session.flush()
    return ct


def get_contact(session: Session, *, owner_id, contact_id) -> Contact | None:
    ct = session.get(Contact, contact_id)
    if ct is None or ct.owner_user_id != owner_id:
        return None
    return ct


def list_contacts(session: Session, *, owner_id) -> list[Contact]:
    return list(session.scalars(
        select(Contact).where(Contact.owner_user_id == owner_id)
        .order_by(Contact.name)))


def update_contact(session: Session, *, owner_id, contact_id, **fields) -> Contact:
    ct = get_contact(session, owner_id=owner_id, contact_id=contact_id)
    if ct is None:
        raise ContactError("no such contact")
    if "name" in fields:
        nm = (fields["name"] or "").strip()
        if not nm:
            raise ContactError("name is required")
        ct.name = nm[:120]
    for f in ("phone", "email", "address", "notes"):
        if f in fields:
            setattr(ct, f, _clean(fields[f]))
    if "photo" in fields:
        ph = fields["photo"]
        if ph and len(ph) > PHOTO_MAX:
            raise ContactError("photo too large")
        ct.photo = ph or None
    ct.updated_at = datetime.now(timezone.utc)
    session.flush()
    return ct


def delete_contact(session: Session, *, owner_id, contact_id) -> None:
    ct = get_contact(session, owner_id=owner_id, contact_id=contact_id)
    if ct is None:
        raise ContactError("no such contact")
    session.delete(ct)
    session.flush()


def assign_loan(session: Session, *, owner_id, plan: Plan, contact_id) -> None:
    if plan.loan is None:
        raise ContactError("not a loan plan")
    if contact_id is None:
        plan.loan.contact_id = None
    else:
        ct = get_contact(session, owner_id=owner_id, contact_id=contact_id)
        if ct is None:
            raise ContactError("no such contact")
        plan.loan.contact_id = ct.id
    session.flush()
