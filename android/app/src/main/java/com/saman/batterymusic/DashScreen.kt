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

    // Keep the local watcher lifecycle in sync with the account flag.
    // Keyed on the armed value itself: this body runs on transitions only,
    // not on every 5-second poll (start/stop spam would churn the OS).
    LaunchedEffect(state?.armed) {
        val s = state ?: return@LaunchedEffect
        prefs.armed = s.armed
        if (s.armed) {
            context.startForegroundService(Intent(context, ArmService::class.java))
        } else {
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
                                    Notifications.cancelThiefAlert(context)
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
                    } else if (KeystoreManager.hasKey() && context is androidx.fragment.app.FragmentActivity) {
                        // Preferred disarm: fingerprint-signed, no typing
                        launchBiometricDisarm(context, prefs, scope, onUpdate = { status = it },
                            onPassFallback = { passInput = ""; passError = null; passDialog = true })
                    } else if (state?.hasPass == true) {
                        passInput = ""
                        passError = null
                        passDialog = true
                    } else {
                        scope.launch {
                            val r = withContext(Dispatchers.IO) { prefs.newClient().armAccount(false) }
                            status = if (r.ok) "Disarmed." else "Disarm failed: ${r.error}"
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
 * Preferred disarm: the phone itself is the passkey. The private key lives
 * in AndroidKeyStore, gated by the fingerprint; only a signature over a
 * fresh relay challenge travels. Falls back to the pass dialog when
 * biometrics are unavailable.
 */
fun launchBiometricDisarm(
    activity: androidx.fragment.app.FragmentActivity,
    prefs: Prefs,
    scope: kotlinx.coroutines.CoroutineScope,
    onUpdate: (String) -> Unit,
    onPassFallback: () -> Unit,
) {
    try {
        KeystoreManager.ensureKey()
        val sig = KeystoreManager.signingSignature()
        val executor = androidx.core.content.ContextCompat.getMainExecutor(activity)
        val prompt = androidx.biometric.BiometricPrompt(
            activity, executor,
            object : androidx.biometric.BiometricPrompt.AuthenticationCallback() {
                override fun onAuthenticationSucceeded(
                    result: androidx.biometric.BiometricPrompt.AuthenticationResult,
                ) {
                    scope.launch {
                        val challenge = withContext(Dispatchers.IO) {
                            prefs.newClient().armChallenge()
                        }
                        if (challenge == null) {
                            onUpdate("Could not get a challenge from the relay.")
                            return@launch
                        }
                        val raw = try {
                            KeystoreManager.derToRaw(KeystoreManager.sign(sig))
                        } catch (e: Exception) {
                            onUpdate("Signing failed: ${e.message}")
                            return@launch
                        }
                        val keySig = android.util.Base64.encodeToString(raw, android.util.Base64.NO_WRAP)
                        val r = withContext(Dispatchers.IO) {
                            prefs.newClient().armAccount(false, keySig = keySig)
                        }
                        if (r.ok) onUpdate("Disarmed with fingerprint.")
                        else onUpdate("Disarm failed: ${r.error}")
                    }
                }

                override fun onAuthenticationError(code: Int, msg: CharSequence) {
                    if (code == androidx.biometric.BiometricPrompt.ERROR_NEGATIVE_BUTTON ||
                        code == androidx.biometric.BiometricPrompt.ERROR_USER_CANCELED
                    ) {
                        onPassFallback()
                    } else {
                        onUpdate(msg.toString())
                    }
                }
            },
        )
        val info = androidx.biometric.BiometricPrompt.PromptInfo.Builder()
            .setTitle("Disarm with fingerprint")
            .setSubtitle("Signs a one-time challenge -- nothing secret leaves the phone")
            .setNegativeButtonText("Use pass instead")
            .build()
        prompt.authenticate(info, androidx.biometric.BiometricPrompt.CryptoObject(sig))
    } catch (_: Exception) {
        onPassFallback() // no biometrics enrolled, key issues -> pass instead
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
    // Recomputed on every poll-driven recomposition: flipping the real
    // system setting must refresh this card without an app restart.
    val batteryOk: Boolean = run {
        val pm = context.getSystemService(android.os.PowerManager::class.java)
        pm?.isIgnoringBatteryOptimizations(context.packageName) == true
    }
    val passOk = state?.hasPass == true
    val keyOk = state?.hasKey == true || KeystoreManager.hasKey()
    if (notifGranted && batteryOk && (passOk || keyOk)) return

    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text("Finish setup", style = MaterialTheme.typography.titleMedium)
            Text(if (notifGranted) "\u2713 Notifications allowed"
                 else "\u2717 Notifications allowed (needed for alerts)")
            Text(if (batteryOk) "\u2713 Battery unrestricted"
                 else "\u2717 Battery unrestricted (needed for background watching)")
            Text(if (keyOk) "\u2713 Fingerprint disarm key enrolled"
                 else "\u2717 Fingerprint disarm key enrolled")
            Text(if (passOk) "\u2713 Disarm pass set (backup option)"
                 else "\u2717 Disarm pass set (backup option)")
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
            if (!keyOk) {
                OutlinedButton(onClick = {
                    scope.launch {
                        val r = withContext(Dispatchers.IO) {
                            try {
                                KeystoreManager.ensureKey()
                                prefs.newClient().setDisarmKey(KeystoreManager.publicKeyB64())
                            } catch (e: Exception) {
                                ApiResult(false, e.message ?: "key error")
                            }
                        }
                        onUpdate(
                            if (r.ok) "Fingerprint disarm key enrolled."
                            else "Key setup failed: ${r.error}",
                        )
                    }
                }) { Text("Enroll fingerprint disarm key") }
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
