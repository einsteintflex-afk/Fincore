# FinCore on Android, iPhone, Windows, macOS and the web

One React app (`frontend/`), one backend. The packaged apps are thin shells around the same web build:

| Platform | Shell | Project | Status (2026-11-18) |
|---|---|---|---|
| Web (Chrome, Edge, Firefox, Safari, mobile browsers) | — | `frontend/` | Built and browser-tested (Chromium desktop + phone width) |
| Android | Capacitor 8.6.2 | `frontend/android/` | **Built**: signed release APK and AAB |
| iPhone / iOS | Capacitor 8.6.2 | `frontend/ios/` | Xcode project generated; **not built** (needs a Mac with Xcode + Apple Developer account) |
| Windows | Tauri 2 | `frontend/src-tauri/` | **Built**: NSIS installer `FinCore_1.0.0_x64-setup.exe` (cross-compiled from Linux, unsigned, not yet run on Windows) |
| macOS | Tauri 2 | `frontend/src-tauri/` | Configured (`app`, `dmg` targets); **not built** (needs a Mac) |
| Linux (bonus check) | Tauri 2 | `frontend/src-tauri/` | Built `.deb`; launched and signed in against the API — the dashboard loaded live data |

## How the apps reach the backend

* All platforms call the same FinCore API. Balances, transactions, users and settings live only on the server, so a
  withdrawal made on the phone appears immediately on the desktop and the web.
* The packaged apps ask for the **server address** on the sign-in screen (stored on the device; not a secret).
  Bake one in at build time with `VITE_SERVER_URL=https://fincore.example.com npm run build`. Only `https://`
  addresses are accepted (plus `localhost`/`10.0.2.2` for development).
* Tokens: the access token is kept in memory. The web app's refresh token is an HttpOnly cookie. The packaged
  apps receive the refresh token in the response body and keep it **in memory only** — it is never written to
  disk, so closing the app signs out and a lost device holds no usable credential.
* No MTN or other provider credentials exist in any app — they are only on the server. (Checked: the APK's
  JavaScript contains no key material.)
* The API allows the apps' origins in CORS: `capacitor://localhost`, `https://localhost` (Android),
  `tauri://localhost`, `http://tauri.localhost`. Add your production web origin with `FINCORE_CORS_ORIGINS`.

## Android

Requirements: JDK 21, Android SDK (platform 36, build-tools 36), Node 20+.

```bash
cd frontend
npm ci
VITE_SERVER_URL=https://fincore.example.com npm run build      # optional server default
npx cap sync android
cd android
export ANDROID_HOME=/path/to/android-sdk
export FINCORE_ANDROID_KEYSTORE_PROPERTIES=/secure/place/keystore.properties
./gradlew assembleRelease bundleRelease
# app/build/outputs/apk/release/app-release.apk     (install directly)
# app/build/outputs/bundle/release/app-release.aab  (upload to Google Play)
```

`keystore.properties` (keep it and the `.jks` **outside the repository** and backed up — losing the upload key
means you cannot update the app):

```
storeFile=/secure/place/fincore-upload.jks
storePassword=...
keyAlias=fincore
keyPassword=...
```
Create a key with
`keytool -genkeypair -keystore fincore-upload.jks -alias fincore -keyalg RSA -keysize 4096 -validity 10000`.
The build in this session used a key generated in the development container (`/home/user/fincore-signing/`, not in
git). For Google Play, enrol in Play App Signing and keep your own upload key safe; generate a new one on your own
computer for production rather than reusing the container's.

Manifest: `INTERNET` permission only, `allowBackup=false` (no app data in cloud backups), cleartext traffic off.
To install the APK on a phone: enable "Install unknown apps" for your file manager/browser and open the file.

## iPhone / iOS (needs a Mac)

```bash
cd frontend && npm ci && npm run build && npx cap sync ios
npx cap open ios          # opens ios/App/App.xcworkspace in Xcode
```
In Xcode: select the **App** target → Signing & Capabilities → choose your Apple Developer team (paid account,
USD 99/year) and a unique bundle id (default `com.fincore.app`). Then Product → Archive → Distribute App
(TestFlight / App Store, or Ad Hoc for registered devices). Required from you: Apple Developer Program membership,
a Mac with current Xcode, and App Store Connect app record (privacy details: the app stores no personal data on
the device). Icons and splash screens are already generated (`scripts/make-icons.py`).

## Windows

Built here by cross-compiling (Linux → Windows):

```bash
rustup target add x86_64-pc-windows-msvc
cargo install --locked cargo-xwin           # downloads the MSVC CRT/SDK headers on first use
sudo apt-get install nsis lld llvm clang
cd frontend && npx tauri build --runner cargo-xwin --target x86_64-pc-windows-msvc --bundles nsis
# src-tauri/target/x86_64-pc-windows-msvc/release/bundle/nsis/FinCore_1.0.0_x64-setup.exe
```
Or on a Windows PC (Rust + Node + WebView2, which Windows 10/11 already have): `npx tauri build` (also produces an
`.msi`). The installer is **unsigned**, so Windows SmartScreen will warn ("More info → Run anyway"). For a trusted
installer buy a code-signing certificate (OV/EV) and set `bundle.windows.certificateThumbprint` or a `signCommand`.
The window is resizable (minimum 900×600).

## macOS (needs a Mac)

```bash
cd frontend && npm ci && npx tauri build --bundles app,dmg
# src-tauri/target/release/bundle/dmg/FinCore_1.0.0_*.dmg
```
For distribution outside the App Store: an Apple Developer ID Application certificate, then sign and notarize
(set `APPLE_SIGNING_IDENTITY`, `APPLE_ID`, `APPLE_PASSWORD`/`APPLE_API_KEY`, `APPLE_TEAM_ID` before
`tauri build`). Unsigned builds open only via right-click → Open.

## Updating the apps

Change the React code → `npm run build` → `npx cap sync` (mobile) or `npx tauri build` (desktop). Increase
`versionCode`/`versionName` in `android/app/build.gradle` and `version` in `src-tauri/tauri.conf.json` for each
release.
