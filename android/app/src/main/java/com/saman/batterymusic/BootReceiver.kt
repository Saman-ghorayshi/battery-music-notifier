package com.saman.batterymusic

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/**
 * After a reboot, the armed watcher must come back on its own: the armed
 * flag survives in encrypted prefs, so restart the foreground service if
 * the user had armed it. The thief receiver (PowerReceiver) works without
 * this -- this is for the real-time relay watching.
 */
class BootReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED) return
        if (Prefs.get(context).armed) {
            context.startForegroundService(Intent(context, ArmService::class.java))
        }
    }
}
