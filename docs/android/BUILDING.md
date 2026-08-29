# Building the Android app from Iran

GitHub Actions builds the debug APK on every push to `v2.1*`/`master`
(artifact `battery-music-notifier-debug`), so building locally is optional.
When you do build locally, Gradle needs to reach Google's Maven and
services.gradle.org, both of which are unreliable from Iran. Two fixes,
in order of preference:

## 1. Maven mirrors, no proxy needed

Uncomment the mirror lines in `android/settings.gradle.kts`
(`maven.aliyun.com` google/public + the Tencent mirror) and comment out the
plain `google()` / `mavenCentral()` lines. The Aliyun mirrors are reachable
directly from Iran.

Also swap the Gradle distribution itself in `gradle/wrapper/gradle-wrapper.properties`:

```
distributionUrl=https\://maven.aliyun.com/repository/gradle-plugin/gradle-8.7-bin.zip
```

(Any mirror of `services.gradle.org/distributions/gradle-8.7-bin.zip` works.)

## 2. Local proxy (v2rayN and friends)

Gradle's SOCKS support is flaky -- prefer the **http** inbound:

```properties
# android/gradle.properties (already stubbed, uncomment)
systemProp.http.proxyHost=127.0.0.1
systemProp.http.proxyPort=10809
systemProp.https.proxyHost=127.0.0.1
systemProp.https.proxyPort=10809
```

In Android Studio: Settings -> Appearance & Behavior -> System Settings ->
HTTP Proxy -> Manual -> `127.0.0.1:10809`.

## Build

```
cd android
./gradlew assembleDebug        # Windows: gradlew.bat assembleDebug
./gradlew testDebugUnitTest    # JVM-only tests, no emulator needed
```

APK lands in `app/build/outputs/apk/debug/app-debug.apk`. Debug-signed on
purpose for the v2.1 alpha; sideload it (Settings -> install unknown apps).

## End-to-end test without an emulator (PhoneSim)

`android/tools/PhoneSim.kt` runs the app's real `ApiClient.kt` on the JVM
against the live worker -- pair with a code from `battery-music pair`,
send a test alert, watch polls, fetch snapshots. See the header comment in
that file for the exact commands.
