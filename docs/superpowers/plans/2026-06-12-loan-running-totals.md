# Loan Running-Total Pending Interest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a cumulative unpaid (net-of-payments) running total of pending interest, plus a principal+pending "total owed", on the loan-detail repayment schedule (per month) and the dashboard loans list (per loan + section running totals).

**Architecture:** One backend change — `loan_state` adds three integer-minor fields per schedule row (`cum_due_minor`, `principal_minor`, `total_owed_minor`). Two frontend changes consume existing JSON: loan-detail adds a second muted line per month row; the dashboard reads already-fetched `st.interest_due_minor` / `st.total_minor` per loan and accumulates them (in base currency) into the BORROWED / LENT OUT section footers. No new model, migration, or endpoint.

**Tech Stack:** Flask + SQLAlchemy 2.0, integer minor units (×100), Decimal ROUND_HALF_UP (never float). Vanilla-JS static HTML with `el()`/`amtSpan()`/`fmtB()`/`fmt()`/`toBase()` helpers. K4 rule: never `innerHTML` on user/API data — `textContent`/`createTextNode` only. pytest via `/Users/assistant/dev/active/khata/.venv/bin/python -m pytest -q`. Test instance: `bash /Users/assistant/dev/active/khata/run-app.sh` → port 5057, real data in `khata_app.db` (never wipe), health at `/api/health`.

---

## File Structure

- `src/khata/services/loans.py` — `loan_state()` schedule loop. Add the three running-total
  fields. Sole backend change. (~lines 389–420.)
- `tests/test_loan_service.py` — add running-total tests next to the existing schedule tests
  (`test_interest_payments_greedy_schedule` is the closest analog).
- `src/khata/static/loan-detail.html` — `renderSchedule()` (~lines 587–620). Second line per row.
- `src/khata/static/app.html` — dashboard loans list: per-loan caption (~lines 802–822) and
  `groupHeader()` footers (~lines 743–756, agg init ~770).
- `docs/specs/khata-AS-BUILT.md` — §9 schedule fields + a 2026-06-12 change-log entry.

---

### Task 1: Backend — schedule running-total fields

**Files:**
- Modify: `src/khata/services/loans.py:389-420`
- Test: `tests/test_loan_service.py`

The schedule is built in two existing loops. The **build loop** (~389) computes `opening`
(principal outstanding at the month's start) and `expected` (interest accrued that month),
then appends a row dict. The **status loop** (~403) walks rows in order, applies the paid
pool greedily (`applied_minor`), and sets `status`. We pigg-back on both: store `opening`
as `principal_minor` in the build loop, and accumulate `cum_due_minor` + `total_owed_minor`
in the status loop (where `applied` is known).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_loan_service.py` (uses the file's existing `ctx` fixture, `_loan`,
`_dt`, `add_disbursement`, `log_loan_entry`, `loan_state`, `date`):

```python
def test_schedule_running_totals_no_payments(ctx):
    s, u = ctx
    plan = _loan(s, u, rate_bps=200, start_date=date(2026, 1, 1))  # 2%/mo
    add_disbursement(s, plan=plan, user_id=u.id, amount_minor=10000000, occurred_at=_dt(2026, 1, 1))
    st = loan_state(s, plan.loan, as_of=date(2026, 4, 1))  # 3 complete months, 2,000/mo accrued
    sch = st["schedule"]
    # cumulative unpaid interest grows 2,000 → 4,000 → 6,000 (minor units ×100)
    assert [r["cum_due_minor"] for r in sch] == [200000, 400000, 600000]
    for r in sch:
        assert r["principal_minor"] == 10000000          # principal flat (no repayment)
        assert r["total_owed_minor"] == r["principal_minor"] + r["cum_due_minor"]


def test_schedule_running_due_reflects_payments(ctx):
    s, u = ctx
    plan = _loan(s, u, rate_bps=200, start_date=date(2026, 1, 1))  # 2%/mo
    add_disbursement(s, plan=plan, user_id=u.id, amount_minor=10000000, occurred_at=_dt(2026, 1, 1))
    log_loan_entry(s, plan=plan, user_id=u.id, kind="interest_payment",
                   amount_minor=300000, occurred_at=_dt(2026, 2, 1))  # pay 3,000
    st = loan_state(s, plan.loan, as_of=date(2026, 4, 1))  # 6,000 accrued − 3,000 paid
    sch = st["schedule"]
    # month 0 fully paid through (cum 0); month 1 half-paid (cum 1,000); month 2 unpaid (cum 3,000)
    assert [r["cum_due_minor"] for r in sch] == [0, 100000, 300000]
    assert sch[0]["cum_due_minor"] == 0
    # strictly lower than the no-payment tail (600000) — a payment reduces pending
    assert sch[-1]["cum_due_minor"] < 600000
    assert sch[-1]["total_owed_minor"] == sch[-1]["principal_minor"] + sch[-1]["cum_due_minor"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/Users/assistant/dev/active/khata/.venv/bin/python -m pytest tests/test_loan_service.py::test_schedule_running_totals_no_payments tests/test_loan_service.py::test_schedule_running_due_reflects_payments -q`
Expected: FAIL with `KeyError: 'cum_due_minor'`.

- [ ] **Step 3: Add `principal_minor` to the build-loop row**

In `src/khata/services/loans.py`, the build loop currently ends:

```python
            interest_accrued += expected
            schedule.append({"month_index": m, "period_start": pm.isoformat(),
                             "expected_minor": expected})
```

Change the appended dict to carry the month's opening principal:

```python
            interest_accrued += expected
            schedule.append({"month_index": m, "period_start": pm.isoformat(),
                             "expected_minor": expected, "principal_minor": opening})
```

- [ ] **Step 4: Accumulate `cum_due_minor` + `total_owed_minor` in the status loop**

The status loop currently reads:

```python
    pool = interest_paid
    next_due_month = None
    months_behind = 0
    for row in schedule:
        expected = row["expected_minor"]
        applied = min(pool, expected)
        pool -= applied
        row["applied_minor"] = applied
        if expected == 0 or applied == expected:
            row["status"] = "paid"
        elif applied > 0:
            row["status"] = "partial"
        else:
            row["status"] = "due"
        if row["status"] != "paid":
            months_behind += 1
            if next_due_month is None:
                next_due_month = row["month_index"]
```

Replace it with (adds `cum_due` accumulator + the two derived fields; integer minor units —
exact, no float, no rounding drift):

```python
    pool = interest_paid
    next_due_month = None
    months_behind = 0
    cum_due = 0
    for row in schedule:
        expected = row["expected_minor"]
        applied = min(pool, expected)
        pool -= applied
        row["applied_minor"] = applied
        # Running cumulative UNPAID interest through this month (net of payments applied),
        # and principal+pending "total owed". All integer minor units — exact.
        cum_due += expected - applied
        row["cum_due_minor"] = cum_due
        row["total_owed_minor"] = row["principal_minor"] + cum_due
        if expected == 0 or applied == expected:
            row["status"] = "paid"
        elif applied > 0:
            row["status"] = "partial"
        else:
            row["status"] = "due"
        if row["status"] != "paid":
            months_behind += 1
            if next_due_month is None:
                next_due_month = row["month_index"]
```

- [ ] **Step 5: Run the new tests + the full suite**

Run: `/Users/assistant/dev/active/khata/.venv/bin/python -m pytest -q`
Expected: PASS — 337 passed (335 prior + 2 new). No regressions in the existing schedule
tests (`test_interest_payments_greedy_schedule`, etc.).

- [ ] **Step 6: Commit**

```bash
git add src/khata/services/loans.py tests/test_loan_service.py
git commit -m "feat(loans): schedule rows carry cumulative pending interest + total owed

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Loan-detail repayment schedule — second line

**Files:**
- Modify: `src/khata/static/loan-detail.html:603-618` (`renderSchedule`)

Each month row's right column (`sv`) holds `pa` (applied amount) and `pl` (`expected ₹X`).
Add a third muted line: `running due ₹X · owed ₹Y` from the new row fields. K4: spans via
`amtSpan()` and `createTextNode` — no innerHTML.

- [ ] **Step 1: Add the running-total line**

The loop body currently reads:

```javascript
    const sv=el('div','sv');
    const pa=el('div','pa'); pa.append(amtSpan(it.applied_minor)); if(status==='due') pa.style.color='var(--ink-faint)';
    const pl=el('div','pl'); pl.append(document.createTextNode('expected '), amtSpan(it.expected_minor));
    sv.append(pa,pl);
    srow.append(dot,si,sv);
```

Replace with (adds `rt`, the running-due/owed line; guarded so legacy payloads without the
field don't render a broken line):

```javascript
    const sv=el('div','sv');
    const pa=el('div','pa'); pa.append(amtSpan(it.applied_minor)); if(status==='due') pa.style.color='var(--ink-faint)';
    const pl=el('div','pl'); pl.append(document.createTextNode('expected '), amtSpan(it.expected_minor));
    sv.append(pa,pl);
    if(it.cum_due_minor!==undefined){
      const rt=el('div','pl'); rt.style.cssText='font-size:11px;color:var(--ink-faint);margin-top:2px';
      rt.append(document.createTextNode('running due '), amtSpan(it.cum_due_minor),
                document.createTextNode(' · owed '), amtSpan(it.total_owed_minor));
      sv.append(rt);
    }
    srow.append(dot,si,sv);
```

- [ ] **Step 2: Restart the test instance and verify headless**

```bash
bash /Users/assistant/dev/active/khata/run-app.sh   # serves :5057 from this worktree
curl -s localhost:5057/api/health                    # {"status":"ok"}
curl -s localhost:5057/loan-detail | grep -c "running due"
```

Expected: health ok; `grep -c "running due"` ≥ 1 (the literal is in the served JS). Then load
a real loan page in a headless DOM (or browser) and confirm: schedule month rows show a second
muted line `running due … · owed …`, the values increase down the list, and the JS console
throws zero errors. The number is `cum_due_minor`/`total_owed_minor` from `/api/plans/<id>`.

- [ ] **Step 3: Commit**

```bash
git add src/khata/static/loan-detail.html
git commit -m "feat(web): loan-detail schedule shows running due + total owed per month

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Dashboard loans list — per-loan caption + section footers

**Files:**
- Modify: `src/khata/static/app.html:743-756` (`groupHeader`), `app.html:770` (agg init),
  `app.html:802-822` (loan fill branch)

No backend change — the loan fill loop already fetches `st` per loan, which carries
`interest_due_minor` (total accrued-unpaid interest) and `total_minor` (principal outstanding
+ interest due = total owed). Add a per-loan caption and accumulate both into the section
footer **in base currency** (the existing `toBase(...)` pattern — never raw-sum across
currencies).

- [ ] **Step 1: Give `groupHeader` a footer sub-line element**

`groupHeader` currently ends:

```javascript
      tw.append(intTot, outTot);
      h.append(lft, tw); plist.append(h);
      return {outEl:outTot, intEl:intTot};
    }
```

Replace with (adds a right-aligned running pending/owed line under the section header):

```javascript
      tw.append(intTot, outTot);
      h.append(lft, tw); plist.append(h);
      const subrow=el('div'); subrow.style.cssText='display:flex;justify-content:flex-end;padding:0 22px 8px;font-family:"JetBrains Mono";font-size:11px;color:var(--ink-faint)';
      plist.append(subrow);
      return {outEl:outTot, intEl:intTot, subEl:subrow};
    }
```

- [ ] **Step 2: Carry the new accumulators on the group aggregate**

The agg is created (~line 770) as:

```javascript
        const agg={sum:0, interest:0, outEl:els.outEl, intEl:els.intEl, ccy:'INR', taken:g.taken};
```

Replace with:

```javascript
        const agg={sum:0, interest:0, pend:0, owed:0, outEl:els.outEl, intEl:els.intEl, subEl:els.subEl, ccy:'INR', taken:g.taken};
```

- [ ] **Step 3: Add the per-loan caption and footer accumulation**

The loan fill branch currently reads (from `outCol.insertBefore(cap, ar);` through the
`groupAgg` block):

```javascript
        } else { cap.textContent='outstanding'; }
        outCol.insertBefore(cap, ar);
        const mi=monthlyInterestMinor(out, p.rate_bps, p.interest_type);
        const taken=(p.direction!=='given');
        if(!mi){ intAmt.textContent='—'; intAmt.style.color='var(--ink-faint)'; }
        else { intAmt.textContent=(taken?'−':'+')+fmtB(mi, ccy); intAmt.style.color=taken?'var(--neg)':'var(--pos)'; }
        if(groupAgg){
          // accumulate in BASE so a cross-currency subtotal is valid (not a raw sum)
          groupAgg.sum+=toBase(out,ccy)[0]; groupAgg.interest+=toBase(mi,ccy)[0]; groupAgg.ccy=BASE;
          groupAgg.outEl.textContent=fmt(groupAgg.sum, BASE);
          groupAgg.intEl.textContent=(groupAgg.taken?'−':'+')+fmt(groupAgg.interest, BASE)+'/mo';
        }
```

Replace with (adds the `pending int … · owed …` caption per loan, and the running totals
in the section footer):

```javascript
        } else { cap.textContent='outstanding'; }
        outCol.insertBefore(cap, ar);
        const idue=st.interest_due_minor||0, owed=st.total_minor||0;
        if(idue>0){
          const pc=el('div'); pc.style.cssText='font-size:11px;color:var(--ink-faint);font-family:"JetBrains Mono"';
          pc.textContent='pending int '+fmtB(idue,ccy)+' · owed '+fmtB(owed,ccy);
          outCol.insertBefore(pc, ar);
        }
        const mi=monthlyInterestMinor(out, p.rate_bps, p.interest_type);
        const taken=(p.direction!=='given');
        if(!mi){ intAmt.textContent='—'; intAmt.style.color='var(--ink-faint)'; }
        else { intAmt.textContent=(taken?'−':'+')+fmtB(mi, ccy); intAmt.style.color=taken?'var(--neg)':'var(--pos)'; }
        if(groupAgg){
          // accumulate in BASE so a cross-currency subtotal is valid (not a raw sum)
          groupAgg.sum+=toBase(out,ccy)[0]; groupAgg.interest+=toBase(mi,ccy)[0]; groupAgg.ccy=BASE;
          groupAgg.pend+=toBase(idue,ccy)[0]; groupAgg.owed+=toBase(owed,ccy)[0];
          groupAgg.outEl.textContent=fmt(groupAgg.sum, BASE);
          groupAgg.intEl.textContent=(groupAgg.taken?'−':'+')+fmt(groupAgg.interest, BASE)+'/mo';
          groupAgg.subEl.textContent='pending int '+fmt(groupAgg.pend, BASE)+' · owed '+fmt(groupAgg.owed, BASE);
        }
```

- [ ] **Step 4: Restart and verify headless**

```bash
bash /Users/assistant/dev/active/khata/run-app.sh
curl -s localhost:5057/api/health                 # {"status":"ok"}
curl -s localhost:5057/app | grep -c "pending int"
```

Expected: health ok; `grep -c "pending int"` ≥ 1. Then load `/app?type=loan` (the Loans list)
in a headless DOM / browser and confirm: each loan row shows a `pending int … · owed …`
caption; the BORROWED and LENT OUT section headers show a running `pending int … · owed …`
line; values are sane (per-loan owed = principal + pending; footer = Σ in ₹ base); JS console
throws zero errors.

- [ ] **Step 5: Commit**

```bash
git add src/khata/static/app.html
git commit -m "feat(web): dashboard loans show pending interest + total owed, per loan and per section

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Docs — AS-BUILT

**Files:**
- Modify: `docs/specs/khata-AS-BUILT.md`

- [ ] **Step 1: Update the loan-state schedule field list (§9)**

Find the loan-state / schedule description in §9 (search the doc for `schedule` and
`expected_minor`). Append to the per-row field description: each schedule row now also carries
`cum_due_minor` (running cumulative unpaid interest, net of payments), `principal_minor` (the
month's opening principal outstanding), and `total_owed_minor` (`principal_minor +
cum_due_minor`). If §9 doesn't enumerate the row fields, add one sentence where the schedule
is described.

- [ ] **Step 2: Add a change-log entry**

Add at the top of the change-log list (do NOT edit existing dated entries):

```markdown
- 2026-06-12 — Loan running totals. `loan_state` schedule rows now carry `cum_due_minor`
  (cumulative unpaid interest through that month, net of payments), `principal_minor` (the
  month's opening principal), and `total_owed_minor` (principal + cumulative pending). The
  loan-detail repayment schedule shows a `running due … · owed …` line per month; the
  dashboard loans list shows `pending int … · owed …` per loan (from `interest_due_minor` /
  `total_minor`) and running section totals in the BORROWED / LENT OUT footers (summed in base
  currency). No new model, migration, or endpoint.
```

- [ ] **Step 3: Commit**

```bash
git add docs/specs/khata-AS-BUILT.md
git commit -m "docs(as-built): loan schedule running-total fields + change-log entry

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Notes for the executor

- **Never wipe `khata_app.db`** — it holds the user's real data; the test instance reads it.
- **Stage files explicitly** — never `git add -A`. The repo has many intentionally-untracked
  files (`.env*`, `khata_*.db*`, `.claude/`, `CLAUDE.md`, `run-app.sh`, `OD_khata_mockup/`).
- **K4** — all new DOM text via `textContent` / `createTextNode` / `amtSpan`. No `innerHTML`.
- **Minor units** — every amount is an integer ×100; cross-currency sums go through `toBase`.
- The `run-app.sh` instance serves THIS worktree (`/private/tmp/khata-landing`); Python edits
  (Task 1) need a restart to take effect, static edits (Tasks 2–3) are live on reload.
