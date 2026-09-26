package com.saman.batterymusic

import android.app.Service
import android.content.Intent
import android.os.IBinder
import kotlin.concurrent.thread

/**
 * Foreground service (dataSync) that exists only while the alarm is armed:
 * it pins the process with the persistent notification so Doze and battery
 * savers leave us alone, and -- since v2.2 -- it WATCHES the relay while
 * armed: a THIEF_ALERT raised anywhere on the account (laptop intruder
 * guard, another device) lands here in ~4s with a heads-up notification
 * and the local siren. This is the phone-side counterpart of the laptop's
 * relay listener; it only burns battery while armed.
 */
class ArmService : Service() {

    override fun onCreate() {
        super.onCreate()
        Notifications.createChannels(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_DISARM) {
            watching = false
            silence()
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
            return START_NOT_STICKY
        }
        if (android.os.Build.VERSION.SDK_INT >= 29) {
            startForeground(
                Notifications.ARMED_NOTIFICATION_ID, Notifications.armedNotification(this),
                android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC or
                    android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA,
            )
        } else {
            @Suppress("DEPRECATION")
            startForeground(Notifications.ARMED_NOTIFICATION_ID, Notifications.armedNotification(this))
        }
        startWatching()
        // Not START_STICKY: if the system kills us the armed flag survives in
        // Prefs and the next unplug still fires PowerReceiver -> ThiefWorker.
        return START_NOT_STICKY
    }

    private fun startWatching() {
        if (watching) return
        watching = true
        val prefs = Prefs.get(this)
        thread(name = "relay-watch") {

        // ── Thief selfie ────────────────────────────────────────────────
        // The alarm ringing means someone may be holding this phone. One
        // front-camera frame, uploaded to the owner's own relay account so
        // it shows up next to the alert. Camera permission is asked once,
        // up front, with the explanation; without it this silently skips.
        val selfieTakenFor = java.util.concurrent.atomic.AtomicLong(0L)
        fun takeThiefSelfie(alertTs: Long) {
            if (selfieTakenFor.get() == alertTs) return
            selfieTakenFor.set(alertTs)
            val granted = androidx.core.content.ContextCompat.checkSelfPermission(
                this, android.Manifest.permission.CAMERA,
            ) == android.content.pm.PackageManager.PERMISSION_GRANTED
            if (!granted) return
            ThiefCamera.captureSelfie(this) { bytes ->
                if (bytes != null) {
                    try { prefs.newClient().uploadSnapshot(bytes) } catch (_: Exception) {}
                }
            }
        }
        // ────────────────────────────────────────────────────────────────

            // Dead-man bookkeeping: when the other device was last FRESH and
            // what it calls itself, so a laptop that stops checking in while
            // armed raises "LAPTOP WENT SILENT" exactly once per silence
            // episode and stands down the moment the heartbeat returns.
            var lastFreshSeen = 0L
            var otherName: String? = null
            while (watching && prefs.armed) {
                val state = try { prefs.newClient().poll() } catch (_: Exception) { null }
                if (state != null && !state.armed) {
                    // Account disarmed remotely while the app was closed:
                    // the watcher's job is over, shut the service down.
                    watching = false
                    silence()
                    Notifications.cancelThiefAlert(this@ArmService)
                    Notifications.cancelOtherSilent(this@ArmService)
                    stopForeground(STOP_FOREGROUND_REMOVE)
                    stopSelf()
                    break
                }

                // A silence request (notification action / dashboard) stops
                // the sound and mutes the CURRENT episodes: THIEF until its
                // alert_ts changes, dead-man until the heartbeat returns.
                // Without the mute memory the siren simply re-rang on the
                // very next poll tick.
                if (muteRequested) {
                    muteRequested = false
                    if (state != null) thiefMutedForTs = state.alertTs
                    deadmanMuted = true
                    thiefRinging = false
                    deadmanRinging = false
                    ringing = false
                    SirenPlayer.stop()
                    Notifications.cancelThiefAlert(this@ArmService)
                    Notifications.cancelOtherSilent(this@ArmService)
                }

                // ---- THIEF episode: raised anywhere on the account ----
                val wantThief = state != null && state.alertActive &&
                    state.alertType == "THIEF_ALERT" && state.alertTs != thiefMutedForTs
                if (wantThief && !thiefRinging) {
                    thiefRinging = true
                    if (!deadmanRinging) {
                        ringing = true
                        SirenPlayer.start(this)
                    }
                    takeThiefSelfie(state?.alertTs ?: 0L)
                    Notifications.showThiefAlert(this)
                } else if (!wantThief && thiefRinging) {
                    thiefRinging = false
                    Notifications.cancelThiefAlert(this)
                    if (!deadmanRinging) {
                        ringing = false
                        SirenPlayer.stop()
                    }
                }

                // ---- Dead-man's switch: the other device went silent ----
                val other = state?.otherDevices?.firstOrNull { it.lastSeen > 0 }
                val nowSec = System.currentTimeMillis() / 1000
                if (other != null) {
                    val age = nowSec - other.lastSeen
                    if (age in 0..DEADMAN_FRESH_AGE) {
                        lastFreshSeen = nowSec
                        if (!other.name.isNullOrEmpty()) otherName = other.name
                        if (deadmanRinging || otherSilent) {
                            // Heartbeat returned: stand the dead-man down.
                            deadmanRinging = false
                            otherSilent = false
                            deadmanMuted = false
                            if (!thiefRinging) {
                                ringing = false
                                SirenPlayer.stop()
                            }
                            Notifications.cancelOtherSilent(this@ArmService)
                        }
                    } else if (!deadmanRinging && !deadmanMuted &&
                        lastFreshSeen > 0 && age > DEADMAN_STALE_SEC &&
                        (nowSec - lastFreshSeen) < DEADMAN_FRESH_WINDOW
                    ) {
                        // Was watched alive, then went dark: not a laptop
                        // that never runs the app -- a guard that vanished.
                        deadmanRinging = true
                        otherSilent = true
                        otherSilentSince = other.lastSeen
                        otherSilentName = otherName ?: other.name
                        takeThiefSelfie(0L - other.lastSeen)
                        if (!thiefRinging) {
                            ringing = true
                            SirenPlayer.start(this)
                        }
                        Notifications.showOtherSilent(this, otherSilentName ?: "Your laptop")
                    }
                }
                try { Thread.sleep(POLL_MS) } catch (_: InterruptedException) { break }
            }
            watching = false
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        const val ACTION_DISARM = "com.saman.batterymusic.DISARM"
        const val POLL_MS = 4_000L

        // Heartbeat freshness bands, in seconds. Between 60 and 90 nothing
        // changes (clock jitter guard); past 90 with a recent fresh sighting
        // the dead-man fires.
        const val DEADMAN_FRESH_AGE = 60L
        const val DEADMAN_STALE_SEC = 90L
        const val DEADMAN_FRESH_WINDOW = 600L

        @Volatile private var watching = false

        /** Siren audible right now (either cause). */
        @Volatile var ringing = false
            private set
        @Volatile var thiefRinging = false
            private set
        @Volatile var deadmanRinging = false
            private set

        /** Dead-man condition active (stale heartbeat), even after silencing. */
        @Volatile var otherSilent = false
            private set
        @Volatile var otherSilentName: String? = null
            private set
        @Volatile var otherSilentSince = 0L
            private set

        @Volatile private var muteRequested = false
        @Volatile private var thiefMutedForTs = 0L
        @Volatile private var deadmanMuted = false

        /** Stop the siren now and mute the current episodes. */
        fun silence() {
            muteRequested = true
        }
    }
}
