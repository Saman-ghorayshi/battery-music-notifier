package com.saman.batterymusic

import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.MediaType.Companion.toMediaType
import org.json.JSONObject

/**
 * Plain-JVM twin of the phone side, for end-to-end testing WITHOUT an
 * emulator. It calls the SAME ApiClient.kt the APK ships, against the real
 * worker, and prints every step:
 *
 *   kotlinc ApiClient.kt PhoneSim.kt -cp okhttp.jar:json.jar -d phonesim
 *   java -cp phonesim.jar:okhttp.jar:okio.jar:kotlin-stdlib.jar:json.jar \
 *       com.saman.batterymusic.PhoneSimKt <worker_url> <6-digit-code> [steps]
 *
 * steps: pair|test|watch|snap (default: run the full pair->test->watch tour)
 */
fun main(args: Array<String>) {
    val workerUrl = args.getOrNull(0) ?: error("usage: PhoneSim <worker_url> <code> [pair|test|watch|snap]")
    val code = args.getOrNull(1) ?: error("usage: PhoneSim <worker_url> <code> [pair|test|watch|snap]")
    val steps = (args.getOrNull(2) ?: "all").split(",")

    // The phone joins an EXISTING account, so pairing hands us the linked
    // token; anything before that (register) is the laptop's job.
    val prefsToken = args.getOrNull(3) ?: ""
    val client = ApiClient(workerUrl, prefsToken)

    if (steps.contains("all") || steps.contains("pair")) {
        println("[1] pairing with code $code ...")
        val result = client.pairLink(code)
        if (!result.ok) {
            println("    PAIR FAILED: ${result.error}")
            kotlin.system.exitProcess(1)
        }
        println("    paired, token: ${result.token?.take(8)}... (shown once, keep it)")
    }

    if (steps.contains("all") || steps.contains("test")) {
        println("[2] sending THIEF_ALERT (test) ...")
        val result = client.sendAlert("THIEF_ALERT", 42, false)
        println("    alert sent: ok=${result.ok} ${result.error ?: ""}")
        println("    -> laptop side should ring now; press Ctrl+C to end watching")
    }

    if (steps.contains("all") || steps.contains("watch") || steps.contains("snap")) {
        println("[3] polling every 5s (Ctrl+C to stop) ...")
        while (true) {
            val state = client.poll()
            if (state != null) {
                print("    alert=${state.alertActive} type=${state.alertType} battery=${state.batteryPct}")
                if (state.snapshotId != null) print(" snapshot=${state.snapshotId}")
                println()
                if (state.snapshotId != null && (steps.contains("snap") || steps.contains("all"))) {
                    val bytes = client.fetchSnapshot(state.snapshotId!!)
                    val isJpeg = bytes != null && bytes.size > 3 &&
                        bytes[0] == 0xFF.toByte() && bytes[1] == 0xD8.toByte()
                    println("    fetched snapshot: ${bytes?.size ?: 0} bytes, jpeg=$isJpeg")
                }
                if (state.alertActive && state.alertType == "THIEF_ALERT") {
                    println("    >>> RING RING - laptop raised a thief alert <<<")
                    // Mirror the real app: acknowledge and clear after ringing once
                    val cleared = client.clearAlert()
                    println("    cleared: ok=${cleared.ok}")
                }
            } else {
                println("    poll failed (network?)")
            }
            Thread.sleep(5_000)
        }
    }
}
