package com.saman.batterymusic

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import androidx.work.BackoffPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.OutOfQuotaPolicy
import androidx.work.WorkManager
import java.util.concurrent.TimeUnit

/**
 * Fires from the manifest when the charger is pulled, even with the app dead.
 * If armed, we enqueue an expedited ThiefWorker: the alert must leave the
 * phone in seconds, before the thief gets far.
 */
class PowerReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_POWER_DISCONNECTED) return
        val prefs = Prefs.get(context)
        if (!prefs.armed || !prefs.hasToken()) return

        val request = OneTimeWorkRequestBuilder<ThiefWorker>()
            .setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 10, TimeUnit.SECONDS)
            .build()
        WorkManager.getInstance(context)
            .enqueueUniqueWork("thief-alert", ExistingWorkPolicy.REPLACE, request)
    }
}
