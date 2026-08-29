package com.saman.batterymusic

import android.content.Intent
import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.OutlinedButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Dashboard: live relay state on a 5-second poll, the ARM toggle behind the
 * foreground service, and the intruder photo if the account has one.
 */
@Composable
fun DashScreen(prefs: Prefs, onUnpaired: () -> Unit) {
    var armed by remember { mutableStateOf(prefs.armed) }
    var state by remember { mutableStateOf<PollState?>(null) }
    var photo by remember { mutableStateOf<android.graphics.Bitmap?>(null) }
    var status by remember { mutableStateOf("") }
    val scope = rememberCoroutineScope()

    LaunchedEffect(Unit) {
        while (true) {
            state = withContext(Dispatchers.IO) { prefs.newClient().poll() }
            delay(5_000)
        }
    }

    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text("Battery Music Notifier", style = MaterialTheme.typography.titleLarge)
            OutlinedButton(onClick = onUnpaired) { Text("Unpair") }
        }

        Card(modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.padding(16.dp)) {
                val s = state
                if (s == null) {
                    Text("Relay unreachable, retrying...")
                } else {
                    Text(
                        if (s.alertActive) "ALERT: ${s.alertType}" else "Idle",
                        style = MaterialTheme.typography.titleMedium,
                        color = if (s.alertActive) MaterialTheme.colorScheme.error
                                else MaterialTheme.colorScheme.primary,
                    )
                    if (s.batteryPct >= 0) {
                        Text("Battery: ${s.batteryPct}%${if (s.isCharging) " (charging)" else ""}")
                    }
                    if (s.alertActive) {
                        Spacer(Modifier.height(8.dp))
                        Button(
                            onClick = {
                                scope.launch {
                                    val cleared = withContext(Dispatchers.IO) {
                                        prefs.newClient().clearAlert()
                                    }
                                    ArmService.silence() // stop the phone's own siren too
                                    status = if (cleared.ok) "Alarm stopped everywhere."
                                             else "Clear failed: ${cleared.error}"
                                }
                            },
                            colors = androidx.compose.material3.ButtonDefaults.buttonColors(
                                containerColor = MaterialTheme.colorScheme.error,
                            ),
                            modifier = Modifier.fillMaxWidth(),
                        ) { Text("STOP ALARM EVERYWHERE") }
                        Text(
                            "Stops the laptop siren too (guard listens for your clear).",
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                    if (s.snapshotId != null && photo == null) {
                        Spacer(Modifier.height(8.dp))
                        OutlinedButton(onClick = {
                            scope.launch {
                                val bytes = withContext(Dispatchers.IO) {
                                    prefs.newClient().fetchSnapshot(s.snapshotId!!)
                                }
                                val bmp = bytes?.let {
                                    BitmapFactory.decodeByteArray(it, 0, it.size)
                                }
                                photo = bmp
                                status = if (bmp == null) "Could not load photo" else ""
                            }
                        }) { Text("VIEW INTRUDER PHOTO") }
                    }
                }
                photo?.let {
                    Spacer(Modifier.height(8.dp))
                    Image(it.asImageBitmap(), contentDescription = "Intruder snapshot")
                }
            }
        }

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text("Thief alarm armed", style = MaterialTheme.typography.titleMedium)
            val context = androidx.compose.ui.platform.LocalContext.current
            Switch(
                checked = armed,
                onCheckedChange = { on ->
                    armed = on
                    prefs.armed = on
                    if (on) {
                        Notifications.createChannels(context)
                        context.startForegroundService(
                            Intent(context, ArmService::class.java),
                        )
                    } else {
                        SirenPlayer.stop()
                        context.startService(
                            Intent(context, ArmService::class.java)
                                .setAction(ArmService.ACTION_DISARM),
                        )
                    }
                },
            )
        }

        Text(
            if (armed) "Armed: charger unplug sends THIEF_ALERT even with the app dead."
            else "Disarmed. Arm before plugging in.",
            style = MaterialTheme.typography.bodySmall,
        )
        if (status.isNotEmpty()) Text(status)
    }
}
