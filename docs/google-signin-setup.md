# Enabling Google Sign-In

Google Sign-In is already built into Khata. It stays hidden until you configure an
OAuth client id, and it only works when the app is served over **HTTPS on a real
hostname** (Google rejects `http://` and raw IP origins; only `localhost` is exempt).
You already run a reverse proxy on your own domain, so this is just configuration.

## 1. OAuth client (reuse or create)

Google OAuth clients serve multiple origins, so you can reuse an existing one.

**Reuse an existing Web client:**
- Google Cloud Console → APIs & Services → Credentials → your existing OAuth 2.0 **Web**
  client → add `https://<your-khata-domain>` under **Authorized JavaScript origins** → Save.
- Note: the sign-in popup shows that client's consent-screen app name.

**Or create a fresh client (clean "Khata" branding):**
- Credentials → Create credentials → OAuth client ID → Application type **Web application**.
- **Authorized JavaScript origins:** `https://<your-khata-domain>`. (No redirect URI —
  Google Identity Services uses the origin only.)
- Copy the **Client ID**.

## 2. Reverse proxy

Terminate TLS for `https://<your-khata-domain>` and proxy to the app, passing the
forwarded scheme. Example (Caddy):

    <your-khata-domain> {
        reverse_proxy 127.0.0.1:5057 {
            header_up X-Forwarded-Proto https
        }
    }

(Caddy/most proxies pass `Host` and `X-Forwarded-Proto` by default; set it explicitly
if yours does not.)

## 3. App environment

In `.env.app`:

    KHATA_GOOGLE_CLIENT_ID=<your-client-id>
    KHATA_SECURE_COOKIES=1

Then restart: `./run-app.sh`.

- `KHATA_GOOGLE_CLIENT_ID` reveals the "Continue with Google" button and enables
  `POST /api/auth/google`.
- `KHATA_SECURE_COOKIES=1` makes the app trust the proxy's `X-Forwarded-Proto` and marks
  the session cookie `Secure; HttpOnly; SameSite=Lax`. Set it **only** on the
  proxied instance — direct `http://<lan-ip>:5057` access would stop logging in with a
  Secure cookie.

## 4. Verify

- Open `https://<your-khata-domain>` → the "Continue with Google" button appears.
- Sign in with Google → a new account is created, or it links to an existing account
  with the same verified email. The session persists across page loads.
- DevTools → Application → Cookies: the `session` cookie shows `Secure` + `HttpOnly`.
