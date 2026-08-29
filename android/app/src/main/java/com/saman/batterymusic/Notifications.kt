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

    /** Heads-up + siren companion when a THIEF_ALERT arrives from the relay. */
    fun showThiefAlert(context: Context) {
        createChannels(context)
        val silence = PendingIntent.getBroadcast(
            context, 1,
            Intent(context, AlertActionReceiver::class.java).setAction(ACTION_SILENCE),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val open = PendingIntent.getActivity(
            context, 0,
            Intent(context, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val notification = NotificationCompat.Builder(context, CHANNEL_ALERT)
            .setSmallIcon(android.R.drawable.ic_dialog_alert)
            .setContentTitle("THIEF ALERT")
            .setContentText("Charger pulled or intruder at your device!")
            .setPriority(NotificationCompat.PRIORITY_MAX)
            .setCategory(NotificationCompat.CATEGORY_ALARM)
            .setOngoing(true) // can't swipe away a thief; use Silence
            .addAction(0, "Silence", silence)
            .setContentIntent(open)
            .build()
        getManager(context).notify(THIEF_ALERT_NOTIFICATION_ID, notification)
    }

    fun cancelThiefAlert(context: Context) {
        getManager(context).cancel(THIEF_ALERT_NOTIFICATION_ID)
    }

    private fun getManager(context: Context) =
        context.getSystemService(NotificationManager::class.java)

    const val ACTION_SILENCE = "com.saman.batterymusic.SILENCE"
    const val THIEF_ALERT_NOTIFICATION_ID = 2
}
