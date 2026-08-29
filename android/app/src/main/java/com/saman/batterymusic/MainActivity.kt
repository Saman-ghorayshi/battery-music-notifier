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

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs.get(this)
        paired = prefs.hasToken()
        if (Build.VERSION.SDK_INT >= 33) {
            notifPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
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
