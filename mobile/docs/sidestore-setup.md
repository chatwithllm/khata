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
