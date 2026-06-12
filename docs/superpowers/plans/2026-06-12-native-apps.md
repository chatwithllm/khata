# Khata on iPhone + iPad + Mac (free) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Khata installable on the owner's iPhone, iPad, and Mac for free — a Mac/iOS PWA of the web app, plus the existing Expo native app prepared for SideStore install with an iPad-friendly layout — no App Store, no $99 Apple Developer Program.

**Architecture:** Two tracks. **Web/PWA** (Flask static): a `manifest.webmanifest` + service worker + apple meta injected via the already-shared `nav.js`, served by two new Flask routes → installable on Mac (desktop app) and iOS (Add to Home Screen). **Mobile** (Expo RN): set `bundleIdentifier`/`supportsTablet`, point the app at the prod API, cap content width on wide screens via the shared `Screen` component, and ship two runbooks (build the `.ipa`, set up SideStore). Phase 3 OTA (`expo-updates`) is documented-only.

**Tech Stack:** Flask + SQLAlchemy (PWA routes + pytest), vanilla JS (nav.js, sw.js), Expo 56 / React Native 0.85 / TypeScript (mobile), `sips` (macOS icon resize), Xcode + SideStore (owner-run). pytest: `/Users/assistant/dev/active/khata/.venv/bin/python -m pytest`. Test instance: `bash /Users/assistant/dev/active/khata/run-app.sh` → :5057.

**Boundary — code vs owner-run:** Tasks 1–4 + 7 are code the implementer writes and verifies. Tasks 5–6 are **runbooks** (Markdown) the implementer authors but the **owner** executes on real devices/Apple-ID — they cannot be run here. Do not attempt the device steps; deliver correct, complete runbooks.

---

## File Structure

- `src/khata/static/manifest.webmanifest` (new) — PWA manifest.
- `src/khata/static/sw.js` (new) — service worker (network-first HTML/API, cache-first static).
- `src/khata/static/assets/icons/` (new) — `icon-192.png`, `icon-512.png`, `apple-touch-icon.png` (resized from the mobile app icon).
- `src/khata/static/assets/nav.js` (modify) — prepend PWA init (inject tags + register SW).
- `src/khata/web.py` (modify) — routes for `/manifest.webmanifest` + `/sw.js`.
- `tests/test_pwa.py` (new) — assert both routes serve with correct mimetypes/headers.
- `mobile/app.json` (modify) — `ios.bundleIdentifier`, `ios.supportsTablet`, `orientation`.
- `mobile/src/config.ts` (modify) — prod `API_BASE`.
- `mobile/src/components/ui.tsx` (modify) — `Screen` caps content width on wide screens.
- `mobile/docs/build-ipa.md` (new) — runbook: prebuild → Xcode archive → unsigned `.ipa`.
- `mobile/docs/sidestore-setup.md` (new) — runbook: SideStore one-time + weekly WiFi refresh.
- `mobile/.gitignore` (modify if needed) — ignore the generated `ios/`.
- `docs/specs/khata-AS-BUILT.md` (modify) — distribution note + change-log entry.

---

### Task 1: PWA manifest, service worker, icons, Flask routes

**Files:**
- Create: `src/khata/static/manifest.webmanifest`, `src/khata/static/sw.js`, `src/khata/static/assets/icons/*`
- Modify: `src/khata/web.py`
- Test: `tests/test_pwa.py`

- [ ] **Step 1: Generate the PWA icons from the existing mobile app icon**

```bash
mkdir -p src/khata/static/assets/icons
sips -z 192 192 mobile/assets/images/icon.png --out src/khata/static/assets/icons/icon-192.png
sips -z 512 512 mobile/assets/images/icon.png --out src/khata/static/assets/icons/icon-512.png
sips -z 180 180 mobile/assets/images/icon.png --out src/khata/static/assets/icons/apple-touch-icon.png
```
Expected: three PNGs created. If `mobile/assets/images/icon.png` does not exist, run `ls mobile/assets/images/` and use the closest square app icon PNG there instead (report the substitution).

- [ ] **Step 2: Create the manifest**

`src/khata/static/manifest.webmanifest`:
```json
{
  "name": "Khata",
  "short_name": "Khata",
  "description": "Your money, your way — assets, loans, chits, holdings, retirement.",
  "start_url": "/app",
  "scope": "/",
  "display": "standalone",
  "orientation": "any",
  "background_color": "#F7F1E6",
  "theme_color": "#C05E1B",
  "icons": [
    { "src": "/static/assets/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any" },
    { "src": "/static/assets/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable" }
  ]
}
```

- [ ] **Step 3: Create the service worker**

`src/khata/static/sw.js`:
```javascript
// Khata PWA service worker. Network-first for HTML navigations and the API (data
// must always be fresh — HTML is no-store anyway); cache-first for versioned static
// assets so the shell loads instantly and survives a flaky connection.
const CACHE = 'khata-v1';
const STATIC = ['/static/assets/app.css', '/static/assets/ledger.css'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(STATIC)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (req.mode === 'navigate' || url.pathname.startsWith('/api/')) {
    e.respondWith(fetch(req).catch(() => caches.match(req)));
    return;
  }
  if (url.pathname.startsWith('/static/')) {
    e.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy));
        return res;
      }))
    );
  }
});
```

- [ ] **Step 4: Write the failing route tests**

`tests/test_pwa.py`:
```python
import json

import pytest

from khata import create_app
from khata.config import Config
from khata.db import Base


@pytest.fixture
def client():
    cfg = Config()
    cfg.database_url = "sqlite:///:memory:"
    app = create_app(cfg)
    app.config["TESTING"] = True
    Base.metadata.create_all(app.config["ENGINE"])
    return app.test_client()


def test_pwa_manifest_served(client):
    r = client.get("/manifest.webmanifest")
    assert r.status_code == 200
    assert r.mimetype == "application/manifest+json"
    data = json.loads(r.data)
    assert data["name"] == "Khata"
    assert data["start_url"] == "/app"
    assert data["display"] == "standalone"


def test_pwa_service_worker_served(client):
    r = client.get("/sw.js")
    assert r.status_code == 200
    assert "javascript" in r.mimetype
    assert r.headers.get("Cache-Control") == "no-store"
```

- [ ] **Step 5: Run the tests to verify they fail**

Run: `/Users/assistant/dev/active/khata/.venv/bin/python -m pytest tests/test_pwa.py -q`
Expected: FAIL — both routes 404 (`assert 404 == 200`).

- [ ] **Step 6: Add the Flask routes**

In `src/khata/web.py`, after the `analysis()` route (end of file), add:
```python


@bp.get("/manifest.webmanifest")
def manifest():
    return send_from_directory(_static_dir(), "manifest.webmanifest",
                               mimetype="application/manifest+json")


@bp.get("/sw.js")
def service_worker():
    # Served from / (not /static) so its scope covers the whole origin. no-store so a
    # new worker is picked up immediately on the owner's next visit.
    resp = send_from_directory(_static_dir(), "sw.js", mimetype="text/javascript")
    resp.headers["Cache-Control"] = "no-store"
    return resp
```

- [ ] **Step 7: Run the tests + full suite**

Run: `/Users/assistant/dev/active/khata/.venv/bin/python -m pytest tests/test_pwa.py -q`
Expected: PASS (2 passed).
Run: `/Users/assistant/dev/active/khata/.venv/bin/python -m pytest -q`
Expected: all pass (was 338; now 340).

- [ ] **Step 8: Commit**

```bash
git add src/khata/static/manifest.webmanifest src/khata/static/sw.js src/khata/static/assets/icons src/khata/web.py tests/test_pwa.py
git commit -m "feat(pwa): manifest + service worker + icons + Flask routes

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Inject PWA tags + register the service worker (nav.js)

**Files:**
- Modify: `src/khata/static/assets/nav.js`

`nav.js` is already loaded on every app page. Prepend a self-contained PWA init that runs
regardless of the nav drawer logic below it (which early-returns when `.app` is absent).

- [ ] **Step 1: Prepend the PWA init block**

At the very top of `src/khata/static/assets/nav.js` (before the existing
`// Responsive off-canvas sidebar.` comment and its IIFE), insert:
```javascript
// ── PWA: make Khata installable (manifest + apple meta + service worker) ──
// Runs on every app page; independent of the off-canvas nav IIFE below. Injecting
// these tags from JS is sufficient for Add-to-Home-Screen (iOS) and desktop install.
(function () {
  function add(tag, attrs) {
    var e = document.createElement(tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    document.head.appendChild(e);
  }
  add('link', { rel: 'manifest', href: '/manifest.webmanifest' });
  add('meta', { name: 'apple-mobile-web-app-capable', content: 'yes' });
  add('meta', { name: 'apple-mobile-web-app-status-bar-style', content: 'default' });
  add('meta', { name: 'apple-mobile-web-app-title', content: 'Khata' });
  add('meta', { name: 'theme-color', content: '#C05E1B' });
  add('link', { rel: 'apple-touch-icon', href: '/static/assets/icons/apple-touch-icon.png' });
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('/sw.js').catch(function () {});
    });
  }
})();

```

- [ ] **Step 2: Restart + verify headless**

```bash
bash /Users/assistant/dev/active/khata/run-app.sh
curl -s localhost:5057/manifest.webmanifest | python3 -c "import sys,json; d=json.load(sys.stdin); print('name',d['name'],'start',d['start_url'])"
curl -s localhost:5057/sw.js | grep -c "addEventListener('fetch'"
curl -s localhost:5057/static/assets/nav.js | grep -c "serviceWorker.register"
```
Expected: manifest name `Khata` start `/app`; sw fetch handler count 1; nav.js register count 1.
Then load `/app` in a browser, open DevTools → Application → Manifest shows "Khata", Service Workers shows `sw.js` activated, no console errors. On the Mac, Safari → File/Share offers "Add to Dock" / Chrome shows an install icon.

- [ ] **Step 3: Commit**

```bash
git add src/khata/static/assets/nav.js
git commit -m "feat(pwa): inject manifest + apple meta + register SW via nav.js

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Mobile app config — bundle id, tablet, orientation, prod API

**Files:**
- Modify: `mobile/app.json`, `mobile/src/config.ts`

- [ ] **Step 1: Set iOS bundle id + tablet support + orientation**

In `mobile/app.json`, change the `ios` block and `orientation`:
```json
    "orientation": "default",
    "ios": {
      "icon": "./assets/expo.icon",
      "bundleIdentifier": "com.npalakurla.khata",
      "supportsTablet": true
    },
```
(Replace the existing `"orientation": "portrait",` and the existing `"ios": { "icon": "./assets/expo.icon" },`.)

- [ ] **Step 2: Point the app at the prod API (with LAN override kept)**

Replace the body of `mobile/src/config.ts` with:
```typescript
/**
 * Runtime config. The API base URL is injected at build time via an
 * EXPO_PUBLIC_* env var (see .env.example). On a physical device "localhost"
 * is the phone, not your Mac, so dev must point at the Mac's LAN IP.
 */
const DEV_FALLBACK = 'http://192.168.50.189:5057'; // canonical Khata test instance (run-app.sh)
const PROD_DEFAULT = 'https://khata.npalakurla.com'; // public server (CORS * + bearer auth)

// EXPO_PUBLIC_API_BASE always wins. Otherwise: LAN box in dev, prod domain in a release build.
export const API_BASE = (
  process.env.EXPO_PUBLIC_API_BASE ?? (__DEV__ ? DEV_FALLBACK : PROD_DEFAULT)
).replace(/\/$/, '');
```

- [ ] **Step 3: Type-check**

```bash
cd mobile && npx tsc --noEmit
```
Expected: no errors. (If `tsc` is not resolvable, run `npm install` first.)

- [ ] **Step 4: Commit**

```bash
git add mobile/app.json mobile/src/config.ts
git commit -m "feat(mobile): iOS bundle id + iPad support + prod API base

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: iPad layout — cap content width in the shared Screen component

**Files:**
- Modify: `mobile/src/components/ui.tsx`

Every screen renders inside `<Screen>`. Capping its content width and centering it on wide
screens makes the whole app read well on iPad without touching individual screens. Phones
(width < 700) stay full-bleed exactly as today.

- [ ] **Step 1: Add `useWindowDimensions` to the React Native import**

In `mobile/src/components/ui.tsx`, add `useWindowDimensions` to the existing
`react-native` import (alphabetical, after `TextProps`/before `View` is fine):
```typescript
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TextInputProps,
  TextProps,
  useWindowDimensions,
  View,
  ViewProps,
} from 'react-native';
```

- [ ] **Step 2: Cap + center content in `Screen`**

Replace the entire `Screen` function with:
```typescript
export function Screen({
  children,
  scroll = true,
  refreshControl,
}: {
  children: ReactNode;
  scroll?: boolean;
  refreshControl?: React.ReactElement<any>;
}) {
  const { width } = useWindowDimensions();
  // iPad / wide windows: cap the content column at 720pt and centre it via horizontal
  // padding. Phones (width < 700) keep the standard 16pt gutter, unchanged.
  const padH = width >= 700 ? Math.max(spacing.lg, (width - 720) / 2) : spacing.lg;
  if (!scroll) {
    return (
      <SafeAreaView style={styles.screen} edges={['top']}>
        <View style={{ flex: 1, paddingHorizontal: padH }}>{children}</View>
      </SafeAreaView>
    );
  }
  return (
    <SafeAreaView style={styles.screen} edges={['top']}>
      <ScrollView
        contentContainerStyle={[styles.scrollBody, { paddingHorizontal: padH }]}
        refreshControl={refreshControl}
        keyboardShouldPersistTaps="handled"
      >
        {children}
      </ScrollView>
    </SafeAreaView>
  );
}
```
(`styles.scrollBody` keeps its `padding`/`gap`; the array's `paddingHorizontal` overrides only the left/right gutter. The non-scroll branch now wraps children in a padded `View`.)

- [ ] **Step 3: Type-check**

```bash
cd mobile && npx tsc --noEmit
```
Expected: no errors.

- [ ] **Step 4: Manual simulator check (owner or implementer if simulator available)**

```bash
cd mobile && npx expo start --ios
```
In the simulator switch between an iPhone and an iPad device. Expected: on iPhone, layout
unchanged (full-width cards, 16pt gutter). On iPad, content is centered in a ~720pt column,
not stretched edge-to-edge; no overflow; tab bar + scrolling work. If no simulator is
available in this environment, note that and rely on the type-check; the owner verifies on
device.

- [ ] **Step 5: Commit**

```bash
git add mobile/src/components/ui.tsx
git commit -m "feat(mobile): iPad-friendly content width cap in Screen

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Build runbook — Expo prebuild → Xcode archive → unsigned .ipa

**Files:**
- Create: `mobile/docs/build-ipa.md`
- Modify: `mobile/.gitignore` (ensure `ios/` ignored)

The generated `ios/` native project is **not** committed (large, churny, regenerated
deterministically from `app.json`). The runbook regenerates it on the owner's Mac.

- [ ] **Step 1: Ensure `ios/` is gitignored**

Check `mobile/.gitignore`. If it does not already contain `/ios` or `ios/`, append:
```
# Native projects are regenerated via `expo prebuild` (see docs/build-ipa.md)
/ios
/android
```
(Run `grep -nE "^/?(ios|android)" mobile/.gitignore` first; only add the lines that are missing.)

- [ ] **Step 2: Write the build runbook**

`mobile/docs/build-ipa.md`:
````markdown
# Build the Khata iOS app (unsigned .ipa for SideStore)

Free Apple ID — no paid Developer Program. We build the native project locally and export
an `.ipa` that SideStore re-signs at install. Do this on your Mac (Xcode required).

## One time / when native deps change

```bash
cd mobile
npm install
npx expo prebuild --platform ios --clean   # generates the ios/ Xcode project from app.json
```

This creates `mobile/ios/Khata.xcworkspace` (bundle id `com.npalakurla.khata`,
`supportsTablet` on). `ios/` is gitignored — that's expected.

## Archive in Xcode (GUI — primary route)

1. `open ios/Khata.xcworkspace`
2. In the target's **Signing & Capabilities**: tick *Automatically manage signing*, set
   **Team** to your **personal (free) Apple ID** team. Bundle id stays `com.npalakurla.khata`.
   - A free team shows "(Personal Team)" — this is correct; ignore "no paid membership".
3. Top device selector → **Any iOS Device (arm64)**.
4. **Product → Archive**. When the Organizer opens, select the archive →
   **Distribute App → Custom → Ad Hoc** (or **Development**) → **Export**.
   - Choose your personal team; let Xcode create the provisioning profile.
   - Export produces `Khata.ipa` in the chosen folder.

## Archive via CLI (alternative)

```bash
cd mobile/ios
xcodebuild -workspace Khata.xcworkspace -scheme Khata \
  -configuration Release -archivePath build/Khata.xcarchive archive
xcodebuild -exportArchive -archivePath build/Khata.xcarchive \
  -exportPath build/ipa -exportOptionsPlist ExportOptions.plist
```
`ExportOptions.plist` (create alongside, fill your 10-char Team ID):
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>method</key><string>development</string>
  <key>teamID</key><string>YOUR_TEAM_ID</string>
  <key>signingStyle</key><string>automatic</string>
  <key>compileBitcode</key><false/>
</dict></plist>
```
Output: `build/ipa/Khata.ipa`.

## Next

Install the `.ipa` with SideStore — see `sidestore-setup.md`. Free-account builds expire
after 7 days; SideStore re-signs over WiFi automatically.
````

- [ ] **Step 3: Commit**

```bash
git add mobile/docs/build-ipa.md mobile/.gitignore
git commit -m "docs(mobile): build runbook — prebuild + Xcode archive to unsigned .ipa

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: SideStore setup runbook

**Files:**
- Create: `mobile/docs/sidestore-setup.md`

- [ ] **Step 1: Write the SideStore runbook**

`mobile/docs/sidestore-setup.md`:
````markdown
# Install Khata via SideStore (free, weekly WiFi re-sign)

SideStore keeps a sideloaded app alive on a **free** Apple ID by re-signing it over WiFi
before the 7-day certificate expires — no cable, no computer after setup. This is the
"republish weekly over WiFi" mechanism.

## What you need

- iPhone / iPad on your home WiFi.
- A Mac (for the one-time pairing only).
- A free Apple ID (a throwaway one is fine; SideStore uses it only to sign).
- The `Khata.ipa` from `build-ipa.md`.

## Free-account limits (know these)

- Max **3** sideloaded apps installed at once.
- Max **10** app IDs registered per 7 days.
- The app **stops opening after 7 days** unless refreshed — SideStore automates the refresh.

## One-time setup (tethered, ~20 min)

1. **Pairing file.** On the Mac, generate a device pairing file with the current
   `jitterbugpair` tool (follow SideStore's official "Pairing File" guide for your OS/version).
   Output: `ALTPairingFile.mobiledevicepairing`.
2. **Anisette server.** SideStore needs an *anisette* source for Apple auth. Either:
   - Self-host (private): run the documented anisette Docker image on your Khata box —
     `docker run -d --restart=always --name anisette -p 6969:6969 <anisette-image>` — and
     point SideStore at `http://192.168.50.14:6969`; **or**
   - Use a public anisette server (simpler, less private) from SideStore's recommended list.
3. **Install SideStore** onto the device per its current official install guide (uses the
   pairing file + your Apple ID). Trust the developer profile in
   *Settings → General → VPN & Device Management*.

## Install Khata

1. AirDrop / host `Khata.ipa` where the device can reach it (e.g. served from the Khata box).
2. In SideStore → **+** → pick `Khata.ipa` → install (signs with your Apple ID).
3. Open Khata. Log in (bearer token stored in the secure store). It talks to
   `https://khata.npalakurla.com`.

## Weekly WiFi refresh

- In SideStore enable **Background Refresh** (and the SideStore "refresh in background"
  toggle). With the device on WiFi it re-signs Khata before the 7-day expiry — automatic.
- If you ever see "app expired": open SideStore on WiFi → **Refresh All**. Re-pair only if
  Apple auth breaks (rare; redo step 1).

## Fallback

If SideStore is down, the **PWA** still works: Safari → Share → *Add to Home Screen* on the
device, or use Khata in the browser. No expiry, no signing.
````

- [ ] **Step 2: Commit**

```bash
git add mobile/docs/sidestore-setup.md
git commit -m "docs(mobile): SideStore setup + weekly WiFi refresh runbook

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: AS-BUILT — distribution note + change-log

**Files:**
- Modify: `docs/specs/khata-AS-BUILT.md`

- [ ] **Step 1: Add a distribution note to the deployment/run section (§11)**

Find §11 (deployment / "Canonical local instance"). Add a bullet near the run/serve bullets:
```markdown
- **App distribution (personal, free):** Khata installs three ways without the App Store —
  (1) a **PWA** of the web app (`/manifest.webmanifest` + `/sw.js`, injected by `nav.js`):
  Mac "Add to Dock", iOS "Add to Home Screen"; (2) the **Expo native iOS app** (`mobile/`)
  sideloaded via **SideStore** on a free Apple ID, auto re-signed over WiFi every ≤7 days —
  see `mobile/docs/build-ipa.md` + `mobile/docs/sidestore-setup.md`; (3) the web app in any
  browser. The native app points at `https://khata.npalakurla.com` (bearer-token auth).
```

- [ ] **Step 2: Add a change-log entry (top of the list; do NOT edit existing dated entries)**

```markdown
- 2026-06-12 — Installable apps (free, no App Store). Added a PWA layer to the web app
  (`manifest.webmanifest` + `sw.js` served by Flask, tags + SW registered via `nav.js`) →
  installable on Mac and iOS home screen. Prepared the existing Expo app for SideStore
  sideloading on a free Apple ID: `ios.bundleIdentifier` (`com.npalakurla.khata`),
  `supportsTablet`, `orientation: default`, prod `API_BASE`, and an iPad content-width cap
  in the shared `Screen` component. Two runbooks (`mobile/docs/build-ipa.md`,
  `sidestore-setup.md`) cover the owner-run build + install + weekly WiFi re-sign. Native
  OTA (`expo-updates`) is documented as future work, not built.
```

- [ ] **Step 3: Commit**

```bash
git add docs/specs/khata-AS-BUILT.md
git commit -m "docs(as-built): app distribution (PWA + SideStore native) + change-log

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Notes for the executor

- **Stage files explicitly** — never `git add -A` (the repo keeps many intentionally-untracked
  files: `.env*`, `khata_*.db*`, `.claude/`, `CLAUDE.md`, `run-app.sh`, `responsive-dashboard.html`).
- **Never wipe `khata_app.db`.**
- **K4** — `sw.js` and `nav.js` build DOM/strings without `innerHTML` on API data.
- Tasks 5 & 6 are **runbooks you author, not execute** — the device/Apple-ID steps are the
  owner's. Deliver them correct and complete; don't attempt the install here.
- Mobile tasks verify via `npx tsc --noEmit` (and the simulator if available); there is no RN
  unit-test harness in the repo.
- The `run-app.sh` instance serves this worktree; Python edits (Task 1 routes) need a restart,
  static edits (Task 2) are live on reload.
```
