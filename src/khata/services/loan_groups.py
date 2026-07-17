from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Plan, Contact
from . import loans as _loans, fx as _fx


def _side():
    return {"count": 0, "principal_minor": 0, "interest_monthly_minor": 0,
            "next_due_minor": 0, "interest_due_minor": 0}


def grouped_loans(session: Session, *, owner_id, base_currency: str, as_of=None) -> dict:
    as_of = as_of or date.today()
    plans = list(session.scalars(
        select(Plan).where(Plan.owner_user_id == owner_id, Plan.type == "loan")))
    groups = {}
    partial = False

    _rates = {}

    def conv(v, ccy):
        nonlocal partial
        if ccy == base_currency:
            return v
        if ccy not in _rates:
            _rates[ccy] = _fx.get_rate(session, base=ccy, quote=base_currency)
        rate = _rates[ccy]
        if not rate:
            partial = True
            return 0
        return _fx.convert(v, rate_micro=rate)

    for p in plans:
        loan = p.loan
        if loan is None:
            continue
        ls = _loans.loan_state(session, loan, as_of=as_of)
        ccy = ls["currency"]
        out = ls["principal_outstanding_minor"]
        mr = _loans._monthly_rate(loan.interest_type, loan.rate_bps)
        interest_monthly = int((Decimal(out) * mr).quantize(Decimal(1), rounding=ROUND_HALF_UP))
        next_due = interest_monthly

        if loan.contact_id is not None:
            ct = session.get(Contact, loan.contact_id)
            name = (ct.name if ct else (loan.counterparty or "")).strip() or "Unlabeled"
            cid = loan.contact_id
        else:
            name = (loan.counterparty or "").strip() or "Unlabeled"
            cid = None
        norm = name.lower()

        g = groups.get(norm)
        if g is None:
            g = {"key": norm, "name": name, "contact_id": cid,
                 "given": _side(), "taken": _side(), "loans": [], "_cids": set()}
            groups[norm] = g
        g["_cids"].add(cid)

        side = g["given"] if loan.direction == "given" else g["taken"]
        side["count"] += 1
        ob = conv(out, ccy)
        side["principal_minor"] += ob
        side["interest_monthly_minor"] += conv(interest_monthly, ccy)
        side["next_due_minor"] += conv(next_due, ccy)
        side["interest_due_minor"] += conv(ls["interest_due_minor"], ccy)   # accrued unpaid
        g["loans"].append({
            "plan_id": p.id, "name": p.name, "direction": loan.direction,
            "currency": ccy, "outstanding_minor": out,
            "interest_monthly_minor": interest_monthly,
            "outstanding_base_minor": ob})

    out_groups = []
    for g in groups.values():
        cids = {c for c in g["_cids"] if c is not None}
        g["contact_id"] = next(iter(cids)) if len(cids) == 1 else None
        del g["_cids"]
        g["total_base_minor"] = g["given"]["principal_minor"] + g["taken"]["principal_minor"]
        out_groups.append(g)
    out_groups.sort(key=lambda g: -g["total_base_minor"])

    base_total = {"lent": _side(), "borrowed": _side()}
    for g in out_groups:
        for k in ("count", "principal_minor", "interest_monthly_minor", "next_due_minor",
                  "interest_due_minor"):
            base_total["lent"][k] += g["given"][k]
            base_total["borrowed"][k] += g["taken"][k]

    sankey = _build_sankey(out_groups)
    return {"base_currency": base_currency, "as_of": as_of.isoformat(),
            "groups": out_groups, "base_total": base_total, "partial": partial,
            "sankey": sankey}


def _build_sankey(groups: list) -> dict:
    nodes, links = [], []
    if not groups:
        return {"nodes": nodes, "links": links}
    have_lent = any(g["given"]["count"] for g in groups)
    have_taken = any(g["taken"]["count"] for g in groups)
    if have_lent:
        nodes.append({"id": "dir:lent", "label": "Lent", "kind": "direction"})
    if have_taken:
        nodes.append({"id": "dir:borrowed", "label": "Borrowed", "kind": "direction"})
    for gi, g in enumerate(groups):
        cnode = f"ct:{gi}"
        nodes.append({"id": cnode, "label": g["name"], "kind": "contact",
                      "contact_id": g["contact_id"]})
        for side, dnode in (("given", "dir:lent"), ("taken", "dir:borrowed")):
            val = g[side]["principal_minor"]
            if val > 0:
                links.append({"source": dnode, "target": cnode, "value_minor": val})
        for ln in g["loans"]:
            if ln["outstanding_base_minor"] <= 0:
                continue
            lnode = f"ln:{ln['plan_id']}"
            nodes.append({"id": lnode, "label": ln["name"], "kind": "loan",
                          "plan_id": ln["plan_id"]})
            links.append({"source": cnode, "target": lnode,
                          "value_minor": ln["outstanding_base_minor"]})
    return {"nodes": nodes, "links": links}
