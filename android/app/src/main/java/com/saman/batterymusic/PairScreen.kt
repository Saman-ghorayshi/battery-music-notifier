package com.saman.batterymusic

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Onboarding: point at the relay, type the 6-digit code the laptop shows
 * (battery-music pair), done. TEST fires a real alert so the user sees it
 * land on the laptop before trusting the app.
 */
@Composable
fun PairScreen(
    prefs: Prefs,
    onPaired: () -> Unit,
    darkTheme: Boolean,
    onToggleTheme: (androidx.compose.ui.geometry.Offset) -> Unit,
) {
    var workerUrl by remember { mutableStateOf(prefs.workerUrl) }
    var code by remember { mutableStateOf("") }
    var status by remember { mutableStateOf("") }
    var pairing by remember { mutableStateOf(false) }
    var showScanner by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    fun pairWith(url: String, pairingCode: String) {
        pairing = true
        status = "Pairing..."
        scope.launch {
            prefs.workerUrl = url
            val result = withContext(Dispatchers.IO) {
                ApiClient(url, prefs.token).pairLink(pairingCode)
            }
            pairing = false
            if (result.ok && result.token != null) {
                prefs.token = result.token
                onPaired()
            } else {
                status = "Failed: ${result.error}"
            }
        }
    }

    if (showScanner) {
        QrScanScreen(
            onDecoded = { raw ->
                showScanner = false
                val parsed = parsePairPayload(raw)
                if (parsed == null) {
                    status = "That QR is not a pairing code."
                } else {
                    workerUrl = parsed.first
                    code = parsed.second
                    pairWith(parsed.first, parsed.second)
                }
            },
            onCancel = { showScanner = false },
        )
        return
    }

    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        androidx.compose.foundation.layout.Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("Pair with your laptop", style = androidx.compose.material3.MaterialTheme.typography.headlineSmall)
            ThemeToggleButton(darkTheme = darkTheme, onToggle = onToggleTheme)
        }
        Spacer(Modifier.height(16.dp))
        OutlinedTextField(
            value = workerUrl,
            onValueChange = { workerUrl = it },
            label = { Text("Relay URL") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(8.dp))
        OutlinedTextField(
            value = code,
            onValueChange = { if (it.length <= 6) code = it.filter { c -> c.isDigit() } },
            label = { Text("6-digit code") },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(16.dp))
        Button(
            onClick = { pairWith(workerUrl, code) },
            enabled = !pairing && code.length == 6,
            modifier = Modifier.fillMaxWidth(),
        ) { Text("PAIR") }

        Spacer(Modifier.height(8.dp))
        OutlinedButton(
            onClick = { showScanner = true },
            enabled = !pairing,
            modifier = Modifier.fillMaxWidth(),
        ) { Text("SCAN QR CODE on the laptop") }

        Spacer(Modifier.height(24.dp))
        if (prefs.hasToken()) {
            OutlinedButton(
                onClick = {
                    scope.launch {
                        status = withContext(Dispatchers.IO) {
                            val r = prefs.newClient().sendAlert("THIEF_ALERT")
                            if (r.ok) "Test alert sent! Check the laptop." else "Failed: ${r.error}"
                        }
                    }
                },
                modifier = Modifier.fillMaxWidth(),
            ) { Text("SEND TEST ALERT") }
        }
        if (status.isNotEmpty()) {
            Spacer(Modifier.height(12.dp))
            Text(status)
        }
    }
}

/**
 * Parse the laptop's QR payload: "BMN1|<relay-url>|<6-digit-code>".
 * Null for anything else -- foreign QR codes must be ignored, never
 * half-applied. Pure JVM so the unit tests can drive it directly.
 */
fun parsePairPayload(raw: String?): kotlin.Pair<String, String>? {
    if (raw.isNullOrBlank()) return null
    val parts = raw.trim().split("|")
    if (parts.size != 3 || parts[0] != "BMN1") return null
    val url = parts[1].trim()
    val code = parts[2].trim()
    if (!url.startsWith("http://") && !url.startsWith("https://")) return null
    if (code.length != 6 || code.any { !it.isDigit() }) return null
    return kotlin.Pair(url, code)
}
