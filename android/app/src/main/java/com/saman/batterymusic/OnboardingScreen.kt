package com.saman.batterymusic

import android.Manifest
import android.content.Intent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

/**
 * First-launch walkthrough: every permission is asked here, ONCE, with the
 * honest reason it exists. This is an open-source app -- the copy below is
 * the trust contract; the source is the proof. Nothing is asked silently,
 * and the things Android cannot grant via a dialog deep-link to the exact
 * settings page instead.
 */
@Composable
fun OnboardingScreen(prefs: Prefs, onDone: () -> Unit) {
    val context = LocalContext.current
    val notifLauncher = androidx.activity.compose.rememberLauncherForActivityResult(
        androidx.activity.result.contract.ActivityResultContracts.RequestPermission(),
    ) { }
    val cameraLauncher = androidx.activity.compose.rememberLauncherForActivityResult(
        androidx.activity.result.contract.ActivityResultContracts.RequestPermission(),
    ) { }

    // Live mirror of what the system currently grants, re-checked as the
    // user returns from settings pages.
    var notifOk by remember { mutableStateOf(false) }
    var cameraOk by remember { mutableStateOf(false) }
    var batteryOk by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) {
        while (true) {
            notifOk = androidx.core.content.ContextCompat.checkSelfPermission(
                context, Manifest.permission.POST_NOTIFICATIONS,
            ) == android.content.pm.PackageManager.PERMISSION_GRANTED
            cameraOk = androidx.core.content.ContextCompat.checkSelfPermission(
                context, Manifest.permission.CAMERA,
            ) == android.content.pm.PackageManager.PERMISSION_GRANTED
            val pm = context.getSystemService(android.os.PowerManager::class.java)
            batteryOk = pm?.isIgnoringBatteryOptimizations(context.packageName) == true
            kotlinx.coroutines.delay(1_000)
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Battery Music Notifier", style = MaterialTheme.typography.headlineSmall)
        Text(
            "Open source. Read every line before you trust it with anything.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        Card(modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.padding(16.dp)) {
                Text("What this app does", style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.height(6.dp))
                Text(
                    "It guards your devices. Your laptop screams when someone unplugs it; " +
                        "your phone screams when your laptop goes quiet. Alerts cross a dumb " +
                        "relay you control, and the alarm is yours -- every sound file in this " +
                        "app is a song from your own music folder.",
                )
            }
        }

        PermissionCard(
            title = "Notifications",
            why = "A thief alert is useless if you never see it. This is how the siren " +
                "and the 'LAPTOP WENT SILENT' warning reach your screen.",
            granted = notifOk,
            pendingLabel = "Allow",
            grantedLabel = "Allowed",
        ) {
            notifLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        }

        PermissionCard(
            title = "Camera",
            why = "If the alarm rings, the front camera takes ONE photo of whoever is " +
                "holding the phone and uploads it to YOUR private relay account, next " +
                "to the alert -- so you can see them. No scanning, no gallery access, " +
                "no photos when the alarm is off. Refuse it and everything else still works.",
            granted = cameraOk,
            pendingLabel = "Allow",
            grantedLabel = "Allowed",
        ) {
            cameraLauncher.launch(Manifest.permission.CAMERA)
        }

        PermissionCard(
            title = "Battery: no restrictions",
            why = "Android loves killing background guards. To watch for a stolen " +
                "laptop while the screen is off, the system must leave this app alone.",
            granted = batteryOk,
            pendingLabel = "Open battery settings",
            grantedLabel = "Unrestricted",
        ) {
            try {
                context.startActivity(
                    Intent(android.provider.Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
                        .setData(android.net.Uri.parse("package:" + context.packageName)),
                )
            } catch (_: Exception) {
                try {
                    context.startActivity(
                        Intent(android.provider.Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS),
                    )
                } catch (_: Exception) {}
            }
        }

        PermissionCard(
            title = "MIUI: Background autostart",
            why = "Xiaomi ships extra kill switches the standard settings don't cover. " +
                "Opening Security and allowing autostart is what keeps the guard alive " +
                "on this phone. (You can skip this on other brands.)",
            granted = null,
            pendingLabel = "Open MIUI settings",
            grantedLabel = "Open MIUI settings",
        ) {
            try {
                context.startActivity(
                    Intent("miui.intent.action.APP_PERM_EDITOR")
                        .setClassName("com.miui.securitycenter", "com.miui.permcenter.permissions.PermissionsEditorActivity")
                        .putExtra("extra_pkgname", context.packageName),
                )
            } catch (_: Exception) {
                try {
                    context.startActivity(
                        android.content.Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
                            .setData(android.net.Uri.parse("package:" + context.packageName)),
                    )
                } catch (_: Exception) {}
            }
        }

        Button(
            onClick = {
                prefs.onboardingDone = true
                onDone()
            },
            modifier = Modifier.fillMaxWidth(),
        ) { Text(if (notifOk && cameraOk && batteryOk) "Done -- everything allowed" else "Continue") }

        Text(
            "You can change any of these later, and the dashboard re-checks them " +
                "for you under 'Finish setup'.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(24.dp))
    }
}

/** One permission: why it exists, whether it's granted, and the action. */
@Composable
fun PermissionCard(
    title: String,
    why: String,
    granted: Boolean?,
    pendingLabel: String,
    grantedLabel: String,
    action: () -> Unit,
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                when (granted) {
                    true -> Text("✓", color = MaterialTheme.colorScheme.primary, fontWeight = FontWeight.Bold)
                    false -> Text("✗", color = MaterialTheme.colorScheme.error, fontWeight = FontWeight.Bold)
                    null -> {}
                }
            }
            Spacer(Modifier.height(4.dp))
            Text(why, style = MaterialTheme.typography.bodySmall)
            Spacer(Modifier.height(8.dp))
            OutlinedButton(onClick = action, enabled = granted != true) {
                Text(if (granted == true) grantedLabel else pendingLabel)
            }
        }
    }
}
