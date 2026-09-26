package com.saman.batterymusic

import android.content.Context
import android.content.Intent
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
        // The phone's OWN power state, read fresh: the relay's account-level
        // is_charging is whatever device pinged last and goes stale (it once
        // reported "discharging" while this phone was on the charger, which
        // fired a phantom low-battery alarm on the whole account).
        val charging = isChargingNow(applicationContext)

        when {
            low && !charging && !state.alertActive ->
                client.sendAlert("BATTERY", battery, charging)
            // Back on the charger: stand the low-battery alert down right
            // here -- the next periodic run is 15 minutes away and the
            // laptop siren shouldn't honk for quarter of an hour.
            charging && state.alertActive && state.alertType == "BATTERY" ->
                client.clearAlert()
            !low && state.alertActive && state.alertType == "BATTERY" ->
                client.clearAlert()
        }
        return Result.success()
    }

    private fun readBatteryPct(context: Context): Int {
        val bm = context.getSystemService(Context.BATTERY_SERVICE) as? android.os.BatteryManager
        return bm?.getIntProperty(android.os.BatteryManager.BATTERY_PROPERTY_CAPACITY) ?: -1
    }

    /** True only when THIS phone is actually drawing power right now. */
    private fun isChargingNow(context: Context): Boolean {
        val bm = context.getSystemService(Context.BATTERY_SERVICE) as? android.os.BatteryManager
        val status = bm?.getIntProperty(android.os.BatteryManager.BATTERY_PROPERTY_STATUS) ?: 0
        if (status == android.os.BatteryManager.BATTERY_STATUS_CHARGING ||
            status == android.os.BatteryManager.BATTERY_STATUS_FULL
        ) return true
        // Fallback: the sticky battery intent's plugged flag.
        val intent = context.registerReceiver(null, android.content.IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        return intent?.getIntExtra(android.os.BatteryManager.EXTRA_PLUGGED, 0) != 0
    }
}

fun scheduleBatteryWatcher(context: Context) {
    val request = PeriodicWorkRequestBuilder<BatteryWorker>(15, TimeUnit.MINUTES).build()
    WorkManager.getInstance(context).enqueueUniquePeriodicWork(
        "battery-watch", ExistingPeriodicWorkPolicy.KEEP, request,
    )
}
