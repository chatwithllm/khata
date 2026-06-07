# Google Sign-In — Enable & Harden Behind a Reverse Proxy

**Date:** 2026-06-07
**Status:** Approved design → ready for implementation plan

## Summary

Google Sign-In is **already fully implemented and tested** in Khata. It is dormant
only because no OAuth client id is configured. This work **enables** it and makes the
app **correct and secure when served over HTTPS through the user's existing reverse
proxy**. No authentication logic changes.

## Background — what already exists (do not rebuild)

- **Backend** (`src/khata/services/auth.py`):
  - `verify_google_credential(credential, client_id)` — verifies a Google ID token via
    the official `google-auth` library (`google.oauth2.id_token.verify_oauth2_token`).
    `google-auth` is installed.
  - `login_with_google(session, *, claims)` — find-by-`google_sub` / link-by-verified-email
    / create. Raises `EmailUnverifiedError` (unverified email) and `GoogleAuthError`
    (`account_link_conflict` when an email already linked to a different sub).
- **API** (`src/khata/api/auth.py`):
  - `GET /api/auth/config` → `{google_client_id}`.
  - `POST /api/auth/google` → verifies `{credential}`, calls `login_with_google`, sets
    `session["user_id"]`. Returns `503 google_not_configured` when no client id;
    `403 email_unverified`; `401 invalid_token`.
- **App factory** (`src/khata/__init__.py`): injects `GOOGLE_VERIFIER = verify_google_credential`.
- **Model** (`src/khata/models/user.py`): `google_sub` (unique, indexed, nullable).
- **Frontend** (`src/khata/static/index.html`): loads Google Identity Services
  (`accounts.google.com/gsi/client`), calls `id.initialize({client_id})` +
  `renderButton`, and the `onGoogle` callback POSTs the credential to
  `/api/auth/google`. The "Continue with Google" CTA is revealed only when
  `/api/auth/config` returns a client id.
- **Tests:** `tests/test_auth_api.py`, `tests/test_auth_service.py` cover the endpoint
  and link/create logic with an injected verifier.

## The hard external constraint (already solved by the user)

Google Identity Services requires the page to be a **secure context** and the OAuth
client's **Authorized JavaScript origin** to be **HTTPS with a hostname** —
`http://`, and raw IP addresses (e.g. `https://192.168.50.190`), are rejected
(`localhost` is the only exception). The canonical Khata instance runs
`http://<LAN-IP>:5057`, which Google rejects.

**Resolution (user-owned, out of scope for code):** the user already runs a reverse
proxy on their own domain that terminates HTTPS and will forward to the app. The app
must simply behave correctly behind it.

## Scope of this work

Three small pieces. No new dependencies (ProxyFix ships with Werkzeug/Flask).

### 1. Configure the client id

- New env var consumed by `Config`: `KHATA_GOOGLE_CLIENT_ID` already exists
  (`config.google_client_id`). Operator sets it in `.env.app`.
- No code change for this piece beyond it already being read; setting it flips the
  feature on (button reveals, endpoint stops 503-ing).

### 2. Proxy-awareness + cookie hardening (opt-in flag)

A single opt-in flag means "this instance runs behind a trusted HTTPS reverse proxy."

- **`src/khata/config.py`:** add
  `self.secure_cookies = os.environ.get("KHATA_SECURE_COOKIES", "").lower() in {"1", "true", "yes"}`.
- **`src/khata/__init__.py` (`create_app`):** when `cfg.secure_cookies` is true:
  - Wrap the WSGI app with `ProxyFix`:
    `from werkzeug.middleware.proxy_fix import ProxyFix;
     app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)` — so `request.scheme`
    reflects `X-Forwarded-Proto` from the proxy.
  - Set cookie flags:
    `app.config.update(SESSION_COOKIE_SECURE=True, SESSION_COOKIE_HTTPONLY=True,
     SESSION_COOKIE_SAMESITE="Lax")`.
- **Why a flag, not `KHATA_ENV`:** the canonical instance is started with
  `KHATA_ENV=production` but accessed directly over **http** on `:5057` for testing. A
  `Secure` cookie would never be sent over http → silent login failure. The flag is set
  **only** on the proxied instance, so direct-http testing keeps working.
- `SameSite=Lax` is correct: the GSI credential is POSTed by first-party JS to a
  same-origin endpoint; there is no cross-site cookie requirement. (`Strict` would also
  work but Lax is the safe default.)

### 3. Operator runbook (documentation)

Add a short runbook (in `docs/` and/or the AS-BUILT doc) covering:

1. **OAuth client** — *reuse or create*:
   - **Reuse** an existing Google OAuth 2.0 **Web** client: add
     `https://<khata-domain>` to its *Authorized JavaScript origins*. Works; the
     sign-in popup shows that client's consent-screen app name.
   - **Or create** a fresh Web client (clean "Khata" branding): Google Cloud Console →
     APIs & Services → Credentials → Create OAuth client ID → Web application →
     Authorized JavaScript origins = `https://<khata-domain>`. (No redirect URI needed —
     GSI uses origin only.)
2. **Reverse proxy** — terminate TLS for `https://<khata-domain>` and proxy to
   `http://127.0.0.1:5057`, passing `X-Forwarded-Proto https` (and `Host`).
3. **App env** (`.env.app`): `KHATA_GOOGLE_CLIENT_ID=<client-id>` and
   `KHATA_SECURE_COOKIES=1`; restart via `run-app.sh`.
4. **Verify:** load `https://<khata-domain>`, the "Continue with Google" button appears,
   a real sign-in creates a new account (or links to an existing email) and the session
   persists across requests.

## Out of scope

- No changes to `login_with_google` / `verify_google_credential` / the endpoint.
- No new Python dependencies.
- No public internet exposure or DNS/cert automation (user-owned).
- No change to email+password auth (continues to work; remains the default).

## Architecture / data flow (unchanged, for reference)

```
Phone (HTTPS) ── user's reverse proxy ──(http, X-Forwarded-Proto: https)── Flask :5057
   │  GSI button (secure context, origin = https://<domain>)
   │  user authenticates with Google → ID token (credential)
   └─ POST /api/auth/google {credential}
        → GOOGLE_VERIFIER(credential, client_id)  → claims
        → login_with_google(claims)               → (user, created)
        → session["user_id"] = user.id            → Secure cookie (flag on)
```

## Error handling (existing, verified)

- No client id → `503 google_not_configured` (button stays hidden anyway).
- Unverified Google email → `403 email_unverified`.
- Bad/expired token or link conflict → `401 invalid_token`.

## Testing

- **Config (new):** `KHATA_SECURE_COOKIES=1` → `app.config["SESSION_COOKIE_SECURE"] is
  True` and `app.wsgi_app` is a `ProxyFix` instance; unset → `SESSION_COOKIE_SECURE`
  falsy and direct-http session login still works.
- **Proxy scheme (new):** with the flag on, a request carrying
  `X-Forwarded-Proto: https` is seen by the app as `request.scheme == "https"`.
- **Existing:** `/api/auth/google` happy-path (injected verifier → link/create) and
  `/api/auth/config` exposing the client id remain green.
- **Manual (runbook):** a real Google sign-in end-to-end on the proxied HTTPS domain —
  cannot be unit-tested (real Google token), covered by the runbook verification step.

## Success criteria

1. With `KHATA_GOOGLE_CLIENT_ID` set and served over the HTTPS domain, the
   "Continue with Google" button appears and a real sign-in creates/links an account.
2. With `KHATA_SECURE_COOKIES=1`, the session cookie is `Secure; HttpOnly; SameSite=Lax`
   and the app sees `https` via the proxy.
3. With neither flag set (direct `http://:5057`), existing behavior is unchanged —
   email+password and direct-http session login still work.
4. All existing tests stay green; new config tests pass.
