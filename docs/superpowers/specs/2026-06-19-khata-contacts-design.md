# Contacts + per-contact loan grouping

**Date:** 2026-06-19
**Branch:** `feat/contacts`
**Status:** approved design

## Problem

You lend to the same person multiple times. Each loan is a separate plan with only a
freeform `counterparty` text string (e.g. "Karunakar") — no link between them, no way to
see your total exposure to one person, and nowhere to keep their actual contact details.

## Goal

1. A **Contact** record holding a person's full info (name, phone, email, address, notes,
   photo, and attached documents).
2. **Assign loans to a contact**, and a **per-contact rollup**: grouped principal +
   interest across all their loans — per-currency subtotals **and** a base-currency
   grand total.

## Decisions (locked in brainstorming)

- **Loan↔contact:** a new `contacts` table; `loans.contact_id` (nullable FK). Existing
  loans start **unlinked** — you assign them manually. The freeform `counterparty` text
  is **kept** (fallback label + seed value when creating a contact from a loan).
- **Contact fields:** name (required), phone, email, address, notes, photo, + **document
  attachments**.
- **Rollup currency:** per-currency subtotals **and** a converted base-currency grand
  total (reuse `networth`/`fx`).
- **Name:** the section is called **Contacts**.

## Architecture

### 1. Data model

**`contacts`** (new table, migration):

| column | type | notes |
|---|---|---|
| `id` | PK | |
| `owner_user_id` | FK users.id, indexed | contacts are private to the owner |
| `name` | String(120), not null | |
| `phone` | String(40), nullable | |
| `email` | String(255), nullable | |
| `address` | Text, nullable | multi-line |
| `notes` | Text, nullable | |
| `photo` | Text, nullable | `data:image/...` URL (same approach as user avatar; <200KB) |
| `created_at` / `updated_at` | DateTime(tz) | |

**`loans.contact_id`** — new nullable FK → `contacts.id` (`ON DELETE SET NULL`, so
deleting a contact unlinks its loans rather than deleting them). `counterparty` text kept.

**Documents — reuse `attachments`** (proven magic-byte mime + blob + backup pipeline):
- Add nullable **`contact_id`** FK → `contacts.id` (`ON DELETE CASCADE`).
- Relax **`ledger_entry_id`** to nullable.
- An attachment belongs to **exactly one** parent (a ledger entry XOR a contact) — enforced
  in the service layer (and a CHECK constraint where the DB supports it).
- **Backup:** add `Contact` to `EXPORT_MODELS` **before `Loan`** (loans FK contacts) and
  thus before `Attachment`; the restore id-remap already handles parent-before-child.

### 2. Services

**`services/contacts.py`** (new):
- `create_contact / update_contact / delete_contact / get_contact / list_contacts(owner)`
  — owner-scoped; validation (name required; photo size cap like avatar).
- `assign_loan(loan, contact_id|None)` / loan unlink — sets `loan.contact_id`
  (verify the contact is owned by the same user).
- `contact_state(session, contact) -> dict` — the rollup:
  - the contact's loans (`loan.contact_id == contact.id`), split given vs taken;
  - per **currency**: `{currency, loan_count, principal_outstanding_minor,
    interest_accrued_minor, interest_paid_minor, interest_due_minor}` (sum each loan's
    `loan_state` figures);
  - a **base-currency** grand total via `fx`/`networth` conversion (same helper the
    dashboard/net-worth uses), flagged approximate;
  - the linked-loan list (id, name, direction, currency, headline figures) for rendering.

**`services/attachments.py`** — generalize: `add_attachment(... , contact_id=None,
ledger_entry_id=None)` (exactly one); `list_for_contact(contact_id)`; access check that
maps a contact attachment to its owner.

### 3. API

- `contacts` blueprint (owner-only, `current_user` + ownership): `POST /api/contacts`,
  `GET /api/contacts`, `GET /api/contacts/<id>` (returns info + `contact_state` rollup +
  documents), `PATCH /api/contacts/<id>`, `DELETE /api/contacts/<id>`.
- Loan assignment: `PATCH /api/plans/<id>/loan` already edits loan terms — extend it to
  accept `contact_id` (or a dedicated `POST /api/plans/<id>/loan/contact`).
- Documents: `GET/POST /api/contacts/<id>/attachments` + reuse `GET /api/attachments/<id>`
  download (extend its access check to cover contact-owned attachments → owner-only).

### 4. UI

- **Sidebar:** new **Contacts** section (alongside Loans), with a count.
- **`contacts.html`** (list): each contact — photo, name, phone, loan count, headline
  outstanding (base-currency). "＋ New contact".
- **`contact-detail.html`**: full info (editable), photo (pick/crop like avatar), document
  list (upload/download/delete), the linked-loans list, and the **rollup** — per-currency
  blocks + the base-currency grand total. Delete contact.
- **Loan detail / create-plan / edit:** a **contact picker** (typeahead over existing
  contacts + "＋ New contact" inline). Loan detail shows the contact name → links to the
  contact page. Web route `GET /contacts` + `GET /contacts/<id>`.

### 5. Privacy (critical — interacts with last session's public share links)

Contacts are **owner-only**. Contact info must **never** leak into:
- **Shared-member** loan views (members see the loan, not the owner's private contact).
- **Public share links** (`/s/<token>`): `loan_state` must NOT start emitting contact
  fields; if any contact reference is added to `loan_state`, add its keys
  (`contact`, `contact_name`, `phone`, etc.) to the share `_SCRUB_KEYS` as defence-in-depth.
  A regression test asserts no contact PII in a public loan share.

## Testing

Service (`tests/test_contacts_service.py`):
- CRUD + owner scoping (can't read/edit another owner's contact).
- `assign_loan` links/unlinks; assigning a contact owned by another user is rejected.
- `contact_state`: 3 loans same currency → correct summed principal/interest; mixed
  INR+USD → per-currency subtotals exact + base-currency grand total present; given/taken
  split; a contact with no loans → zeros, empty list.
- delete contact → its loans get `contact_id = NULL` (not deleted); its document
  attachments cascade-delete.
- attachment: add to a contact; `list_for_contact`; exactly-one-parent enforced (passing
  both a ledger entry and a contact → error).

API (`tests/test_contacts_api.py`):
- CRUD owner-only (non-owner → 403/404); rollup shape; assign loan via the loan PATCH;
  upload/list/download/delete a contact document (owner-only download).

Privacy (`tests/test_public_share_api.py` extension):
- a loan assigned to a contact, shared publicly → the public envelope contains **no**
  contact name/phone/email.

Backup round-trip (`tests/test_backup.py` extension): a contact + its loan link + a
contact document export and re-import intact.

Migration: `contacts` table + `loans.contact_id` + `attachments.contact_id` /
nullable `ledger_entry_id`; single head; up+down clean.

UI: headless verify Contacts list + contact detail (rollup renders, 0 JS throws) per
`/build-screen`.

## Out of scope

- Contacts for non-loan plans (assets/holdings/chit) — loans only for now.
- Merging/deduping contacts; fuzzy auto-link of existing counterparty strings (manual assign).
- Sharing a contact with another user.
- Reminders/notifications on contacts.

## Docs

Update `docs/specs/khata-AS-BUILT.md` (data model: new `contacts` table + `attachments`
change; §9 + change log) in the same commit as the implementation.
