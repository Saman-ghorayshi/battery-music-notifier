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
        startForeground(Notifications.ARMED_NOTIFICATION_ID, Notifications.armedNotification(this))
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
            while (watching && prefs.armed) {
                val state = try { prefs.newClient().poll() } catch (_: Exception) { null }
                if (state != null && !state.armed) {
                    // Account disarmed remotely while the app was closed:
                    // the watcher's job is over, shut the service down.
                    watching = false
                    silence()
                    Notifications.cancelThiefAlert(this@ArmService)
                    stopForeground(STOP_FOREGROUND_REMOVE)
                    stopSelf()
                    break
                }
                if (state != null && state.alertActive && state.alertType == "THIEF_ALERT") {
                    if (!ringing) {
                        ringing = true
                        SirenPlayer.start(this)
                        Notifications.showThiefAlert(this)
                    }
                } else if (ringing && state != null && !state.alertActive) {
                    // Owner cleared it from another device
                    ringing = false
                    SirenPlayer.stop()
                    Notifications.cancelThiefAlert(this)
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

        @Volatile private var watching = false
        @Volatile var ringing = false
            private set

        /** Called by the Silence notification action and on disarm. */
        fun silence() {
            ringing = false
            SirenPlayer.stop()
        }
    }
}
