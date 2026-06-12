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
