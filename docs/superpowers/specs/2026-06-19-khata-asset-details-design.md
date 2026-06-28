# Asset details — parties, custom info, documents & links

**Date:** 2026-06-19
**Branch:** `feat/asset-details`
**Status:** approved design

## Problem

An Asset is just `total_price_minor` + installments. There's nowhere to record **who you
bought from / sold to**, arbitrary **tracking info** (survey number, area, registration
date…), or to attach **documents/proofs/receipts** and **video** of the asset.

## Goal

On the asset detail page: edit **seller** & **buyer** (free text, optionally linked to a
Contact), add arbitrary **custom info** rows, attach **documents** (DB-blob files), and add
**links** (video walkthroughs, Drive folders, maps — URLs, not uploaded).

## Decisions (locked in brainstorming)

- **Seller/buyer:** free-text name + an optional link to a Contact. Keep BOTH parties.
- **Custom info + links:** **JSON columns** on `asset_purchases` (small ordered lists,
  edited as a block; auto-covered by the whole-instance JSON backup) — no new tables.
- **Documents:** reuse the existing DB-blob `attachments` (photos/receipts/PDF/Office, 25 MB
  cap). **Video = a link**, not an upload (keeps the one-file backup intact).

## Architecture

### 1. Data model (migration on `asset_purchases` + `attachments`)

`asset_purchases` gains:

| column | type | notes |
|---|---|---|
| `seller_name` | Text, nullable | free text |
| `seller_contact_id` | FK→contacts, nullable, ON DELETE SET NULL | optional contact link |
| `buyer_name` | Text, nullable | |
| `buyer_contact_id` | FK→contacts, nullable, SET NULL | |
| `extra_fields` | Text(JSON), nullable | JSON array `[{"label","value"}]` |
| `links` | Text(JSON), nullable | JSON array `[{"label","url"}]` |

(JSON stored as `Text` containing `json.dumps(...)`; the service (de)serializes — SQLite has
no native JSON column type the project uses elsewhere; `Text` keeps backup base64-free and
human-readable.)

`attachments` gains a **third parent**:
- `asset_plan_id` (nullable FK→plans.id, ON DELETE CASCADE). An attachment belongs to
  **exactly one** of {`ledger_entry_id`, `contact_id`, `asset_plan_id`}.

### 2. Service — `services/assets.py`

- `update_asset_meta(session, *, plan, owner_id, seller_name?, seller_contact_id?,
  buyer_name?, buyer_contact_id?, extra_fields?, links?) -> AssetPurchase`:
  - owner-only (asset edit is an owner action, like other plan-term edits).
  - validate any `*_contact_id` is owned by the same user (reuse `contacts.get_contact`); else error.
  - `extra_fields`: list of `{label,value}` — trim, drop blank-label rows, cap count (e.g. ≤40) and lengths.
  - `links`: list of `{label,url}` — **URL must be http(s)** (reject `javascript:`/`data:`/other
    schemes); trim; cap count + length. A link MAY carry `"video": true` (client hint) — store it.
  - serialize `extra_fields`/`links` to JSON Text.
- `asset_state` extended to surface: `seller`/`buyer` (`{name, contact_id, contact_name?}`),
  `extra_fields` (parsed list), `links` (parsed list), and `attachment_count`/list for the asset.
- Generalize `attachments.add_attachment(... entry=None, contact=None, asset_plan=None)` —
  exactly-one-parent now over THREE; add `list_for_asset(session, plan_id)`.

### 3. API (`api/plans.py` + `api/contacts.py`/`attachments.py`)

- `PATCH /api/plans/<id>/asset/meta` (owner-only) → `update_asset_meta`, returns the refreshed
  `asset_state`.
- Asset documents: `GET/POST /api/plans/<id>/asset/attachments` (multipart `file`); reuse the
  download route `GET /api/attachments/<id>` — extend its access branch: for an
  `asset_plan_id` attachment, allow anyone with **plan access** (`sharing.accessible`), same as
  ledger-entry attachments (NOT owner-only — assets can be shared). Delete: owner or uploader.

### 4. UI — `static/asset-detail.html`

- An **"Edit details"** panel/modal: seller & buyer (text input + "link contact" typeahead from
  `/api/contacts`, showing the linked name + a clear-link button), repeatable **custom-field
  rows** (label + value, add/remove), repeatable **link rows** (label + URL, an "is video"
  checkbox). Save → `PATCH /asset/meta`.
- A **Documents** card: upload (file picker → multipart POST), list (filename + download +
  delete), reusing the contact-docs UI pattern.
- A **Links** card: each link as a row (label → opens `url` in a new tab, `rel="noopener
  noreferrer"`; video links get a ▶ marker). No iframe/embedding — safe outbound anchors only.
- Seller/buyer shown read-only on the detail header when set (name → `/contacts/<id>` when linked).

### 5. Privacy / security

- `update_asset_meta` + asset-doc upload/delete are **owner-only**; asset-doc **download** is
  **plan-accessible** (members of a shared asset can view).
- **URLs:** only `http(s)` accepted (server-validated); rendered as anchors with
  `rel="noopener noreferrer"`, `target="_blank"`; all labels/values via `textContent` (XSS-safe).
- **Public share leak guard:** if an asset is shared via a public link, seller/buyer/extra_fields/
  links must NOT appear. `asset_state` will carry them, so the public `sharing_links` scrub must
  drop them — add `seller`, `buyer`, `seller_name`, `buyer_name`, `extra_fields`, `links`,
  `contact_name`, `url` to `_SCRUB_KEYS`, with a regression test asserting no asset PII in a public
  asset share. (Public asset views show figures only, not parties/notes/docs.)

## Testing

Service (`tests/test_asset_meta.py`):
- set seller/buyer text + contact link; reject a foreign `*_contact_id`.
- extra_fields/links round-trip (parse back to lists); blank-label rows dropped; count/length caps.
- **URL validation:** `javascript:`/`data:` links rejected; `http(s)` accepted.
- `asset_state` surfaces seller/buyer (+ resolved contact name), extra_fields, links.
- attachments: asset parent add/list; **exactly-one-of-three** parent enforced; delete-plan
  cascades asset attachments.

API (`tests/test_asset_meta_api.py`): PATCH owner-only (non-owner 403); asset-doc upload/list +
**plan-member download** (a shared member can download; a stranger 403/404); delete owner/uploader.

Privacy (`tests/test_public_share_api.py` ext): an asset with seller/buyer/extra_fields/links
shared publicly → none appear in `/api/public/<token>`.

Backup round-trip: an asset with the new columns + an asset attachment export/import intact
(asset_purchases already in EXPORT_MODELS; attachments too — asset_plan_id rides along).

UI: headless verify the edit panel + documents + links on asset-detail, 0 JS throws, per
`/build-screen`.

## Out of scope

- Video **upload**/storage (chose link).
- Custom fields for non-asset plan types.
- Per-field typing/validation beyond text (it's free key/value).
- Embedding/streaming videos (outbound links only).

## Docs

Update `docs/specs/khata-AS-BUILT.md` (data model: asset_purchases new columns + attachments
third parent; §9 + change log) in the same commit as the implementation.
