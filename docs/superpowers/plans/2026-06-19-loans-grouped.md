# Loans Grouped by Contact + Sankey Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A "By contact" grouping mode on the Loans page (contact-first, given/taken inside, per-group principal/interest/next-due) plus a hand-rolled Sankey of the loan book — fed by a new testable backend endpoint.

**Architecture:** New `loan_groups` service computes the grouped aggregation + Sankey nodes/links (owner-scoped, base-currency, reusing `loan_state`/`fx`). A read-only `GET /api/plans/loans/grouped` exposes it. `app.html` gains a By-direction↔By-contact toggle; By-contact renders the groups + an SVG Sankey. No migration.

**Tech Stack:** Python 3.12, Flask, SQLAlchemy, pytest; vanilla-JS + hand-rolled SVG in `app.html`.

---

## File Structure

- **Create** `src/khata/services/loan_groups.py` — `grouped_loans(...)` (T1).
- **Modify** `src/khata/api/plans.py` — `GET /loans/grouped` route (T2).
- **Modify** `src/khata/static/app.html` — toggle + by-contact group render (T3), Sankey SVG (T4).
- **Modify** `docs/specs/khata-AS-BUILT.md` (T5).
- **Tests:** `tests/test_loan_groups.py` (T1), `tests/test_loan_groups_api.py` (T2).

Verified facts:
- `loans._monthly_rate(interest_type, rate_bps) -> Decimal` (monthly=bps/10000, yearly=bps/120000, none=0).
- `loans.loan_state(session, loan, as_of) -> {currency, direction, principal_outstanding_minor, ...}`. Next-month interest = `round_half_up(outstanding × monthly_rate)`.
- `fx.get_rate(session, base, quote) -> int|None` (rate_micro), `fx.convert(amount_minor, *, rate_micro) -> int`.
- `user.base_currency` (default "INR"); `Plan.type=='loan'`, `plan.loan`, `loan.contact_id`, `loan.counterparty`, `Contact.name`.
- `_summary()` in `plans.py` already returns `contact_id` + `counterparty` for loans.
- Loan plans query: `select(Plan).where(Plan.owner_user_id==owner_id, Plan.type=='loan')`.
- The plans blueprint has url_prefix `/api/plans`; `<int:plan_id>` converter won't match the literal `loans` segment, so `/loans/grouped` is collision-free.

Test command (venv in primary checkout):
`cd /tmp/khata-loans-grouped && PYTHONPATH=src /Users/assistant/dev/active/khata/.venv/bin/pytest <args>`

---

### Task 1: `loan_groups` service

**Files:** create `src/khata/services/loan_groups.py`; test `tests/test_loan_groups.py`.

- [ ] **Step 1: Write the failing tests**

`tests/test_loan_groups.py`:
```python
from datetime import date, datetime, timezone

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User
from khata.services.loans import create_loan_plan, add_disbursement
from khata.services import contacts as c, fx
from khata.services.loan_groups import grouped_loans


@pytest.fixture
def ctx():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s:
        u = User(email="a@b.com", display_name="A", password_hash="x")
        o = User(email="z@z.com", display_name="O", password_hash="x")
        s.add_all([u, o]); s.flush()
        yield s, u, o


def _loan(s, u, name, ccy, direction, principal, rate_bps=300, counterparty=None,
          contact_id=None):
    p = create_loan_plan(s, owner_id=u.id, name=name, currency=ccy, direction=direction,
                         interest_type="monthly", rate_bps=rate_bps,
                         start_date=date(2024, 1, 1), counterparty=counterparty)
    add_disbursement(s, plan=p, user_id=u.id, amount_minor=principal,
                     occurred_at=datetime(2024, 1, 1, tzinfo=timezone.utc))
    if contact_id is not None:
        c.assign_loan(s, owner_id=u.id, plan=p, contact_id=contact_id)
    s.flush()
    return p


def test_groups_by_contact_then_counterparty_merge(ctx):
    s, u, o = ctx
    ct = c.create_contact(s, owner_id=u.id, name="Sunil"); s.flush()
    _loan(s, u, "L1", "INR", "given", 100000, contact_id=ct.id)        # linked
    _loan(s, u, "L2", "INR", "given", 50000, counterparty="sunil")     # text, same name (lower)
    _loan(s, u, "L3", "INR", "taken", 30000, counterparty="Bank")      # different
    out = grouped_loans(s, owner_id=u.id, base_currency="INR")
    by = {g["name"].lower(): g for g in out["groups"]}
    # the linked 'Sunil' and the text 'sunil' merge into one group
    assert "sunil" in by
    sunil = by["sunil"]
    assert sunil["given"]["count"] == 2 and sunil["given"]["principal_minor"] == 150000
    assert sunil["contact_id"] == ct.id  # all linked-or-mergeable to that one contact
    assert "bank" in by and by["bank"]["taken"]["count"] == 1


def test_per_side_sums_interest_and_next_due(ctx):
    s, u, o = ctx
    _loan(s, u, "L", "INR", "given", 200000, rate_bps=300, counterparty="K")  # 3%/mo
    out = grouped_loans(s, owner_id=u.id, base_currency="INR")
    g = out["groups"][0]["given"]
    assert g["principal_minor"] == 200000
    # next month interest = 3% of 2,00,000 = 6,000 (minor)
    assert g["interest_monthly_minor"] == 6000
    assert g["next_due_minor"] == g["interest_monthly_minor"]   # interest-only


def test_multi_currency_base_conversion_and_partial(ctx):
    s, u, o = ctx
    fx.set_rate(s, base="USD", quote="INR", rate_micro=83_000_000, as_of=None); s.flush()
    ct = c.create_contact(s, owner_id=u.id, name="X"); s.flush()
    _loan(s, u, "I", "INR", "given", 100000, contact_id=ct.id)
    _loan(s, u, "U", "USD", "given", 2000, contact_id=ct.id)
    out = grouped_loans(s, owner_id=u.id, base_currency="INR")
    g = [x for x in out["groups"] if x["name"] == "X"][0]
    # 1,00,000 INR + 2000 USD*83 = 1,00,000 + 1,66,000 = 2,66,000
    assert g["given"]["principal_minor"] == 266000
    assert out["partial"] is False


def test_partial_flag_when_rate_missing(ctx):
    s, u, o = ctx
    _loan(s, u, "U", "USD", "given", 2000, counterparty="K")   # no USD->INR rate seeded
    out = grouped_loans(s, owner_id=u.id, base_currency="INR")
    assert out["partial"] is True


def test_sankey_invariant(ctx):
    s, u, o = ctx
    ct = c.create_contact(s, owner_id=u.id, name="S"); s.flush()
    _loan(s, u, "L1", "INR", "given", 100000, contact_id=ct.id)
    _loan(s, u, "L2", "INR", "given", 60000, contact_id=ct.id)
    out = grouped_loans(s, owner_id=u.id, base_currency="INR")
    sk = out["sankey"]
    # contact node total in == total out == 160000
    contact_nodes = [n for n in sk["nodes"] if n["kind"] == "contact"]
    assert contact_nodes, "expected a contact node"
    cid = contact_nodes[0]["id"]
    incoming = sum(l["value_minor"] for l in sk["links"] if l["target"] == cid)
    outgoing = sum(l["value_minor"] for l in sk["links"] if l["source"] == cid)
    assert incoming == outgoing == 160000
    # direction->contact links sum to base_total lent
    lent_total = out["base_total"]["lent"]["principal_minor"]
    assert lent_total == 160000


def test_owner_scoping(ctx):
    s, u, o = ctx
    _loan(s, u, "mine", "INR", "given", 100000, counterparty="K")
    _loan(s, o, "theirs", "INR", "given", 999999, counterparty="Z")
    out = grouped_loans(s, owner_id=u.id, base_currency="INR")
    names = {g["name"] for g in out["groups"]}
    assert names == {"K"} and out["base_total"]["lent"]["principal_minor"] == 100000


def test_empty(ctx):
    s, u, o = ctx
    out = grouped_loans(s, owner_id=u.id, base_currency="INR")
    assert out["groups"] == [] and out["sankey"]["nodes"] == [] and out["sankey"]["links"] == []
```

- [ ] **Step 2: Run → fail (ModuleNotFoundError).**

- [ ] **Step 3: Implement** — `src/khata/services/loan_groups.py`:
```python
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Plan, Contact
from . import loans as _loans, fx as _fx


def _side():
    return {"count": 0, "principal_minor": 0, "interest_monthly_minor": 0,
            "next_due_minor": 0}


def grouped_loans(session: Session, *, owner_id, base_currency: str, as_of=None) -> dict:
    as_of = as_of or date.today()
    plans = list(session.scalars(
        select(Plan).where(Plan.owner_user_id == owner_id, Plan.type == "loan")))
    groups = {}
    partial = False

    def conv(v, ccy):
        nonlocal partial
        if ccy == base_currency:
            return v
        rate = _fx.get_rate(session, base=ccy, quote=base_currency)
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
        next_due = interest_monthly  # interest-only loans; kept distinct for amortizing future

        if loan.contact_id is not None:
            ct = session.get(Contact, loan.contact_id)
            name = (ct.name if ct else (loan.counterparty or "")).strip() or "Unlabeled"
            cid = loan.contact_id
        else:
            name = (loan.counterparty or "").strip() or "Unlabeled"
            cid = None
        norm = name.lower() or "unlabeled"

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
        g["loans"].append({
            "plan_id": p.id, "name": p.name, "direction": loan.direction,
            "currency": ccy, "outstanding_minor": out,
            "interest_monthly_minor": interest_monthly,
            "outstanding_base_minor": ob})

    # finalize groups: contact_id only if the whole group shares ONE linked contact
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
        for k in ("count", "principal_minor", "interest_monthly_minor", "next_due_minor"):
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
        for li, ln in enumerate(g["loans"]):
            lnode = f"ln:{ln['plan_id']}"
            nodes.append({"id": lnode, "label": ln["name"], "kind": "loan",
                          "plan_id": ln["plan_id"]})
            if ln["outstanding_base_minor"] > 0:
                links.append({"source": cnode, "target": lnode,
                              "value_minor": ln["outstanding_base_minor"]})
    return {"nodes": nodes, "links": links}
```

- [ ] **Step 4: Run → pass (8 tests) + full suite `-q` green.**
  NOTE on the sankey invariant: per contact, Σ(Direction→Contact) uses each side's
  `principal_minor`, and Σ(Contact→Loan) sums each loan's `outstanding_base_minor` — these are
  equal because the side principal is the sum of that side's loans' base outstanding. If the
  test fails, it means a loan's base value diverged from its side total (e.g. a partial/missing
  rate zeroed one but not the other) — keep them computed via the SAME `conv()` so they match.

- [ ] **Step 5: Commit**
```bash
git add src/khata/services/loan_groups.py tests/test_loan_groups.py
git commit -m "feat(loans): loan_groups service — contact grouping + sankey aggregation"
```

---

### Task 2: `GET /api/plans/loans/grouped` endpoint

**Files:** modify `src/khata/api/plans.py`; test `tests/test_loan_groups_api.py`.

- [ ] **Step 1: Failing tests** — `tests/test_loan_groups_api.py` (copy the `client` fixture + auth/seed idiom from `tests/test_secured_loans_api.py`; create loans + a contact via the API). Contract:
```python
def test_grouped_endpoint_shape(client):
    # create 2 loans to the same counterparty + 1 to another
    _make_loan(client, name="L1", counterparty="Sunil")
    _make_loan(client, name="L2", counterparty="Sunil")
    _make_loan(client, name="L3", counterparty="Bank", direction="taken")
    r = client.get("/api/plans/loans/grouped")
    assert r.status_code == 200
    body = r.get_json()
    assert "groups" in body and "base_total" in body and "sankey" in body
    names = {g["name"] for g in body["groups"]}
    assert "Sunil" in names and "Bank" in names
    sunil = [g for g in body["groups"] if g["name"] == "Sunil"][0]
    assert sunil["given"]["count"] == 2


def test_grouped_owner_only(client):
    _make_loan(client, name="L", counterparty="K")
    _login_as_other_user(client)
    body = client.get("/api/plans/loans/grouped").get_json()
    assert body["groups"] == []   # other user sees none of the first user's loans


def test_grouped_unauth_401(client):
    client.delete_cookie("session")
    assert client.get("/api/plans/loans/grouped").status_code == 401


def test_grouped_empty(client):
    body = client.get("/api/plans/loans/grouped").get_json()
    assert body["groups"] == [] and body["sankey"]["nodes"] == []
```
(`_make_loan` — POST `/api/plans` with `type=loan, interest_type=monthly, rate="3", start_date="2023-12-12", counterparty=<name>, direction=<given|taken>` then a disbursement. Adapt to the real create payload as in `test_share_owner_api.py`/`test_contacts_api.py`.)

- [ ] **Step 2: Run → fail (404).**

- [ ] **Step 3: Implement** — in `src/khata/api/plans.py` add `loan_groups` to the `from ..services import ...` line, and add the route (place it before any `/<int:plan_id>` GET if ordering matters — it won't, "loans" isn't an int):
```python
@bp.get("/loans/grouped")
def loans_grouped():
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    base = getattr(user, "base_currency", None) or "INR"
    return jsonify(loan_groups.grouped_loans(g.db, owner_id=user.id, base_currency=base)), 200
```

- [ ] **Step 4: Run → pass (4) + full suite `-q` green.**

- [ ] **Step 5: Commit**
```bash
git add src/khata/api/plans.py tests/test_loan_groups_api.py
git commit -m "feat(loans): GET /api/plans/loans/grouped (owner-only)"
```

---

### Task 3: Frontend — By-direction ↔ By-contact toggle + group render

**Files:** modify `src/khata/static/app.html` (the loan-list section, ~lines 697–835).

- [ ] **Step 1: Read the loan view** — find where `type==='loan'` renders the Borrowed/Lent groups (`groupHeader`, the `groups=[{arr:taken,...},{arr:given,...}]` block, `pmeta`), the `BASE` currency var, the `fmt`/`fmtB`/`toBase` money helpers, `el()`, and the loans card header (where "Loans · 11 plans" + the borrowed/lent meta render).

- [ ] **Step 2: Add the toggle** — in the loans card header area, render a segmented control (two buttons: `By direction` / `By contact`). Persist the choice in `localStorage['loanGroupMode']` (default `'direction'`). Switching re-renders the list. Style it with the page's existing pill/segment CSS (reuse `#curtog`-style buttons if present; otherwise minimal inline). Only show the toggle on the loan view (`type==='loan'`).

- [ ] **Step 3: By-contact render** — when mode is `contact`, instead of the direction grouping, fetch `/api/plans/loans/grouped` and render:
```js
async function renderLoansByContact(card){
  let data;
  try { data = await fetch('/api/plans/loans/grouped').then(r=>r.json()); }
  catch(e){ return; }
  // (Sankey panel is added in Task 4 — leave a placeholder container with id="loan-sankey")
  const list = el('div','grouped');
  if (!data.groups.length){ list.append(el('div','emptypanel','No loans yet.')); }
  for (const g of data.groups){
    const head = el('div','gcontact');
    const title = g.contact_id
      ? Object.assign(el('a','gname', g.name), {href:'/contacts/'+g.contact_id})
      : el('span','gname', g.name);
    head.append(title);
    // three figures: principal · interest/mo · next-month due (base currency)
    const tot = (g.given.principal_minor||0) + (g.taken.principal_minor||0);
    const im  = (g.given.interest_monthly_minor||0) - (g.taken.interest_monthly_minor||0);
    const nd  = (g.given.next_due_minor||0) - (g.taken.next_due_minor||0);
    head.append(el('span','gfig', 'principal '+fmtMoney(tot, data.base_currency)));
    head.append(el('span','gfig', 'interest/mo '+fmtSign(im, data.base_currency)));
    head.append(el('span','gfig', 'next due '+fmtSign(nd, data.base_currency)));
    list.append(head);
    for (const side of ['given','taken']){
      if (!g[side].count) continue;
      list.append(el('div','gside', side==='given'?'Lent out':'Borrowed'));
      for (const ln of g.loans.filter(l=>l.direction===side)){
        const row = el('div','grow');
        const a = Object.assign(el('a','grow-n', ln.name), {href:'/loan/'+ln.plan_id});
        row.append(a, el('span','grow-amt', fmtMoney(ln.outstanding_minor, ln.currency)));
        list.append(row);
      }
    }
  }
  card.append(el('div',null,'',{id:'loan-sankey'}));  // Task 4 fills this
  card.append(list);
  if (data.partial){ card.append(el('div','partial-note','≈ some totals exclude a currency (missing FX rate)')); }
}
```
Implement `fmtMoney(minor, ccy)` / `fmtSign(minor, ccy)` using the page's EXISTING formatters (`fmt`/`indGroup`/`sym`) — do NOT invent new ones; map to whatever the file already exposes (e.g. `fmt(minor, ccy)` returns the grouped string and `sym(ccy)` the symbol). Wire `renderLoansByContact` into the loan render path when `loanGroupMode==='contact'`; otherwise the existing direction render runs unchanged.

- [ ] **Step 4: Minimal CSS** — add `.grouped`, `.gcontact`, `.gname`, `.gfig`, `.gside`, `.grow`, `.grow-n`, `.grow-amt`, `.partial-note` to `app.html`'s `<style>` (scope under the page's existing class; do NOT edit app.css/ledger.css). Lent green / borrowed red signing consistent with the page.

- [ ] **Step 5: Syntax + suite** — extract the inline `<script>`, `node --check` it (clean). Run `PYTHONPATH=src /Users/assistant/dev/active/khata/.venv/bin/pytest -q` (green — guards the repo).

- [ ] **Step 6: Commit**
```bash
git add src/khata/static/app.html
git commit -m "feat(loans): By-contact grouping toggle + per-contact summary on Loans page"
```

(Controller runs the live headless verify after Task 4, when the Sankey is present.)

---

### Task 4: Sankey SVG render

**Files:** modify `src/khata/static/app.html`.

- [ ] **Step 1: Implement `renderSankey(container, sankey, baseCcy)`** — a self-contained SVG builder. Layout:
  - Assign nodes to columns by `kind`: direction (col 0), contact (col 1), loan (col 2).
  - Node height ∝ its throughput (a direction node = sum of its outgoing link values; a contact = its total; a loan = its incoming value). Stack nodes per column with small gaps; scale so the tallest column fits a fixed SVG height (e.g. 360px).
  - Links: cubic/quadratic-bezier ribbons between source/target node bands, stroke-width ∝ `value_minor` on a shared px-per-minor scale; lent links green family, borrowed red family, ~0.45 opacity.
  - Labels: node label text (escaped) beside each node; truncate long names.
  - Hover a link or node → a tooltip div with the formatted ₹ value (use the page's money formatter). Click a contact node → `document.getElementById('grp-'+contactKey)?.scrollIntoView()` (give each group header an id in Task 3 render, e.g. `grp-<key>`).
  - Empty sankey (no nodes) → render nothing (and the Task 3 container stays empty).
- Wire it: in `renderLoansByContact`, after building the list, call
  `renderSankey(document.getElementById('loan-sankey'), data.sankey, data.base_currency)`.

- [ ] **Step 2: Fallback** — if `window.matchMedia('(max-width:560px)').matches` or
  `prefers-reduced-motion: reduce`, render a compact stacked-bar list instead (one row per
  contact: a horizontal bar split lent/borrowed by base outstanding) — same data, simpler SVG.
  Keep both code paths in `renderSankey`.

- [ ] **Step 3: Syntax + suite** — `node --check` the inline script (clean); `pytest -q` green.

- [ ] **Step 4: Commit**
```bash
git add src/khata/static/app.html
git commit -m "feat(loans): hand-rolled Sankey of the loan book (Direction->Contact->Loan)"
```

- [ ] **Step 5: Headless verify (controller runs).** Per `/build-screen` Phase-4: start the app from this worktree on a temp DB + safe port, seed a user + several loans (2 lent to "Sunil" via counterparty, 1 borrowed "Bank", 1 USD + an FX rate, one assigned to a real contact), log in, then headless-render `/app?type=loan`: toggle to By-contact → assert 0 page-origin JS throws; contact groups render with the three figures; the Sankey `<svg>` has nodes (paths/rects) and link ribbons; By-direction mode still renders the original Borrowed/Lent groups unchanged. Report concrete DOM findings.

---

### Task 5: AS-BUILT doc

**Files:** modify `docs/specs/khata-AS-BUILT.md`.

- [ ] **Step 1: Update** — add a §9 paragraph + a change-log entry at the top, and note the new read-only endpoint in the API section:
```
- 2026-06-19 — Loans grouped by contact + Sankey. The Loans page gains a By-direction ↔
  By-contact toggle: By-contact groups loans per person (contact name, else counterparty text;
  same names merge), given/taken within, each with principal · expected interest/mo · next-month
  due (base currency). A hand-rolled SVG Sankey (Direction → Contact → Loan, weighted by
  outstanding) sits above the list, with a stacked-bar fallback on small screens. New read-only
  `GET /api/plans/loans/grouped` (owner-only) computes the aggregation + sankey nodes/links
  (reuses loan_state + fx). No migration.
```
Add the endpoint to the API surface list (Loans section): `GET /api/plans/loans/grouped → grouped-by-contact rollup + sankey`.

- [ ] **Step 2: Full suite green + commit**
```bash
PYTHONPATH=src /Users/assistant/dev/active/khata/.venv/bin/pytest -q
git add docs/specs/khata-AS-BUILT.md
git commit -m "docs(loans): record grouped-by-contact + sankey in AS-BUILT"
```

---

## Self-Review

**Spec coverage:** toggle (T3) ✅; contact-first grouping + key/merge (T1 service, rendered T3) ✅; per-group principal/interest/next-due (T1 + T3) ✅; Sankey Direction→Contact→Loan weighted by outstanding (T1 structure + T4 render) ✅; base-currency + partial (T1) ✅; testable endpoint (T2) ✅; small-screen/reduced-motion fallback (T4) ✅; headless verify (T4 step 5) ✅; docs (T5) ✅.

**Placeholder scan:** Frontend tasks (T3/T4) reference the page's existing money helpers (`fmt`/`sym`/`indGroup`) and existing render structure rather than restating them — flagged for the implementer to map to the real names (guessing would be wrong); the JS shown is concrete. API test helpers (`_make_loan`/`_login_as_other_user`) copy the project's real fixture idiom (flagged). All service code (the testable core) is complete.

**Type consistency:** `grouped_loans(...)` returns `{base_currency, as_of, groups:[{key,name,contact_id,given:_side,taken:_side,loans:[{plan_id,name,direction,currency,outstanding_minor,interest_monthly_minor,outstanding_base_minor}],total_base_minor}], base_total:{lent:_side,borrowed:_side}, partial, sankey:{nodes:[{id,label,kind,...}],links:[{source,target,value_minor}]}}` where `_side = {count,principal_minor,interest_monthly_minor,next_due_minor}`. This exact shape is consumed by the API (T2 passthrough), the group render (T3), and the sankey render (T4). Node ids `dir:lent`/`dir:borrowed`/`ct:<i>`/`ln:<plan_id>` and link `value_minor` are used consistently in the invariant test (T1) and the renderer (T4).
