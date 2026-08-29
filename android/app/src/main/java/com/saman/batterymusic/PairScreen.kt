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
fun PairScreen(prefs: Prefs, onPaired: () -> Unit) {
    var workerUrl by remember { mutableStateOf(prefs.workerUrl) }
    var code by remember { mutableStateOf("") }
    var status by remember { mutableStateOf("") }
    var pairing by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("Pair with your laptop", style = androidx.compose.material3.MaterialTheme.typography.headlineSmall)
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
            onClick = {
                pairing = true
                status = "Pairing..."
                scope.launch {
                    prefs.workerUrl = workerUrl
                    val result = withContext(Dispatchers.IO) {
                        ApiClient(workerUrl, prefs.token).pairLink(code)
                    }
                    pairing = false
                    if (result.ok && result.token != null) {
                        prefs.token = result.token
                        onPaired()
                    } else {
                        status = "Failed: ${result.error}"
                    }
                }
            },
            enabled = !pairing && code.length == 6,
            modifier = Modifier.fillMaxWidth(),
        ) { Text("PAIR") }

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
