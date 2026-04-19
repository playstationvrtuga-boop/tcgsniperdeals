# TCG Sniper Deals Mobile Wrapper

This folder contains the **Capacitor wrapper** for the existing Flask + PWA app.

Path:

`C:\Users\Trabalho\Desktop\bot_pokemon\vip_app_mobile`

## What was chosen and why

The existing app is a **dynamic Flask app** with:

- login
- VIP feed
- favorites
- profile
- admin
- payments
- database-backed listings

Because of that, the simplest robust mobile path is:

- **keep the existing Flask app**
- **wrap it with Capacitor**
- **open the existing app by URL inside Android/iPhone native shells**

This avoids rebuilding the product in Flutter or React Native.

## Important idea

The mobile wrapper does **not** replace the Flask app.

The Flask app still needs to be available at a URL.

The wrapper reads that URL from:

`C:\Users\Trabalho\Desktop\bot_pokemon\vip_app\.env`

Priority:

1. `MOBILE_APP_URL`
2. `CAP_SERVER_URL`
3. `SITE_URL`

## Good URL examples

### Browser on the same Windows PC

```env
MOBILE_APP_URL=http://127.0.0.1:5000
```

### Android emulator

```env
MOBILE_APP_URL=http://10.0.2.2:5000
```

### Physical Android / iPhone on the same Wi-Fi

Use your PC LAN IP:

```env
MOBILE_APP_URL=http://192.168.1.50:5000
```

For this to work, run Flask on all interfaces:

```powershell
python vip_app\manage.py run --host 0.0.0.0 --port 5000
```

### Real production / distribution

Use a public HTTPS URL:

```env
MOBILE_APP_URL=https://your-domain.com
```

This is the recommended setup for:

- iPhone testing
- TestFlight
- stable Android sharing

## Files that matter

- Capacitor package:
  - [C:\Users\Trabalho\Desktop\bot_pokemon\vip_app_mobile\package.json](C:\Users\Trabalho\Desktop\bot_pokemon\vip_app_mobile\package.json)
- Capacitor config generator:
  - [C:\Users\Trabalho\Desktop\bot_pokemon\vip_app_mobile\scripts\sync-capacitor-config.mjs](C:\Users\Trabalho\Desktop\bot_pokemon\vip_app_mobile\scripts\sync-capacitor-config.mjs)
- Generated Capacitor config:
  - [C:\Users\Trabalho\Desktop\bot_pokemon\vip_app_mobile\capacitor.config.json](C:\Users\Trabalho\Desktop\bot_pokemon\vip_app_mobile\capacitor.config.json)
- Android project:
  - [C:\Users\Trabalho\Desktop\bot_pokemon\vip_app_mobile\android](C:\Users\Trabalho\Desktop\bot_pokemon\vip_app_mobile\android)
- iOS project:
  - [C:\Users\Trabalho\Desktop\bot_pokemon\vip_app_mobile\ios](C:\Users\Trabalho\Desktop\bot_pokemon\vip_app_mobile\ios)
- Branding source assets:
  - [C:\Users\Trabalho\Desktop\bot_pokemon\vip_app_mobile\resources\icon.png](C:\Users\Trabalho\Desktop\bot_pokemon\vip_app_mobile\resources\icon.png)
  - [C:\Users\Trabalho\Desktop\bot_pokemon\vip_app_mobile\resources\splash.png](C:\Users\Trabalho\Desktop\bot_pokemon\vip_app_mobile\resources\splash.png)

## What was already prepared

- Capacitor installed
- Android project generated
- iOS project generated
- app icon and splash generated for both platforms
- wrapper config reads the existing Flask app URL
- native-safe CSS / viewport-fit / status-bar-safe layout added to the Flask app
- service worker is skipped inside the native shell so it does not fight the webview

## Exact commands

Run these from:

`C:\Users\Trabalho\Desktop\bot_pokemon\vip_app_mobile`

### 1) Install dependencies

```powershell
npm.cmd install
```

### 2) Sync the wrapper config with the current Flask URL

```powershell
npm.cmd run sync:config
```

### 3) Regenerate mobile icons and splash if you change branding later

```powershell
npm.cmd run assets:generate
```

### 4) Sync everything into Android / iOS

```powershell
npm.cmd run cap:sync
```

## Android path

### Open the Android project

```powershell
npm.cmd run android:open
```

This opens the project in Android Studio.

### Build a test APK

In Android Studio:

1. wait for Gradle sync
2. choose:
   - **Build**
   - **Build Bundle(s) / APK(s)**
   - **Build APK(s)**

Expected debug APK output:

`C:\Users\Trabalho\Desktop\bot_pokemon\vip_app_mobile\android\app\build\outputs\apk\debug\app-debug.apk`

### Current status on this machine

The Android project is ready, but **APK build is not complete yet on this PC** because Java is not configured.

The exact blocker found here:

- `JAVA_HOME is not set`
- no `java` found in `PATH`

### What remains manual for Android

Install and configure:

- Android Studio
- Android SDK
- Java JDK

Then the APK build path above becomes usable.

## iPhone / iOS path

### Open the iOS project

```powershell
npm.cmd run ios:open
```

On Windows, this will prepare the project files, but **real iOS building still needs macOS with Xcode**.

Main iOS project folder:

`C:\Users\Trabalho\Desktop\bot_pokemon\vip_app_mobile\ios\App`

### Realistic iPhone testing path

For iPhone, the standard practical path is:

1. move the project to a Mac
2. open the iOS project in Xcode
3. use an Apple account / team
4. run on a real device
5. for easier tester distribution, use **TestFlight**

### Important iPhone note

For iPhone testing and TestFlight, the wrapped app should point to a **public HTTPS URL**.

`http://127.0.0.1:5000` is not a realistic iPhone distribution URL.

## How to test the wrapper locally

### Browser / local desktop

Run the app:

```powershell
python vip_app\manage.py run
```

Then the wrapper can point to:

```env
MOBILE_APP_URL=http://127.0.0.1:5000
```

### Physical phone on same Wi-Fi

1. find your PC LAN IP
2. set:

```env
MOBILE_APP_URL=http://YOUR-PC-LAN-IP:5000
```

3. run Flask so the phone can reach it:

```powershell
python vip_app\manage.py run --host 0.0.0.0 --port 5000
```

4. run:

```powershell
npm.cmd run sync:config
npm.cmd run cap:sync
```

5. open Android Studio / Xcode and run the wrapper

## Push notifications in wrapped apps

The current push implementation in the Flask app is **web push for the PWA/browser flow**.

That is different from native mobile push.

So:

- PWA push already exists
- native Android/iPhone push inside the Capacitor apps is **not fully implemented yet**

That future step would require:

- Firebase Cloud Messaging for Android
- Apple Push Notification setup for iPhone
- native push plugin integration

## What remains manual

- choosing the final mobile URL for the wrapper
- setting `MOBILE_APP_URL` in `vip_app\.env`
- installing Android Studio / JDK on Windows
- building the APK in Android Studio
- moving the iOS project to macOS for Xcode
- Apple account / signing / TestFlight for iPhone

## Short version

You now have:

- a real Capacitor wrapper
- Android project generated
- iOS project generated
- branding assets applied
- a clean path to Android APK testing
- a realistic path to iPhone testing through Xcode / TestFlight
