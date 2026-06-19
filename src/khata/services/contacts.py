from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Contact, Plan, Loan
from . import loans as _loans, fx as _fx

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


def contact_state(session: Session, contact: Contact, *, base_currency: str,
                  as_of=None) -> dict:
    as_of = as_of or date.today()
    plans = list(session.scalars(
        select(Plan).join(Loan, Loan.plan_id == Plan.id)
        .where(Loan.contact_id == contact.id)))
    loans_out = []
    buckets = {}
    given = taken = 0
    for p in plans:
        ls = _loans.loan_state(session, p.loan, as_of=as_of)
        ccy = ls["currency"]
        b = buckets.setdefault(ccy, {"currency": ccy, "loan_count": 0,
            "principal_outstanding_minor": 0, "interest_accrued_minor": 0,
            "interest_paid_minor": 0, "interest_due_minor": 0})
        b["loan_count"] += 1
        for k in ("principal_outstanding_minor", "interest_accrued_minor",
                  "interest_paid_minor", "interest_due_minor"):
            b[k] += ls.get(k, 0)
        if ls["direction"] == "given":
            given += 1
        else:
            taken += 1
        loans_out.append({"plan_id": p.id, "name": p.name, "direction": ls["direction"],
                          "currency": ccy,
                          "principal_outstanding_minor": ls["principal_outstanding_minor"],
                          "interest_due_minor": ls["interest_due_minor"]})
    by_currency = sorted(buckets.values(), key=lambda r: -r["loan_count"])
    base = {"principal_outstanding_minor": 0, "interest_accrued_minor": 0,
            "interest_paid_minor": 0, "interest_due_minor": 0}
    base_partial = False
    for b in by_currency:
        if b["currency"] == base_currency:
            for k in base:
                base[k] += b[k]
        else:
            rate = _fx.get_rate(session, base=b["currency"], quote=base_currency)
            if rate:
                for k in base:
                    base[k] += _fx.convert(b[k], rate_micro=rate)
            else:
                base_partial = True
    return {
        "contact_id": contact.id, "name": contact.name,
        "base_currency": base_currency, "as_of": as_of.isoformat(),
        "loan_count": len(plans), "given_count": given, "taken_count": taken,
        "by_currency": by_currency, "base_total": base,
        "base_total_partial": base_partial, "loans": loans_out,
    }
