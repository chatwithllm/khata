# Khata Phase 5 · Plan 5.1 — Account Settings Design Spec

**Status:** Approved (autonomous) 2026-06-05. Backend (2 small endpoints) + a Settings page.

## Goal
A real **Settings** page: set/change your **password** (so Google-created users can add one), edit your
**display name**, and manage **base currency** + **FX rates** (endpoints already exist). Closes the
deferred auth follow-ups.

## Decisions (recommended)
- **Set-password requires only the session** (no old password) — a logged-in user is authenticated, and
  Google-created users (`password_hash=None`) have no old password to supply. Min length 6 (same as
  register). This lets a Google user add a password and thereafter also log in with email/password.
- **Profile = display name** only in v1. Profile-photo upload is a bigger feature — deferred (the mockups
  reference it; out of scope here).
- Base currency + FX rate management reuse the existing `POST /api/base-currency` + `POST /api/fx-rates`.

## Services (`src/khata/services/auth.py`)
- `set_password(session, *, user, password) -> User` — validates `len(password) >= 6`; sets
  `user.password_hash = hash_password(password)`; flush. Raises `AuthError` on a too-short password.
- `update_profile(session, *, user, display_name) -> User` — `display_name` stripped; if empty, raises
  `AuthError("display name required")`; sets it; flush.

## API (`src/khata/api/auth.py`)
- `POST /api/auth/password` `{password}` — 401 if unauthenticated; `set_password`; commit → 200
  `{ok:true}`. `AuthError` → 400.
- `POST /api/auth/profile` `{display_name}` — 401 if unauth; `update_profile`; commit → 200
  `{user:{id,email,display_name}}`. `AuthError` → 400.
- `GET /api/auth/me` already returns the user; the settings page also reads `/api/networth.base_currency`.
  Extend `_user_json` to add `has_password` (`bool(user.password_hash)`) so the UI can say "set" vs
  "change" password and show whether email/password login is available.

## Frontend (`static/settings.html` at `/settings`)
- Sections: **Profile** (display name input → `POST /api/auth/profile`); **Password** ("Set a password"
  for Google-only accounts vs "Change password"; input → `POST /api/auth/password`); **Currency** (base
  currency select → `POST /api/base-currency`; FX rate quote+rate → `POST /api/fx-rates`). Each section
  has its own inline success/error (textContent). Auth guard 401→`/`. On `ledger.css`.
- `web.py`: `/settings` → `settings.html`.
- `app.html`: the sidebar **Settings** item (currently a `.soon` placeholder) becomes a real link to
  `/settings`.

## Testing (TDD)
- `test_auth_service.py` (extend) — `set_password` (Google user with `password_hash=None` → can set, then
  `authenticate_user` works; too-short rejected); `update_profile` (sets; empty rejected).
- `test_auth_api.py` (extend) — `POST /api/auth/password` (401 unauth; 200 sets; 400 too-short;
  afterwards `/api/auth/login` with the new password works); `POST /api/auth/profile` (200 updates
  `/me`; 400 empty); `_user_json` includes `has_password`.
- `test_web.py` — `GET /settings` 200 + markers (`/api/auth/password`, `/api/auth/profile`,
  `/api/base-currency`, `ledger.css`).

## Out of scope
Profile photo upload · email change · account deletion · 2FA · old-password verification.

## Boundaries
`security.hash_password` ← `services/auth.py` (set_password/update_profile) ← `api/auth.py` ← settings
page. No model/migration changes (`password_hash` already nullable).
