package com.saman.batterymusic

import android.content.Intent
import android.graphics.BitmapFactory
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.MutableTransitionState
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.slideInVertically
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
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
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalHapticFeedback
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
fun DashScreen(
    prefs: Prefs,
    darkTheme: Boolean,
    onUnpaired: () -> Unit,
    onToggleTheme: (androidx.compose.ui.geometry.Offset) -> Unit,
) {
    var state by remember { mutableStateOf<PollState?>(null) }
    var photo by remember { mutableStateOf<android.graphics.Bitmap?>(null) }
    var status by remember { mutableStateOf("") }
    var passDialog by remember { mutableStateOf(false) }
    var passInput by remember { mutableStateOf("") }
    var passError by remember { mutableStateOf<String?>(null) }
    var unpairConfirm by remember { mutableStateOf(false) }
    var ringing by remember { mutableStateOf(ArmService.ringing) }
    var otherSilent by remember { mutableStateOf(ArmService.otherSilent) }
    var otherSilentName by remember { mutableStateOf(ArmService.otherSilentName) }
    var otherSilentSince by remember { mutableStateOf(ArmService.otherSilentSince) }
    var sirenTestRunning by remember { mutableStateOf(false) }
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val haptics = LocalHapticFeedback.current

    LaunchedEffect(Unit) {
        while (true) {
            state = withContext(Dispatchers.IO) { prefs.newClient().poll() }
            delay(5_000)
        }
    }

    // The ArmService siren rings outside Compose; mirror it here so the
    // dashboard can offer a big SILENCE button while it's going off.
    LaunchedEffect(Unit) {
        while (true) {
            ringing = ArmService.ringing
            otherSilent = ArmService.otherSilent
            otherSilentName = ArmService.otherSilentName
            otherSilentSince = ArmService.otherSilentSince
            delay(400)
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
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("Battery Music Notifier", style = MaterialTheme.typography.titleLarge)
            Row(verticalAlignment = Alignment.CenterVertically) {
                ThemeToggleButton(darkTheme = darkTheme, onToggle = onToggleTheme)
                OutlinedButton(onClick = { unpairConfirm = true }) { Text("Unpair") }
            }
        }

        StaggerIn(0) {
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(16.dp)) {
                    val s = state
                    if (s == null) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            CircularProgressIndicator(
                                modifier = Modifier.size(16.dp),
                                strokeWidth = 2.dp,
                            )
                            Spacer(Modifier.size(12.dp))
                            Text("Relay unreachable, retrying...")
                        }
                    } else {
                        // The alert state breathes: pulse + animated color.
                        val statusColor by animateColorAsState(
                            if (s.alertActive) MaterialTheme.colorScheme.error
                            else MaterialTheme.colorScheme.primary,
                            label = "statusColor",
                        )
                        val pulse = rememberInfiniteTransition(label = "alertPulse")
                        val pulseScale by pulse.animateFloat(
                            initialValue = 0.94f, targetValue = 1.06f,
                            animationSpec = infiniteRepeatable(tween(450), RepeatMode.Reverse),
                            label = "pulseScale",
                        )
                        Text(
                            if (s.alertActive) "ALERT: ${s.alertType}" else "Idle",
                            style = MaterialTheme.typography.titleMedium,
                            color = statusColor,
                            modifier = if (s.alertActive) {
                                Modifier.graphicsLayer {
                                    scaleX = pulseScale
                                    scaleY = pulseScale
                                }
                            } else {
                                Modifier
                            },
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
                                                 else when (cleared.error) {
                                                     // This phone raised the THIEF (phone
                                                     // theft): the relay refuses self-clear.
                                                     "origin_cannot_clear" ->
                                                         "This phone raised the alarm -- clear it from the laptop, or disarm."
                                                     else -> "Clear failed: ${cleared.error}"
                                                 }
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
                        } else if (ringing) {
                            // The relay watcher is mid-siren but the account
                            // state already moved on: silence just this phone.
                            Spacer(Modifier.height(8.dp))
                            Button(
                                onClick = {
                                    ArmService.silence()
                                    Notifications.cancelThiefAlert(context)
                                    status = "Phone silenced."
                                },
                                colors = androidx.compose.material3.ButtonDefaults.buttonColors(
                                    containerColor = MaterialTheme.colorScheme.error,
                                ),
                                modifier = Modifier.fillMaxWidth(),
                            ) { Text("SILENCE PHONE SIREN") }
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
        }

        // Dead-man's switch: the laptop's heartbeat went stale while armed.
        if (otherSilent) {
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = androidx.compose.material3.CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.errorContainer,
                ),
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text(
                        "LAPTOP WENT SILENT",
                        style = MaterialTheme.typography.titleMedium,
                        color = MaterialTheme.colorScheme.onErrorContainer,
                    )
                    val since = if (otherSilentSince > 0)
                        java.time.Instant.ofEpochSecond(otherSilentSince)
                            .atZone(java.time.ZoneId.systemDefault())
                            .format(java.time.format.DateTimeFormatter.ofPattern("HH:mm"))
                    else "--:--"
                    Text(
                        "${otherSilentName ?: "Your laptop"} stopped checking in at $since -- asleep, crashed, or taken.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onErrorContainer,
                    )
                    Spacer(Modifier.height(8.dp))
                    Button(
                        onClick = {
                            ArmService.silence()
                            Notifications.cancelOtherSilent(context)
                        },
                        colors = androidx.compose.material3.ButtonDefaults.buttonColors(
                            containerColor = MaterialTheme.colorScheme.error,
                        ),
                        modifier = Modifier.fillMaxWidth(),
                    ) { Text("SILENCE") }
                }
            }
        }

        // Account-level ARM: drives every device, not just this phone
        StaggerIn(1) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("System armed", style = MaterialTheme.typography.titleMedium)
                Switch(
                    checked = state?.armed == true,
                    onCheckedChange = { on ->
                        haptics.performHapticFeedback(HapticFeedbackType.LongPress)
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
        }

        StaggerIn(2) { SetupChecklist(prefs, state, onUpdate = { status = it }) }

        StaggerIn(3) {
            // Verify the phone-side siren without sending a real alert.
            OutlinedButton(
                onClick = {
                    if (sirenTestRunning || ringing) return@OutlinedButton
                    sirenTestRunning = true
                    scope.launch {
                        SirenPlayer.start(context)
                        delay(3_000)
                        SirenPlayer.stop()
                        sirenTestRunning = false
                        status = "Siren test done -- that's what a thief hears."
                    }
                },
                enabled = !sirenTestRunning && !ringing,
                modifier = Modifier.fillMaxWidth(),
            ) { Text(if (sirenTestRunning) "SIREN TESTING..." else "Test siren (3 s)") }
        }

        if (status.isNotEmpty()) Text(status)
    }

    if (unpairConfirm) {
        AlertDialog(
            onDismissRequest = { unpairConfirm = false },
            title = { Text("Unpair this phone?") },
            text = { Text("The phone loses its relay token. You'll need a fresh 6-digit code from the laptop to pair again.") },
            confirmButton = {
                TextButton(onClick = { unpairConfirm = false; onUnpaired() }) { Text("Unpair") }
            },
            dismissButton = {
                TextButton(onClick = { unpairConfirm = false }) { Text("Cancel") }
            },
        )
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

/**
 * Entrance animation: fade + slight rise, staggered by index so the
 * dashboard settles in like a deck being dealt instead of popping at once.
 */
@Composable
fun StaggerIn(index: Int, content: @Composable () -> Unit) {
    val visible = remember { MutableTransitionState(false).apply { targetState = true } }
    val delay = index * 90
    AnimatedVisibility(
        visibleState = visible,
        enter = fadeIn(tween(300, delayMillis = delay)) +
            slideInVertically(tween(380, delayMillis = delay)) { it / 4 },
        exit = androidx.compose.animation.ExitTransition.None,
    ) { content() }
}
