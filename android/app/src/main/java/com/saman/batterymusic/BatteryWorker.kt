package com.saman.batterymusic

import android.content.Context
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import java.util.concurrent.TimeUnit

/**
 * Periodic watcher (WorkManager floor is 15 minutes): post a threshold alert
 * when the battery crosses the configured band, and auto-clear once it is
 * charging again. Mirrors the desktop monitor's battery alert behavior.
 */
class BatteryWorker(context: Context, params: WorkerParameters) : Worker(context, params) {

    override fun doWork(): Result {
        val prefs = Prefs.get(applicationContext)
        if (!prefs.hasToken()) return Result.success()

        val client = prefs.newClient()
        val state = client.poll() ?: return Result.success()

        // Remote arm (e.g. from the laptop): Android forbids starting a
        // foreground service from the background, so nudge with a
        // notification the user taps once to activate full watching.
        if (state.armed && !prefs.armed) {
            val notifGranted = androidx.core.content.ContextCompat.checkSelfPermission(
                applicationContext, android.Manifest.permission.POST_NOTIFICATIONS,
            ) == android.content.pm.PackageManager.PERMISSION_GRANTED
            if (notifGranted) {
                Notifications.createChannels(applicationContext)
                val n = androidx.core.app.NotificationCompat.Builder(
                    applicationContext, Notifications.CHANNEL_ARMED,
                )
                    .setSmallIcon(android.R.drawable.ic_lock_idle_lock)
                    .setContentTitle("System armed remotely")
                    .setContentText("Tap to activate watching on this phone")
                    .setContentIntent(android.app.PendingIntent.getActivity(
                        applicationContext, 3,
                        android.content.Intent(applicationContext, MainActivity::class.java),
                        android.app.PendingIntent.FLAG_IMMUTABLE,
                    ))
                    .build()
                androidx.core.app.NotificationManagerCompat.from(applicationContext)
                    .notify(Notifications.REMOTE_ARMED_NOTIFICATION_ID, n)
            }
        }

        val battery = readBatteryPct(applicationContext)
        if (battery < 0) return Result.success()

        val low = battery <= 20
        val charging = state.isCharging
        when {
            low && !charging && !state.alertActive ->
                client.sendAlert("BATTERY", battery, charging)
            !low && state.alertActive && state.alertType == "BATTERY" ->
                client.clearAlert()
        }
        return Result.success()
    }

    private fun readBatteryPct(context: Context): Int {
        val bm = context.getSystemService(Context.BATTERY_SERVICE) as? android.os.BatteryManager
        return bm?.getIntProperty(android.os.BatteryManager.BATTERY_PROPERTY_CAPACITY) ?: -1
    }
}

fun scheduleBatteryWatcher(context: Context) {
    val request = PeriodicWorkRequestBuilder<BatteryWorker>(15, TimeUnit.MINUTES).build()
    WorkManager.getInstance(context).enqueueUniquePeriodicWork(
        "battery-watch", ExistingPeriodicWorkPolicy.KEEP, request,
    )
}
