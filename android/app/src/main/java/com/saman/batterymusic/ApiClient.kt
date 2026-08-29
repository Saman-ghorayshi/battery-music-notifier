package com.saman.batterymusic

import java.util.concurrent.TimeUnit
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject

/** Result of an API call. [error] carries the worker's own error string. */
data class ApiResult(val ok: Boolean, val error: String? = null, val token: String? = null)

/** One /api/poll answer: relay alert state plus the latest snapshot, if any. */
data class PollState(
    val alertActive: Boolean,
    val alertType: String,
    val batteryPct: Int,
    val isCharging: Boolean,
    val snapshotId: Long?,
    val armed: Boolean = false,
    val armedBy: String? = null,
    val hasPass: Boolean = false,
)

/**
 * HTTP client for the battery relay. Pure JVM on purpose: no android.* imports,
 * so the JVM unit tests and the PhoneSim runner drive the exact code that
 * ships in the APK. One instance per process; OkHttp pools connections.
 */
class ApiClient(private val workerUrl: String, private var token: String) {

    private val http = OkHttpClient.Builder()
        .connectTimeout(8, TimeUnit.SECONDS)
        .readTimeout(8, TimeUnit.SECONDS)
        .build()

    fun currentToken(): String = token

    private fun post(path: String, body: JSONObject): JSONObject {
        val request = Request.Builder()
            .url(workerUrl.trimEnd('/') + path)
            .header("Authorization", "Bearer $token")
            .post(body.toString().toRequestBody("application/json".toMediaType()))
            .build()
        return execute(request)
    }

    private fun get(path: String): okhttp3.Response {
        val request = Request.Builder()
            .url(workerUrl.trimEnd('/') + path)
            .header("Authorization", "Bearer $token")
            .get()
            .build()
        return http.newCall(request).execute()
    }

    private fun execute(request: Request): JSONObject {
        return try {
            http.newCall(request).execute().use { resp ->
                JSONObject(resp.body?.string() ?: "{}")
            }
        } catch (e: Exception) {
            JSONObject().put("ok", false).put("error", "network: ${e.message}")
        }
    }

    /** Join an account with a 6-digit code from the laptop. Token shown once. */
    fun pairLink(code: String): ApiResult {
        if (!code.matches(Regex("\\d{6}"))) {
            return ApiResult(false, "invalid_code")
        }
        val resp = post("/api/pair/link", JSONObject().put("code", code))
        val newToken = resp.optString("token", "")
        if (resp.optBoolean("ok") && newToken.isNotEmpty()) {
            token = newToken
            return ApiResult(true, token = newToken)
        }
        return ApiResult(false, resp.optString("error", "unknown"))
    }

    /** Send an alert. THIEF_ALERT is never user-rate-limited by the worker. */
    fun sendAlert(alertType: String, batteryPct: Int = -1, charging: Boolean = false): ApiResult {
        val body = JSONObject()
            .put("alert_type", alertType)
            .put("battery_pct", batteryPct)
            .put("is_charging", charging)
        val resp = post("/api/alert", body)
        return ApiResult(resp.optBoolean("ok"), resp.optString("error", "").ifEmpty { null })
    }

    fun clearAlert(): ApiResult {
        val resp = post("/api/clear", JSONObject())
        return ApiResult(resp.optBoolean("ok"), resp.optString("error", "").ifEmpty { null })
    }

    fun poll(): PollState? {
        return try {
            get("/api/poll").use { resp ->
                if (!resp.isSuccessful) return null
                val body = JSONObject(resp.body?.string() ?: return null)
                if (!body.optBoolean("ok")) return null
                PollState(
                    alertActive = body.optInt("alert_active") == 1,
                    alertType = body.optString("alert_type", ""),
                    batteryPct = body.optInt("battery_pct", -1),
                    isCharging = body.optInt("is_charging") == 1,
                    snapshotId = if (body.isNull("snapshot_id")) null else body.optLong("snapshot_id"),
                    armed = body.optInt("armed", 0) == 1,
                    armedBy = if (body.isNull("armed_by")) null else body.optString("armed_by"),
                    hasPass = body.optBoolean("has_pass", false),
                )
            }
        } catch (e: Exception) {
            null
        }
    }

    /** Download a snapshot's bytes, or null. Caller checks JPEG/PNG magic. */
    fun fetchSnapshot(snapshotId: Long): ByteArray? {
        return try {
            get("/api/snapshot/$snapshotId").use { resp ->
                if (!resp.isSuccessful) null else resp.body?.bytes()
            }
        } catch (e: Exception) {
            null
        }
    }

    // ---- Account arm/disarm (v2.3): the toggle drives the whole account ----

    /** Set (first time) or change the disarm pass. Pass lives only as a hash. */
    fun setPass(passCode: String, currentPassCode: String? = null): ApiResult {
        val body = JSONObject().put("pass_code", passCode)
        if (currentPassCode != null) body.put("current_pass_code", currentPassCode)
        val resp = post("/api/pass/setup", body)
        return ApiResult(resp.optBoolean("ok"), resp.optString("error", "").ifEmpty { null })
    }

    /** Arm the account freely; disarming needs the pass when one is set. */
    fun armAccount(armed: Boolean, passCode: String? = null): ApiResult {
        val body = JSONObject().put("armed", armed)
        if (passCode != null) body.put("pass_code", passCode)
        val resp = post("/api/arm", body)
        return ApiResult(resp.optBoolean("ok"), resp.optString("error", "").ifEmpty { null })
    }
}
