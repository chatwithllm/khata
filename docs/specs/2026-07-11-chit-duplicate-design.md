# Chit duplicate — design

**Date:** 2026-07-11
**Scope:** Add a "Duplicate" action to a chit fund that clones its terms into a
new, empty chit under a user-chosen name.

## Problem

Creating a second chit with the same terms as an existing one (chit value,
member count, commission, currency, start date) means re-entering every field
in the create-plan flow. Users running near-identical chits (e.g. `1 Lakh -1`,
`1 Lakh -2`) want a one-action copy that they only have to rename.

## Goal

From a chit's detail page, duplicate it into a new chit that:

- copies the **terms only**: `chit_value_minor`, `n_members`, `commission_bps`,
  `currency`, `start_date`;
- has an **empty ledger** (no contributions, dividends, or prizes);
- is **private to the owner** (no shared-with roster copied);
- takes a **new name**, defaulted to an incremented trailing number and editable
  before creation.

## Non-goals (YAGNI)

- Copying members / shared-with roster or share links.
- Copying ledger entries or recorded auction rounds.
- Enforcing name uniqueness (plan names are not unique today).
- Duplicating non-chit plan types.

## Backend

### Service — `src/khata/services/chits.py`

New thin wrapper:

```python
def duplicate_chit_plan(session, *, source_plan, owner_id, name) -> Plan:
    """Clone a chit's terms into a new empty chit. Ledger and shares not copied."""
    chit = source_plan.chit
    return create_chit_plan(
        session, owner_id=owner_id, name=name, currency=source_plan.currency,
        chit_value_minor=chit.chit_value_minor, n_members=chit.n_members,
        commission_bps=chit.commission_bps, start_date=chit.start_date)
```

Reuses `create_chit_plan`, which already validates currency, member count,
value, and commission. No new validation paths.

### Endpoint — `src/khata/api/plans.py`

```
POST /api/plans/<int:plan_id>/chit/duplicate
```

- Auth required; `_owned_plan(user, plan_id)` (owner-only — duplicating clones
  the owner's terms, so contributors should not trigger it).
- Reject if `plan.type != "chit"` → 400 `not_a_chit`.
- Body: `{ "name": "<string>" }`. Trim it; if blank, fall back to
  `f"{source.name} -copy"` (server never creates an unnamed plan — client
  always sends a suggested name, so this is just a guard).
- Call `chits.duplicate_chit_plan(...)`, `commit()`.
- On `ChitError` / `ValueError` / `TypeError`: rollback → 400 `invalid`.
- Return `_detail(new_plan)`, 201 (same shape as create, so client reads
  `id` for redirect).

## Frontend — `src/khata/static/chit-detail.html`

### Header action

Add a `Duplicate` button between Print and Delete in the header action row,
using the existing `actBtn(cls, label, dPath, fn)` helper and a copy/stack icon
path. Matches Share/Print/Delete styling and keyboard handling (Enter/Space).

```js
acts.append(actBtn('planduplicate','Duplicate',
  'M8 8h11a1 1 0 011 1v11a1 1 0 01-1 1H8a1 1 0 01-1-1V9a1 1 0 011-1zM4 16V4a1 1 0 011-1h11',
  duplicatePlan));
```

### Behavior

```js
function nextChitName(name){
  const m = String(name||'').match(/^(.*?)(\d+)(\D*)$/);   // last digit run
  return m ? m[1] + (parseInt(m[2],10)+1) + m[3] : (name + ' 2');
}
async function duplicatePlan(){
  const suggested = nextChitName(plan.name);
  const name = prompt('Name for the duplicated chit', suggested);
  if(name === null) return;                 // cancelled
  const trimmed = name.trim();
  if(!trimmed) return;                       // blank aborts
  const r = await fetch('/api/plans/'+pid+'/chit/duplicate', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ name: trimmed }) });
  if(!r.ok){ /* surface error via existing toast/alert path */ return; }
  const d = await r.json();
  location.href = '/chit/' + d.id;           // land on the new chit
}
```

`nextChitName("1 Lakh -1")` → `"1 Lakh -2"` (non-greedy prefix, last digit run
increments). Names without a number get ` 2` appended; the user edits the
prompt anyway.

Uses `prompt()` to stay consistent with the page's existing `confirm()`-based
delete flow — no new modal component.

## Data flow

```
[Duplicate btn] → prompt(name) → POST /api/plans/:id/chit/duplicate {name}
   → _owned_plan + type check
   → chits.duplicate_chit_plan → create_chit_plan (terms only) → commit
   → 201 _detail(new_plan)
   → client redirect /chit/:newId  (fresh chit, empty schedule)
```

## Error handling

| Case | Result |
| --- | --- |
| Not authenticated | 401 `unauthenticated` |
| Not owner / not found | error from `_owned_plan` |
| Plan is not a chit | 400 `not_a_chit` |
| Invalid terms (should not occur — cloned from a valid chit) | 400 `invalid` |
| Blank name from client | server falls back to `"<name> -copy"` |
| Client `prompt` cancelled/blank | no request sent |

## Testing

- **Service test** (`tests/`): `duplicate_chit_plan` produces a new plan with a
  distinct id, identical terms, empty `ledger_entries`, and no shares.
- **Endpoint test**: owner gets 201 with new id; non-chit plan → 400; the new
  chit's `chit_state` shows `months_recorded == 0` and full unpaid schedule.
- **Headless UI verify** via `/build-screen` protocol: Duplicate button present,
  prompt suggests `-2`, redirect lands on an empty copy.

## Docs

Update `docs/specs/khata-AS-BUILT.md` in the same commit (project rule: every
change updates the as-built doc alongside the code).
