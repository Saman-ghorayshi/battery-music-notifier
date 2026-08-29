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
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.Switch
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Dashboard: everything keys off the ACCOUNT's armed state (poll every 5 s)
 * so any device can arm/disarm the whole system. The pass is asked only for
 * the dangerous direction -- disarming.
 */
@Composable
fun DashScreen(prefs: Prefs, onUnpaired: () -> Unit) {
    var state by remember { mutableStateOf<PollState?>(null) }
    var photo by remember { mutableStateOf<android.graphics.Bitmap?>(null) }
    var status by remember { mutableStateOf("") }
    var passDialog by remember { mutableStateOf(false) }
    var passInput by remember { mutableStateOf("") }
    var passError by remember { mutableStateOf<String?>(null) }
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    LaunchedEffect(Unit) {
        while (true) {
            state = withContext(Dispatchers.IO) { prefs.newClient().poll() }
            delay(5_000)
        }
    }

    // Keep the local watcher lifecycle in sync with the account flag
    LaunchedEffect(state?.armed) {
        val s = state ?: return@LaunchedEffect
        prefs.armed = s.armed
        if (s.armed && !ArmService.ringing) {
            context.startForegroundService(Intent(context, ArmService::class.java))
        } else if (!s.armed) {
            context.startService(
                Intent(context, ArmService::class.java).setAction(ArmService.ACTION_DISARM),
            )
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
                    if (s.armedBy != null) {
                        Text("Armed by: ${s.armedBy}", style = MaterialTheme.typography.bodySmall)
                    }
                    if (s.alertActive) {
                        Spacer(Modifier.height(8.dp))
                        Button(
                            onClick = {
                                scope.launch {
                                    val cleared = withContext(Dispatchers.IO) {
                                        prefs.newClient().clearAlert()
                                    }
                                    ArmService.silence()
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
                                photo = bytes?.let {
                                    BitmapFactory.decodeByteArray(it, 0, it.size)
                                }
                                if (photo == null) status = "Could not load photo"
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

        // Account-level ARM: drives every device, not just this phone
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text("System armed", style = MaterialTheme.typography.titleMedium)
            Switch(
                checked = state?.armed == true,
                onCheckedChange = { on ->
                    if (on) {
                        scope.launch {
                            val r = withContext(Dispatchers.IO) { prefs.newClient().armAccount(true) }
                            status = if (r.ok) "Armed -- charger pull and intruders are watched."
                                     else "Arm failed: ${r.error}"
                        }
                    } else {
                        // The dangerous direction: ask for the pass when one exists
                        if (state?.hasPass == true) {
                            passInput = ""
                            passError = null
                            passDialog = true
                        } else {
                            scope.launch {
                                val r = withContext(Dispatchers.IO) { prefs.newClient().armAccount(false) }
                                status = if (r.ok) "Disarmed." else "Disarm failed: ${r.error}"
                            }
                        }
                    }
                },
            )
        }

        SetupChecklist(prefs, state, onUpdate = { status = it })

        if (status.isNotEmpty()) Text(status)
    }

    if (passDialog) {
        AlertDialog(
            onDismissRequest = { passDialog = false },
            title = { Text("Disarm pass") },
            text = {
                Column {
                    Text("Disarming the whole system needs your pass.")
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        value = passInput,
                        onValueChange = { passInput = it },
                        label = { Text("Pass") },
                        singleLine = true,
                        visualTransformation = PasswordVisualTransformation(),
                    )
                    passError?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    scope.launch {
                        val r = withContext(Dispatchers.IO) {
                            prefs.newClient().armAccount(false, passInput)
                        }
                        if (r.ok) {
                            passDialog = false
                            status = "Disarmed."
                        } else {
                            passError = when (r.error) {
                                "invalid_pass" -> "Wrong pass."
                                "rate_limited" -> "Too many attempts -- wait a minute."
                                else -> r.error ?: "failed"
                            }
                        }
                    }
                }) { Text("Disarm") }
            },
            dismissButton = {
                TextButton(onClick = { passDialog = false }) { Text("Cancel") }
            },
        )
    }
}

/**
 * Setup checklist: everything the app needs to actually work without the
 * owner babysitting it. Items tick themselves off as they're satisfied.
 */
@Composable
fun SetupChecklist(prefs: Prefs, state: PollState?, onUpdate: (String) -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val notifLauncher = androidx.activity.compose.rememberLauncherForActivityResult(
        androidx.activity.result.contract.ActivityResultContracts.RequestPermission(),
    ) { }
    val notifGranted = androidx.core.content.ContextCompat.checkSelfPermission(
        context, android.Manifest.permission.POST_NOTIFICATIONS,
    ) == android.content.pm.PackageManager.PERMISSION_GRANTED
    val batteryOk = remember {
        val pm = context.getSystemService(android.os.PowerManager::class.java)
        pm?.isIgnoringBatteryOptimizations(context.packageName) == true
    }
    val passOk = state?.hasPass == true
    if (notifGranted && batteryOk && passOk) return

    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text("Finish setup", style = MaterialTheme.typography.titleMedium)
            Text(if (notifGranted) "\u2713 Notifications allowed"
                 else "\u2717 Notifications allowed (needed for alerts)")
            Text(if (batteryOk) "\u2713 Battery unrestricted"
                 else "\u2717 Battery unrestricted (needed for background watching)")
            Text(if (passOk) "\u2713 Disarm pass set"
                 else "\u2717 Disarm pass set (protects against unwanted disarms)")
            if (!notifGranted) {
                OutlinedButton(onClick = {
                    notifLauncher.launch(android.Manifest.permission.POST_NOTIFICATIONS)
                }) { Text("Allow notifications") }
            }
            if (!batteryOk) {
                OutlinedButton(onClick = {
                    try {
                        context.startActivity(
                            Intent(android.provider.Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS),
                        )
                    } catch (_: Exception) {}
                }) { Text("Open battery settings") }
            }
            if (!passOk) {
                var pass1 by remember { mutableStateOf("") }
                OutlinedTextField(
                    value = pass1,
                    onValueChange = { pass1 = it },
                    label = { Text("Choose a disarm pass (4+ chars)") },
                    singleLine = true,
                    visualTransformation = PasswordVisualTransformation(),
                    modifier = Modifier.fillMaxWidth(),
                )
                Button(
                    onClick = {
                        scope.launch {
                            val r = withContext(Dispatchers.IO) { prefs.newClient().setPass(pass1) }
                            onUpdate(
                                if (r.ok) "Pass saved -- disarming will ask for it."
                                else "Pass setup failed: ${r.error}",
                            )
                        }
                    },
                    enabled = pass1.length >= 4,
                ) { Text("Save pass") }
            }
        }
    }
}
