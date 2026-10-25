# GATE Prep Android wrapper (development build)

This Android Studio/Gradle project bundles the current Flask + SQLite app with Chaquopy Python and opens it in an Android WebView. SQLite data is stored in the app's private files directory and should survive app restarts. The server binds only to 127.0.0.1.

## Important status
- This is a build project, **not a compiled APK**.
- It has not been built or run on a real Android device yet.
- It needs a successful Gradle/Chaquopy build and runtime verification before use for real study data.
- The AI assistant still requires internet and a compatible API key configured in the app's server environment; this wrapper does not yet provide a safe in-app API-key settings bridge.
- WebView and embedded server lifecycle need device testing, especially Android process suspension/restart.

## Build APK with GitHub Actions from a phone
1. Create a new GitHub repository and upload all files in this project (including `.github/workflows/build-apk.yml`).
2. Open the repository's **Actions** tab and allow workflows if prompted.
3. Select **Build GATE Prep APK** → **Run workflow**.
4. After the run completes, open its summary and download the `gate-prep-debug-apk` artifact.
5. Extract the artifact ZIP to obtain `app-debug.apk`; install only after build succeeds and inspect Android warnings.

The workflow produces a debug APK, not a Play Store release-signed APK. Do not use it as a trusted production release until tests pass.
