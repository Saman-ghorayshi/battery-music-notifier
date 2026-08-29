package com.saman.batterymusic

import android.content.Context
import android.media.AudioManager
import android.media.RingtoneManager
import androidx.work.Worker
import androidx.work.WorkerParameters

/**
 * Sends THIEF_ALERT through the relay. Expedited, with exponential backoff:
 * a dropped packet must not lose the alarm, so retry until the worker
 * accepts or WorkManager gives up.
 */
class ThiefWorker(context: Context, params: WorkerParameters) : Worker(context, params) {

    override fun doWork(): Result {
        val prefs = Prefs.get(applicationContext)
        if (!prefs.hasToken()) return Result.failure()

        val client = prefs.newClient()
        // The account flag is the truth: a remote disarm silences this phone,
        // a remote arm (done from the laptop) protects it. No token or
        // network problem defaults to ALERTING -- fail loud, not silent.
        val state = client.poll()
        if (state != null && !state.armed) return Result.success()

        val battery = readBatteryPct(applicationContext)
        val result = client.sendAlert("THIEF_ALERT", battery, charging = false)
        if (result.ok) {
            SirenPlayer.start(applicationContext) // local siren too, thief hears it
            return Result.success()
        }
        // Network hiccup or rate limit: try again later. Banned tokens will
        // keep failing, so give up after WorkManager's retry cap kicks in.
        return if (result.error == "banned") Result.failure() else Result.retry()
    }

    private fun readBatteryPct(context: Context): Int {
        val bm = context.getSystemService(Context.BATTERY_SERVICE) as? android.os.BatteryManager
        return bm?.getIntProperty(android.os.BatteryManager.BATTERY_PROPERTY_CAPACITY) ?: -1
    }
}

/** Small looping siren: default alarm sound at max volume until stopped. */
object SirenPlayer {

    @Volatile private var player: android.media.MediaPlayer? = null

    fun start(context: Context) {
        if (player != null) return
        try {
            val audioManager = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
            audioManager.setStreamVolume(
                AudioManager.STREAM_ALARM,
                audioManager.getStreamMaxVolume(AudioManager.STREAM_ALARM),
                0,
            )
            val uri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM)
                ?: RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE)
            val mp = android.media.MediaPlayer()
            mp.setDataSource(context, uri)
            mp.setAudioAttributes(
                android.media.AudioAttributes.Builder()
                    .setUsage(android.media.AudioAttributes.USAGE_ALARM)
                    .setContentType(android.media.AudioAttributes.CONTENT_TYPE_SONIFICATION)
                    .build()
            )
            mp.isLooping = true
            mp.prepare()
            mp.start()
            player = mp
        } catch (e: Exception) {
            player = null
        }
    }

    fun stop() {
        player?.let {
            try { it.stop(); it.release() } catch (_: Exception) {}
        }
        player = null
    }
}
