# Khata on iPhone + iPad + Mac (free, SideStore + PWA) — Design

**Date:** 2026-06-12
**Status:** Approved

## Problem

Khata should be installable as an app on the owner's iPhone, iPad, and Mac, updatable
weekly over WiFi, **without** an App Store listing and **without** paying the $99/yr Apple
Developer Program. Personal use only — the owner installs on their own devices.

## Context (what already exists)

- `mobile/` is an **Expo / React Native** app (Expo 56, RN 0.85, expo-router). Managed
  workflow — no `ios/` native folder yet (`expo prebuild` not run).
- Screens present: `(auth)/login`, `(tabs)/{index,analysis,holdings,networth,settings}`,
  `create-plan`, `plan/[type]/[id]`. No iPad/tablet layout logic anywhere.
- `app.json`: `orientation: portrait`, **no** `ios.bundleIdentifier`, **no** `supportsTablet`,
  **no** `expo-updates`. `web.output: static` (so a web build exists for Mac).
- `src/config.ts`: `API_BASE` with dev fallback `http://192.168.50.189:5057`, overridable via
  `EXPO_PUBLIC_API_BASE`.
- `src/api/client.ts`: fetch wrapper injecting `Authorization: Bearer <token>`.
- Backend: Flask JSON API under `/api/*`; **bearer-token auth already built**
  (`src/khata/tokens.py`, signed stateless 30-day tokens; `/api/auth/{login,register,google,me}`
  return a token). CORS `*` on `/api/*` (safe — bearer, not cookies).
- Web frontend: server-rendered static HTML (`src/khata/static/*.html`), `no-store`, already
  responsive across all pages.

## Decision

Extend the existing Expo app; do **not** rebuild native from scratch. Reach the three devices
on a free Apple ID:

- **iPhone + iPad**: the Expo app, built to an **unsigned device `.ipa`**, signed by
  **SideStore** with the owner's free Apple ID, auto-refreshed over WiFi every ≤7 days.
- **Mac**: a **PWA** of the existing web app (no native signing path is free for Mac; web is
  the clean free Mac story, and instant-updating).

### Why this and not alternatives

- *Paid Apple Developer ($99)* — rejected by the owner.
- *Pure SwiftUI native* — can't OTA-update outside App Store; weeks of rebuild; abandons Expo.
- *PWA-only on all three* — viable and free, but the owner chose native for iPhone/iPad feel.
- *Free Apple ID + Xcode direct install* — same 7-day expiry as SideStore but **manual**
  re-install every week with a cable. SideStore automates the refresh over WiFi.

## Build-vs-manual boundary

Some steps are physically bound to the owner's devices and Apple ID and **cannot** be done by
the implementer/agent: producing the signed `.ipa` on a real device, the SideStore tethered
setup, and the on-device install. The implementer delivers everything in-repo (config, iPad
layout, Mac PWA, build script, runbook); the owner runs the device steps following the runbook.

## Phase 1 — Mac PWA (today, zero Apple)

Make the existing web app installable as a desktop app, and as an iOS home-screen fallback.

### `src/khata/static/manifest.webmanifest` (new)
Standard PWA manifest: `name` "Khata", `short_name` "Khata", `start_url` "/app",
`display` "standalone", `background_color`/`theme_color` matching the app shell
(`#208AEF` / paper), `icons` (192, 512, and a maskable variant) referencing existing
`assets/` icons (reuse the mobile app icon PNGs, copied into `static/assets/icons/`).

### `src/khata/static/sw.js` (new)
A minimal service worker: cache-first for static assets (CSS/JS/icons), **network-first** for
HTML and `/api/*` (so data is always fresh; HTML is `no-store` anyway). Versioned cache name
bumped on deploy. No offline write queue (out of scope) — offline just shows the last cached
shell + a "connection lost" state from the existing API error handling.

### HTML `<head>` additions (each app HTML page, or the shared shell)
- `<link rel="manifest" href="/manifest.webmanifest">`
- `<meta name="apple-mobile-web-app-capable" content="yes">`
- `<meta name="apple-mobile-web-app-status-bar-style" content="default">`
- `<meta name="apple-mobile-web-app-title" content="Khata">`
- `<link rel="apple-touch-icon" href="/static/assets/icons/icon-192.png">`
- `<meta name="theme-color" content="#208AEF">`
- A small `navigator.serviceWorker.register('/sw.js')` script (guarded; no-op if unsupported).

### Flask serving (`src/khata/web.py`)
Serve `/manifest.webmanifest` (mimetype `application/manifest+json`) and `/sw.js`
(mimetype `text/javascript`, `Cache-Control: no-store` so SW updates land). Both from the
static dir.

**Outcome:** Mac — install from Safari ("Add to Dock") or Chrome ("Install Khata") → desktop
app icon, own window. iPhone/iPad — Safari Share → Add to Home Screen works as a fallback if
SideStore is ever down.

## Phase 2 — iPhone + iPad native via SideStore

### 2a. App config (`mobile/app.json`)
- Add `ios.bundleIdentifier`: `com.npalakurla.khata` (stable; required for signing).
- Add `ios.supportsTablet: true`.
- Change `orientation` from `portrait` to `default` (lets iPad rotate; iPhone screens already
  work portrait and tolerate landscape).
- Add `ios.infoPlist` only if needed by existing plugins (image-picker already configures its
  own usage strings via the plugin — verify during implementation; add `NSPhotoLibraryUsageDescription`
  only if the prebuild warns it's missing).

### 2b. iPad layout (`mobile/src/`)
The screens were built phone-first with no width logic. Add a single shared responsive helper
and apply it where fixed-width / single-column layouts look stranded on iPad:
- `mobile/src/theme/layout.ts` (new): `useLayout()` → `{ width, isWide }` from
  `useWindowDimensions()`, `isWide = width >= 700`; plus `CONTENT_MAX = 720` (cap reading width)
  and a `columns` helper (`isWide ? 2 : 1`).
- Apply in the list/grid screens (`(tabs)/index`, `holdings`, `networth`, `analysis`): center
  content within `CONTENT_MAX`, and render card/list grids in 2 columns when `isWide`.
- `plan/[type]/[id]` and `create-plan`: center within `CONTENT_MAX`; keep single column (forms
  read better narrow).
- No new screens; only layout props. Each screen verified at iPhone and iPad widths in the
  simulator (`expo start --ios`, toggle device).

### 2c. Point at the server (`mobile/src/config.ts`)
Set the production `API_BASE` to `https://khata.npalakurla.com` (public domain, already
serving the API with CORS `*` + bearer auth). Keep the `EXPO_PUBLIC_API_BASE` override for LAN
testing (`http://192.168.50.14:5057`). Document both.

### 2d. Build script + native project (`mobile/`)
- Run `expo prebuild --platform ios` → generates `mobile/ios/` (Xcode project). Commit it (so
  the build is reproducible and the owner opens a ready project).
- `mobile/scripts/build-ipa.md` (runbook) — exact steps for the owner on their Mac:
  1. `cd mobile && npm install && npx expo prebuild -p ios` (if `ios/` stale).
  2. `open ios/Khata.xcworkspace`.
  3. Xcode → set Signing team to the **free personal Apple ID** team; bundle id
     `com.npalakurla.khata`.
  4. Product → Archive (target "Any iOS Device").
  5. Distribute → "Custom" / export **without** App Store signing → produces the `.ipa`
     (or use the documented `xcodebuild -exportArchive` invocation with an ad-hoc/dev
     export plist for an unsigned/dev-signed `.ipa` SideStore can re-sign).
  - The script documents both the GUI and CLI routes; the GUI route is primary.

### 2e. SideStore runbook (`mobile/scripts/sidestore-setup.md`, new)
Step-by-step for the owner (one-time tethered, then on-device):
1. Prereqs: free Apple ID, a Mac (have it), iPhone/iPad on the same WiFi.
2. Generate the device **pairing file** (via the documented `jitterbugpair`/Apple-Mobile-Device
   tooling) — exact commands.
3. Choose an **anisette** source (self-hosted via the documented Docker one-liner, or a public
   anisette server) — note the privacy/uptime trade-off.
4. Install **SideStore** onto the device (one-time, computer-assisted) per its current docs;
   record the device UDID with the free Apple ID.
5. In SideStore, install the Khata `.ipa` from Phase 2d.
6. Enable SideStore background refresh → it re-signs Khata over WiFi every ≤7 days. Note the
   free-account limits: max 3 sideloaded apps, 10 app IDs / 7 days.
7. Troubleshooting: anisette auth failures, "app expired" manual refresh, re-pairing.

This file is a **runbook**, not code — it cannot be executed by the implementer; it documents
exactly what the owner does.

## Phase 3 — Weekly OTA feature pushes (deferred, documented only)

`expo-updates` self-hosted on the Khata box: publish a JS bundle the installed app pulls over
WiFi between SideStore's 7-day native refreshes — push UI changes with no rebuild. Documented
as future work in the spec; **not implemented in this project**. Captured so the bundleId /
config choices here don't block it later.

## Testing

- **Phase 1 PWA:** headless/manual — `/manifest.webmanifest` and `/sw.js` served with correct
  mimetypes; HTML carries the manifest link + apple meta; SW registers without console errors;
  Lighthouse "installable" passes; Mac install produces a standalone window; iOS Add-to-Home
  shows the Khata icon + standalone chrome. The existing pytest suite must stay green (the only
  backend change is two static-file routes — add a test asserting both endpoints return 200 with
  the expected `Content-Type`).
- **Phase 2 iPad layout:** simulator at iPhone (390pt) and iPad (834pt+) widths — no stranded
  single-column-on-wide screens, no overflow, touch targets ≥44pt, content capped at
  `CONTENT_MAX`. Manual (no RN test harness in repo).
- **Phase 2 build/SideStore:** validated by the owner following the runbook on real devices —
  out of the implementer's reach; the deliverable is a correct, complete runbook + a committed,
  prebuilt `ios/` project that opens and archives in Xcode.

## Docs

`docs/specs/khata-AS-BUILT.md`: a §-level note that Khata ships as (a) a Mac/iOS PWA and (b) an
Expo native iOS app installed via SideStore, with pointers to the two runbooks; plus a dated
change-log entry. Same commits as the code.

## Out of scope

- Apple Developer Program / App Store / TestFlight.
- True-native Mac (Mac Catalyst / react-native-macos).
- `expo-updates` OTA implementation (Phase 3, documented only).
- Android distribution (the Expo app still builds for Android; not part of this project).
- Offline write/sync queue in the PWA.
- Push notifications.

## Risks

- **Free-account treadmill:** 7-day cert expiry, max 3 sideloaded apps, anisette dependency.
  SideStore automates refresh but can break on Apple auth changes — the runbook includes
  recovery steps; the Mac/iOS PWA is the always-available fallback.
- **Build environment:** the `.ipa` export needs the owner's Mac + free Apple ID; the
  implementer commits the `ios/` project and runbook but cannot produce the device binary.
- **Public API exposure:** pointing the app at `khata.npalakurla.com` means the bearer-token
  API is reachable from the internet (already the case for the web app). No new surface; auth
  unchanged.
