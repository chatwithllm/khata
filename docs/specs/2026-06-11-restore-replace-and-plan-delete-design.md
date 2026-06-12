# Restore = Replace (wipe + load) & Plan Delete Everywhere — Design

**Date:** 2026-06-11
**Status:** Approved

## Problem

1. `POST /api/restore` MERGES: users matched by email, but every plan/entry is inserted
   as a NEW row (no natural key). Restoring onto a non-empty instance duplicates
   everything. Observed on prod: user restored a backup and got duplicate loans and
   assets. Loans could be cleaned up (loan-detail has a Delete button); assets could not.
2. Only `loan-detail.html` has a plan-level Delete button. Asset, chit, holding, and
   retirement detail pages have none — even though the backend
   (`DELETE /api/plans/<id>` → `assets.delete_plan`) is already type-generic and
   owner-only.

## Decision

**Restore semantics: wipe + load.** Delete ALL existing data (every user, plan, entry,
fx rate), then load the backup file exactly, preserving the backup's original row ids.
The pre-restore auto-snapshot (already implemented in `api/backup.py`) is the safety net.

Rejected alternatives:
- *Replace-per-user (merge users by email, wipe only matched users' plans)* — partial
  states, more code, doesn't match the user's mental model ("erase and load").
- *Merge + dedupe by (name, type, owner)* — near-duplicates from edited plans slip through.
- *Raw SQLite file swap (scripts/restore.sh style) via the API* — live gunicorn workers
  hold connections + WAL; not portable.

## Part 1 — `import_replace`

### `src/khata/services/backup.py`

New `import_replace(session, data) -> dict` replaces `import_merge` as the API restore
path. (`import_merge` is deleted — nothing else uses it; its tests are rewritten against
`import_replace`.)

Behavior:
1. Validate: `data` is a dict with `tables`, `version == BACKUP_VERSION`, and
   `tables["users"]` is non-empty (`BackupError` otherwise — an empty backup would brick
   the instance: no one could log in afterwards).
2. Wipe, children before parents (explicit order; do not rely on cascade config):
   `attachments → ledger_entries → installments → plan_memberships →
   asset_purchases/loans/holdings/chits/retirements → plans → fx_rates → users`.
   Bulk `session.execute(delete(Model))` per table, then `flush()`.
3. Insert rows verbatim in `EXPORT_MODELS` order via the existing `_parse` coercion,
   **keeping the backup's `id` values** (tables are empty — no remap needed). Loans'
   `collateral_plan_id` also needs no remap.
4. Return per-table insert counts: `{"users": n, "plans": n, ...}`.

All inside the caller's transaction: any failure → rollback → instance untouched.

Not wiped (operational state, not in backup files): `backup_config`, `fx_refresh_state`.

Preserving ids matters beyond simplicity: cookie sessions and bearer tokens carry
`user_id`. With verbatim ids, a stale session from before the restore maps to the same
person when the backup came from the same instance (the normal case). The merge path's
id reshuffle could map a stale cookie onto a *different* user.

Module docstring updated to describe replace semantics.

### `src/khata/api/backup.py` — `POST /api/restore`

- Call `import_replace` instead of `import_merge`.
- Pre-restore snapshot logic unchanged.
- After commit, re-resolve the operator **by email** in the restored data:
  - found → `session["user_id"] = new_user.id` (keeps them logged in),
  - missing → `session.clear()`, respond `logged_out: true` (their account no longer
    exists; client redirects to login).
- Response: `{"ok": true, "stats": {...}, "pre_restore_saved": bool, "logged_out": bool}`.

### `src/khata/static/settings.html`

- Hint text: restore **replaces** everything with the backup's contents (all current
  users, plans, and entries are deleted first); pre-restore snapshot auto-saved on the
  server.
- Confirm dialog: `Restore from "<name>"? This REPLACES all current data with the
  backup's contents. A pre-restore snapshot is saved on the server first.`
- Success handler: if `logged_out` → `window.location.href='/'`; else show replaced
  counts and reload.

## Part 2 — Delete button on all plan detail pages

Replicate the `loan-detail.html` pattern (ghost `plandel` button in the header
`planacts` row + `confirm()` + `DELETE /api/plans/<pid>` + redirect `/app`) on:

- `asset-detail.html`
- `chit-detail.html`
- `holding-detail.html`
- `retirement-detail.html`

Per page: same trash icon path, same actBtn/keyboard affordances, type-specific confirm
copy ("Delete this asset and all its entries? This cannot be undone."), error surfaced
via the page's existing error element + `alert` fallback. K4 holds: textContent only.

Backend: no change. `DELETE /api/plans/<id>` is owner-only (`_owned_plan`);
`assets.delete_plan` removes entries, installments, memberships, the 1:1 sub-row, and
the plan, for any type. Attachments cascade with their entries.

Visibility: match loan-detail's current behavior — button rendered for any viewer; the
API enforces owner-only (a member clicking it gets the error surfaced). No client gate.

## Tests

`tests/test_backup.py` (rewrite merge tests against replace):
- replace onto non-empty instance: old plans gone, backup's plans present with original ids
- restoring the same file twice → identical table counts (the duplicate bug, dead)
- backup with empty `users` → `BackupError`, 400, instance untouched
- operator present in backup by email → session keeps working (`logged_out` false)
- operator absent → `logged_out` true, session cleared
- version mismatch / non-dict still rejected
- fx_rates replaced, `fx_refresh_state` + `backup_config` untouched

UI: headless verification — delete button present and wired on all four pages; restore
confirm copy updated.

## Docs

`docs/specs/khata-AS-BUILT.md`: restore section rewritten (merge → replace), plan-delete
row updated, change-log entry. Same commits as the code.

## Out of scope

- Cleaning the duplicates already on prod (user can now delete them in the UI once this
  ships, or re-restore their backup file — which now replaces).
- Multi-select / bulk delete.
- Soft-delete / undo.
