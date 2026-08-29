package com.saman.batterymusic

import android.app.Service
import android.content.Intent
import android.os.IBinder

/**
 * Foreground service (dataSync) that exists only while the alarm is armed:
 * it pins the process with the persistent notification so Doze and battery
 * savers leave us alone, and cancels it on disarm.
 */
class ArmService : Service() {

    override fun onCreate() {
        super.onCreate()
        Notifications.createChannels(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_DISARM) {
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
            return START_NOT_STICKY
        }
        startForeground(Notifications.ARMED_NOTIFICATION_ID, Notifications.armedNotification(this))
        // Not START_STICKY: if the system kills us the armed flag survives in
        // Prefs and the next unplug still fires PowerReceiver -> ThiefWorker.
        return START_NOT_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        const val ACTION_DISARM = "com.saman.batterymusic.DISARM"
    }
}
