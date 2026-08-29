package com.saman.batterymusic

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat

/** One place for the notification channel + the armed-charging notification. */
object Notifications {

    const val CHANNEL_ARMED = "armed"
    const val CHANNEL_ALERT = "alert"
    const val ARMED_NOTIFICATION_ID = 1

    fun createChannels(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(
                CHANNEL_ARMED, "Armed status",
                NotificationManager.IMPORTANCE_LOW,
            ).apply { description = "Persistent notice while thief alarm is armed" }
        )
        manager.createNotificationChannel(
            NotificationChannel(
                CHANNEL_ALERT, "Thief alerts",
                NotificationManager.IMPORTANCE_HIGH,
            ).apply { description = "Fires when a thief alert arrives" }
        )
    }

    /** The persistent notification that keeps [ArmService] in the foreground. */
    fun armedNotification(context: Context): android.app.Notification {
        val open = PendingIntent.getActivity(
            context, 0,
            Intent(context, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        return NotificationCompat.Builder(context, CHANNEL_ARMED)
            .setSmallIcon(android.R.drawable.ic_lock_idle_lock)
            .setContentTitle("Thief alarm armed")
            .setContentText("Watching for charger unplug")
            .setOngoing(true)
            .setContentIntent(open)
            .build()
    }
}
