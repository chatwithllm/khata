# Khata Phase 1 · Plan 5 — Google Sign-In + Features Page Design Spec

**Status:** Approved 2026-06-04. Builds on Plans 1–4 (auth, asset+ledger, loan, sharing).

## Goal
Add **Google sign-in** (identity-only, via Google Identity Services ID tokens) alongside the existing
email/password auth, and build the polished, static **Features & Limitations** page using the locked
editorial-ledger design kit.

## Scope
**In:** `users.google_sub` column + migration; an injectable Google ID-token verifier; a
`login_with_google` service (find-by-sub / link-by-verified-email / create); `GET /api/auth/config`
and `POST /api/auth/google` endpoints; `KHATA_GOOGLE_CLIENT_ID` config; a minimal real login/signup
section on the landing page with a Google button (shown only when configured); a full editorial-ledger
`features.html`; a shared stylesheet extracted from the mockup kit.

**Out (later):** server-side OAuth 2.0 auth-code flow · Google API scopes / refresh tokens · letting a
Google-created user set a password later · profile-picture import from Google · other social providers ·
building the full authenticated app UI (only the login surface is in scope).

## Locked rules honored
- Money/ledger rules untouched (no money code changes here).
- Auth stays **session-based** (signed cookie, `SECRET_KEY` from env). Google login sets the same
  `session["user_id"]` the password flow does.

## Decisions (from brainstorming)
- **Mechanism:** Google Identity Services (GIS). Frontend obtains a short-lived **ID token (JWT)**;
  backend **verifies** it (signature + `aud` + `iss` + `exp`). No client secret, no redirect dance,
  no Google API access — identity only.
- **Account linking:** auto-link by **verified** email. Match `google_sub` first, then email
  (only when `email_verified=true`); else create. Never link/create on an unverified email.
- **Library:** official `google-auth` (`google.oauth2.id_token.verify_oauth2_token`), which fetches
  and caches Google's public keys. The verifier is **injected** (app config) so tests stub it without
  network access.
- **Google-created users:** `display_name` taken from the token's `name` claim (fallback to email);
  `password_hash=None` (no password login until they set one — deferred).
- **Features page:** full editorial-ledger static page (fonts, palette, grain, scroll reveals).
- **Sign-in surface:** a minimal **real** login/signup section on the landing page (email+password +
  Google button), button gated on `/api/auth/config`.

## Data model
- **`User.google_sub`** — `Mapped[str | None]`, `String(64)`, `unique=True`, `nullable=True`,
  `index=True`. Stable Google account id (the `sub` claim). `password_hash` remains nullable.
- One Alembic revision: add `users.google_sub` + its unique index. Plain nullable column add — no
  batch mode required. `down_revision` = the Plan-4 head (`fcb8126c1b40`).

## Services (`src/khata/services/auth.py`)
- **Verifier (injectable):**
  - `verify_google_credential(credential: str, client_id: str) -> dict` — the real implementation,
    wrapping `verify_oauth2_token`. Returns the relevant claims as a plain dict:
    `{"sub", "email", "email_verified", "name"}`. Raises `GoogleAuthError` on any verification failure
    (bad signature/aud/iss/exp, malformed token).
  - The app stores a callable under `app.config["GOOGLE_VERIFIER"]` (defaults to the real one). The API
    reads it from config so tests can override it with a stub returning a fixed claims dict.
- **`login_with_google(session, *, claims: dict) -> tuple[User, bool]`** (returns `(user, created)`):
  1. `google_sub = claims["sub"]`. If a user with that `google_sub` exists → return `(user, False)`.
  2. Else if `claims.get("email_verified")` is true and a user with `email == claims["email"]` exists →
     set `user.google_sub = google_sub` (**link**), flush → return `(user, False)`.
  3. Else if `claims.get("email_verified")` is true → create
     `User(email=claims["email"].strip().lower(), display_name=(claims.get("name") or "").strip() or email,
     password_hash=None, google_sub=google_sub)`, flush → return `(user, True)`.
  4. Else (email not verified, no sub match) → raise `EmailUnverifiedError`.
- **Errors:** `GoogleAuthError(AuthError)` (token verification failures) and
  `EmailUnverifiedError(GoogleAuthError)` (unverified-email refusal) — both new. The API distinguishes
  them by **type**, not message string. Existing `AuthError`/`EmailTakenError`/
  `InvalidCredentialsError` unchanged.
- Email comparison normalizes (`strip().lower()`) consistent with `register_user`.

## API (`src/khata/api/auth.py`)
- **`GET /api/auth/config`** (public) → `200 {"google_client_id": <cfg.google_client_id or null>}`.
  Frontend uses it to decide whether to render the Google button. The client_id is public — safe to
  expose.
- **`POST /api/auth/google`** `{credential}`:
  - If `cfg.google_client_id` is unset → `503 {"error":"google_not_configured"}`.
  - Else call `verifier(credential, cfg.google_client_id)` to get `claims`, then
    `user, created = login_with_google(g.db, claims=claims)`, inside one `try`:
    - `except EmailUnverifiedError` → `403 {"error":"email_unverified"}` (rollback).
    - `except (GoogleAuthError, ValueError)` → `401 {"error":"invalid_token"}` (rollback).
  - On success: `g.db.commit()`;
    `session["user_id"] = user.id`; return `200 {"user": _user_json(user), "created": created}`.
  - The verifier comes from `current_app.config["GOOGLE_VERIFIER"]`.
- Existing `register`/`login`/`logout`/`me` unchanged.

## Config (`src/khata/config.py`)
- `self.google_client_id = os.environ.get("KHATA_GOOGLE_CLIENT_ID")` (None when unset).
- App factory sets `app.config["GOOGLE_VERIFIER"] = verify_google_credential` by default.
- `requirements.txt`: add `google-auth` and `requests` (google-auth's request transport).

## Frontend
A shared stylesheet `src/khata/static/assets/ledger.css` is extracted from the mockup kit
(`docs/mockups/_SHARED_KIT.md`): CSS custom properties (INR/USD palettes), Fraunces/Hanken
Grotesk/JetBrains Mono `@import`, film-grain/texture utilities, `.reveal` scroll-in, shared `.nav`
and `.foot`. Both pages link it.

- **`src/khata/static/index.html`** (replace 7-line placeholder): editorial landing page with a real
  **login/signup section**:
  - Email + password form → posts JSON to `/api/auth/login`; a register toggle → `/api/auth/register`.
    On success, redirect to `/app`. Inline error display on 401/409/400.
  - A "Continue with Google" area: on load, `fetch('/api/auth/config')`; if `google_client_id` is
    present, inject the GIS script (`https://accounts.google.com/gsi/client`), initialize with the
    client_id, render the button; its callback POSTs `{credential: response.credential}` to
    `/api/auth/google` and redirects to `/app` on `200`. If no client_id, the Google area stays hidden.
  - Nav links to `/features`.
- **`src/khata/static/features.html`** (replace 15-line placeholder): full editorial-ledger
  **Features & Limitations** page. Shared nav/footer, fonts, palette, grain, scroll reveals. Honest
  sections, each with a **Limitations** note:
  - Multi-user sharing & per-payment attribution
  - Single source of truth (derived balances)
  - Money as integer minor units (never float)
  - Asset purchase roll-forward
  - Loan interest (reducing-balance, simple, whole-month)
  - Net-position dashboard
  - Self-hosted & privacy-first
  - Sign in with Google (identity-only)

## Web routes
`src/khata/web.py` already serves `/`, `/app`, `/features` from the static dir — no route changes; the
HTML files are replaced. The `static/assets/` dir is served by Flask's existing static handler.

## Testing (TDD, pytest)
- **`test_auth_service.py`** (extend or new): `login_with_google` —
  create-new (verified email, no existing) → `created=True`, `password_hash is None`, `google_sub` set;
  link-by-verified-email (existing password user, same email) → links `google_sub`, `created=False`;
  match-by-`google_sub` on repeat → same user, `created=False`, no duplicate; refuse unverified email
  (no sub match) → raises `EmailUnverifiedError`; `name`→`display_name` on create; missing name falls
  back to email.
- **`test_auth_api.py`** (extend): with `app.config["GOOGLE_VERIFIER"]` stubbed to return a fixed claims
  dict — `POST /api/auth/google` → 200, sets session, `/api/auth/me` returns the user, `created` flag
  correct; `GET /api/auth/config` returns the configured id and `null` when unset;
  `google_not_configured` → 503; a verifier that raises `GoogleAuthError("invalid")` → 401; one that
  raises `GoogleAuthError("email_unverified")` → 403. Existing email/password tests stay green.
- **`test_web.py`** (light, new or extend): `GET /features` → 200 and body contains the section
  headings (e.g. "Limitations", "Single source of truth"); `GET /` → 200 and contains the login form +
  a reference to `/api/auth/config`.

## Migration & wiring
- One Alembic revision: `users.google_sub` + unique index (`down_revision = fcb8126c1b40`).
- `config.py`: add `google_client_id`; factory registers the default `GOOGLE_VERIFIER`.
- No new blueprint — endpoints extend the existing `auth` blueprint.

## Component boundaries
`config.py` (client_id) → `services/auth.py` (verifier + `login_with_google`, pure/session-injected,
no Flask) → `api/auth.py` (HTTP + session + config dispatch). The verifier is the only network-touching
unit and is injected, so all auth logic is testable without Google. The two static pages depend only on
the shared `ledger.css`, not on backend internals.
