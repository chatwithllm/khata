# Khata iPhone App — Setup Guide

How to get the Khata mobile app running on a physical iPhone from a clean Mac.
There are **two ways**. Pick one:

- **Path A — Expo Go (fastest, no Xcode).** App runs inside the free Expo Go
  app. Best for development and trying it out. ~15 min.
- **Path B — Xcode (standalone app).** Builds a real `.app` with its own icon,
  installed straight onto the iPhone. Needs full Xcode. ~1–2 hrs first time
  (mostly the Xcode download).

You only need Path B if you want the app installed standalone (no Expo Go).

---

## 0. Prerequisites (both paths)

### macOS
- A Mac (Apple Silicon or Intel) on macOS.
- An **Apple ID** (free is fine for installing on your own device).

### Install Homebrew (package manager)
If `brew --version` fails, install it:
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```
Then follow the on-screen "Next steps" to add brew to your PATH.

### Install Node.js (v20 or newer) + Git + Watchman
```bash
brew install node git watchman
```
Verify:
```bash
node -v        # should print v20+ (this app was built on v26)
npm -v
git --version
```

### Get the code
```bash
git clone https://github.com/chatwithllm/khata.git
cd khata
git checkout main          # mobile app is on main
```

### Install JS dependencies
```bash
cd mobile
npm install
```

### Configure the API URL
The app talks to the Khata backend over your LAN. Find the Mac's IP:
```bash
ipconfig getifaddr en0     # e.g. 192.168.50.189
```
Create the env file:
```bash
cp .env.example .env
```
Open `.env` and set the IP to **your Mac's IP** (port stays 5057):
```
EXPO_PUBLIC_API_BASE=http://YOUR.MAC.IP.HERE:5057
```

### Run the backend (needed for login/data)
In a **separate terminal**, from the repo root:
```bash
cd khata
python3 -m venv .venv                          # first time only
.venv/bin/pip install -r requirements.txt       # first time only (installs Flask etc.)
PYTHONPATH=src KHATA_DATABASE_URL="sqlite:///$PWD/khata_app.db" \
  .venv/bin/python -c "from khata import create_app; create_app().run(host='0.0.0.0', port=5057)"
```
Leave it running. The phone and Mac must be on the **same Wi-Fi**.

---

## Path A — Run in Expo Go (no Xcode)

1. On the iPhone, install **Expo Go** from the App Store.
2. On the Mac, from `mobile/`:
   ```bash
   npx expo start
   ```
3. A QR code appears in the terminal.
   - **iPhone:** open the **Camera** app, point at the QR, tap the banner — it
     opens in Expo Go.
   - Or in Expo Go tap "Enter URL manually" and type `exp://YOUR.MAC.IP:8081`.
4. The app loads → register or sign in. Done.

Hot reload is on: edit code, the app refreshes.

---

## Path B — Build with Xcode (standalone app)

### B1. Install full Xcode
1. Open the **App Store** → search **Xcode** → install (~7 GB, slow).
2. After it finishes, point the command-line tools at it and accept the license:
   ```bash
   sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
   sudo xcodebuild -license accept
   ```
3. Open Xcode once so it installs its extra components, then quit it.

### B2. Install CocoaPods
```bash
brew install cocoapods
pod --version      # confirm it works
```

### B3. Generate + install native dependencies
From `mobile/`:
```bash
npx expo prebuild --platform ios      # regenerates ios/ (safe to re-run)
cd ios
pod install                            # creates Khata.xcworkspace
```

### B4. Open in Xcode and run
```bash
open Khata.xcworkspace                  # IMPORTANT: .xcworkspace, NOT .xcodeproj
```
In Xcode:
1. Plug the iPhone into the Mac with a cable. Tap **Trust** on the phone.
2. In the top toolbar, set the **scheme to "Khata"** and the **destination to
   your iPhone**.
3. In the left sidebar click the blue **Khata** project → select the **Khata**
   target → **Signing & Capabilities** tab.
4. **Team:** click the dropdown → **Add an Account…** → sign in with your Apple
   ID. Then pick your name as the Team. Make sure **Automatically manage
   signing** is checked.
   - If you see a "bundle identifier is not available" error, change
     **Bundle Identifier** to something unique, e.g. `com.YOURNAME.khata`.
5. Press the **▶ Run** button (or ⌘R). Xcode builds and installs to the phone.
6. First launch the phone will block it. On the iPhone:
   **Settings → General → VPN & Device Management → (your Apple ID) → Trust**.
7. Reopen the app from the home screen.

### One-command alternative
After B1 + B2 are done, this does prebuild + pod install + build + install in one step:
```bash
cd mobile
npx expo run:ios --device
```

---

## Notes & gotchas

- **Free Apple ID:** the app runs for **7 days**, then re-run from Xcode to
  renew. A paid **Apple Developer account ($99/yr)** removes that limit and is
  required for the App Store.
- **"Cannot connect to server" in the app:** the backend isn't running, the
  `.env` IP is wrong, or phone/Mac are on different Wi-Fi. Re-check section 0.
- **Changed `.env`?** Restart `expo start` (Path A) or rebuild (Path B) — the
  API URL is baked in at bundle time.
- **Google sign-in** is hidden unless OAuth client IDs are set
  (`EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID` etc. in `.env`). Email/password works
  without any of that.
- **Don't hand-edit `ios/`** — it's generated. Re-run `npx expo prebuild` to
  regenerate from `app.json`.

## Quick command reference

| Task | Command (from `mobile/`) |
| --- | --- |
| Install JS deps | `npm install` |
| Run in Expo Go | `npx expo start` |
| Type-check | `npx tsc --noEmit` |
| Regenerate native project | `npx expo prebuild --platform ios` |
| Install pods | `cd ios && pod install` |
| Open in Xcode | `open ios/Khata.xcworkspace` |
| Build + install to device | `npx expo run:ios --device` |
