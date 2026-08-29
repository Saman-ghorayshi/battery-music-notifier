package com.saman.batterymusic

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/**
 * "Silence" button on the thief-alert notification: stops the local siren
 * and clears the notification. The relay's alert state is left alone -- the
 * owner clears it from the device that raised it.
 */
class AlertActionReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Notifications.ACTION_SILENCE) return
        ArmService.silence()
        Notifications.cancelThiefAlert(context)
    }
}
