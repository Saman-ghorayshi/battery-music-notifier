package com.saman.batterymusic

import android.Manifest
import android.graphics.Bitmap
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.PixelCopy
import androidx.fragment.app.FragmentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.asImageBitmap

/**
 * Compose host: pairing onboarding until we hold a linked token, then the
 * dashboard. The armed flag and token live in encrypted prefs, so the app
 * resumes its state after process death.
 */
class MainActivity : FragmentActivity() {

    private lateinit var prefs: Prefs
    private var paired by mutableStateOf(false)
    private var darkTheme by mutableStateOf(true)
    private var wave by mutableStateOf<WaveCapture?>(null)

    private val mainHandler = Handler(Looper.getMainLooper())

    private val notifPermission =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { }

    /**
     * OEM battery managers (Xiaomi/Samsung/...) love killing background
     * polling, which is the whole job of the armed watcher. Send the user to
     * the battery settings once; sideloaded app, so no Play-policy worry.
     */
    private fun askBatteryUnrestrictionOnce() {
        if (!prefs.hasToken()) return
        val sp = getSharedPreferences("hints", MODE_PRIVATE)
        if (sp.getBoolean("battery_prompted", false)) return
        val pm = getSystemService(android.os.PowerManager::class.java)
        if (pm?.isIgnoringBatteryOptimizations(packageName) == true) {
            sp.edit().putBoolean("battery_prompted", true).apply()
            return
        }
        sp.edit().putBoolean("battery_prompted", true).apply()
        try {
            startActivity(
                android.content.Intent(
                    android.provider.Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS,
                ),
            )
        } catch (_: Exception) {
            // Some OEMs hide the page; the user can do it manually
        }
    }

    /**
     * Theme flip with a wave: snapshot the outgoing frame, switch the scheme
     * underneath, then cut an expanding circle out of the snapshot from the
     * tap point so the new theme floods in from where the finger landed.
     */
    private fun toggleTheme(center: Offset) {
        if (wave != null) return // one wave at a time
        val w = window ?: return
        val bmp = try {
            Bitmap.createBitmap(
                maxOf(1, w.decorView.width), maxOf(1, w.decorView.height),
                Bitmap.Config.ARGB_8888,
            )
        } catch (_: Exception) { null }
        if (bmp == null) { flipTheme(WaveCapture(null, center)); return }
        try {
            PixelCopy.request(w, bmp, { result ->
                flipTheme(
                    if (result == PixelCopy.SUCCESS) WaveCapture(bmp.asImageBitmap(), center)
                    else WaveCapture(null, center),
                )
            }, mainHandler)
        } catch (_: Exception) {
            flipTheme(WaveCapture(null, center))
        }
    }

    private fun flipTheme(capture: WaveCapture) {
        wave = capture
        prefs.darkMode = !darkTheme
        darkTheme = !darkTheme
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs.get(this)
        paired = prefs.hasToken()
        darkTheme = prefs.darkMode
        if (Build.VERSION.SDK_INT >= 33) {
            notifPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
        askBatteryUnrestrictionOnce()
        // Idempotent (KEEP policy): schedules on first launch, keeps interval after.
        if (prefs.hasToken()) scheduleBatteryWatcher(this)
        setContent {
            MaterialTheme(colorScheme = if (darkTheme) DarkScheme else LightScheme) {
                Surface(Modifier.fillMaxSize()) {
                    if (paired) {
                        DashScreen(
                            prefs,
                            darkTheme = darkTheme,
                            onUnpaired = { paired = false },
                            onToggleTheme = ::toggleTheme,
                        )
                    } else {
                        PairScreen(
                            prefs,
                            onPaired = {
                                // First pairing happens after onCreate: schedule the
                                // battery watcher right now, not on next app start.
                                scheduleBatteryWatcher(this)
                                paired = true
                            },
                            darkTheme = darkTheme,
                            onToggleTheme = ::toggleTheme,
                        )
                    }
                }
                ThemeWaveOverlay(wave) { wave = null }
            }
        }
    }
}
