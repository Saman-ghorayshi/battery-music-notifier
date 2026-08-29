package com.saman.batterymusic

import android.Manifest
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue

/**
 * Compose host: pairing onboarding until we hold a linked token, then the
 * dashboard. The armed flag and token live in encrypted prefs, so the app
 * resumes its state after process death.
 */
class MainActivity : ComponentActivity() {

    private lateinit var prefs: Prefs
    private var paired by mutableStateOf(false)

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

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs.get(this)
        paired = prefs.hasToken()
        if (Build.VERSION.SDK_INT >= 33) {
            notifPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
        askBatteryUnrestrictionOnce()
        // Idempotent (KEEP policy): schedules on first launch, keeps interval after.
        if (prefs.hasToken()) scheduleBatteryWatcher(this)
        setContent {
            MaterialTheme {
                Surface {
                    if (paired) DashScreen(prefs, onUnpaired = { paired = false })
                    else PairScreen(prefs, onPaired = { paired = true })
                }
            }
        }
    }
}
