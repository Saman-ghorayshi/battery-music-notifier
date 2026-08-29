package com.saman.batterymusic

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Pure-JVM ApiClient tests: a local MockWebServer plays the worker, so the
 * same OkHttp path that ships in the APK runs against canned responses.
 */
class ApiClientTest {

    private fun client(server: MockWebServer): ApiClient =
        ApiClient(server.url("/").toString(), "device-token-123456")

    @Test
    fun pairLink_rejects_non_numeric_code_without_network() {
        val server = MockWebServer()
        server.start()
        val result = client(server).pairLink("12ab45")
        assertFalse(result.ok)
        assertEquals("invalid_code", result.error)
        server.shutdown()
    }

    @Test
    fun pairLink_stores_token_from_worker() {
        val server = MockWebServer()
        server.enqueue(
            MockResponse().setBody("""{"ok":true,"token":"linked-abc123"}""")
        )
        server.start()
        val result = client(server).pairLink("123456")
        assertTrue(result.ok)
        assertEquals("linked-abc123", result.token)
        // Subsequent calls must use the linked token, not the old one
        val recorded = server.takeRequest()
        assertEquals("Bearer device-token-123456", recorded.getHeader("Authorization"))
        assertEquals("123456", JSONObject(recorded.body.readUtf8()).getString("code"))
        server.shutdown()
    }

    @Test
    fun sendAlert_builds_expected_payload() {
        val server = MockWebServer()
        server.enqueue(MockResponse().setBody("""{"ok":true,"alert_type":"THIEF_ALERT"}"""))
        server.start()
        val result = client(server).sendAlert("THIEF_ALERT", 42, charging = false)
        assertTrue(result.ok)
        val body = JSONObject(server.takeRequest().body.readUtf8())
        assertEquals("THIEF_ALERT", body.getString("alert_type"))
        assertEquals(42, body.getInt("battery_pct"))
        assertEquals(false, body.getBoolean("is_charging"))
        server.shutdown()
    }

    @Test
    fun poll_parses_alert_and_snapshot_fields() {
        val server = MockWebServer()
        server.enqueue(
            MockResponse().setBody(
                """{"ok":true,"alert_active":1,"alert_type":"THIEF_ALERT",
                    "battery_pct":-1,"is_charging":0,"snapshot_id":7,
                    "snapshot_url":"/api/snapshot/7"}"""
            )
        )
        server.start()
        val state = client(server).poll()
        assertTrue(state!!.alertActive)
        assertEquals("THIEF_ALERT", state.alertType)
        assertEquals(-1, state.batteryPct)
        assertEquals(7L, state.snapshotId)
        server.shutdown()
    }

    @Test
    fun poll_returns_null_on_error_response() {
        val server = MockWebServer()
        server.enqueue(MockResponse().setResponseCode(401).setBody("""{"ok":false}"""))
        server.start()
        assertNull(client(server).poll())
        server.shutdown()
    }

    @Test
    fun fetchSnapshot_returns_bytes_on_200() {
        val server = MockWebServer()
        // A 3-byte fake JPEG (the real thing is ~40KB, magic is what matters)
        val jpeg = byteArrayOf(0xff.toByte(), 0xd8.toByte(), 0xff.toByte())
        server.enqueue(
            MockResponse()
                .setHeader("Content-Type", "image/jpeg")
                .setBody(okio.Buffer().write(jpeg))
        )
        server.start()
        val bytes = client(server).fetchSnapshot(7)
        assertTrue(jpeg.contentEquals(bytes))
        assertTrue(server.takeRequest().path!!.endsWith("/api/snapshot/7"))
        server.shutdown()
    }

    @Test
    fun fetchSnapshot_returns_null_on_404() {
        val server = MockWebServer()
        server.enqueue(MockResponse().setResponseCode(404).setBody("""{"ok":false}"""))
        server.start()
        assertNull(client(server).fetchSnapshot(999))
        server.shutdown()
    }
}

// ---------------------------------------------------------------------------
// v2.3: account-level arm/disarm + disarm pass
// ---------------------------------------------------------------------------

class ArmApiTest {

    private fun client(server: MockWebServer): ApiClient =
        ApiClient(server.url("/").toString(), "device-token-123456")

    @Test
    fun armAccount_true_sends_armed_payload() {
        val server = MockWebServer()
        server.enqueue(MockResponse().setBody("""{"ok":true,"armed":1}"""))
        server.start()
        val r = client(server).armAccount(true)
        assertTrue(r.ok)
        val body = JSONObject(server.takeRequest().body.readUtf8())
        assertEquals(true, body.getBoolean("armed"))
        assertFalse(body.has("pass_code"))
        server.shutdown()
    }

    @Test
    fun disarmAccount_carries_pass_when_set() {
        val server = MockWebServer()
        server.enqueue(MockResponse().setBody("""{"ok":true,"armed":0}"""))
        server.start()
        val r = client(server).armAccount(false, "1234")
        assertTrue(r.ok)
        val body = JSONObject(server.takeRequest().body.readUtf8())
        assertEquals(false, body.getBoolean("armed"))
        assertEquals("1234", body.getString("pass_code"))
        server.shutdown()
    }

    @Test
    fun disarmAccount_surfaces_pass_errors() {
        val server = MockWebServer()
        server.enqueue(MockResponse().setBody("""{"ok":false,"error":"invalid_pass"}"""))
        server.start()
        val r = client(server).armAccount(false, "0000")
        assertFalse(r.ok)
        assertEquals("invalid_pass", r.error)
        server.shutdown()
    }

    @Test
    fun setPass_first_time_has_no_current_field() {
        val server = MockWebServer()
        server.enqueue(MockResponse().setBody("""{"ok":true}"""))
        server.start()
        val r = client(server).setPass("hunter2")
        assertTrue(r.ok)
        val body = JSONObject(server.takeRequest().body.readUtf8())
        assertEquals("hunter2", body.getString("pass_code"))
        assertFalse(body.has("current_pass_code"))
        server.shutdown()
    }

    @Test
    fun poll_parses_armed_and_has_pass() {
        val server = MockWebServer()
        server.enqueue(
            MockResponse().setBody(
                """{"ok":true,"alert_active":0,"alert_type":"","battery_pct":50,
                    "is_charging":1,"snapshot_id":null,"armed":1,
                    "armed_by":"MyLaptop","has_pass":true}"""
            )
        )
        server.start()
        val state = client(server).poll()!!
        assertTrue(state.armed)
        assertEquals("MyLaptop", state.armedBy)
        assertTrue(state.hasPass)
        assertNull(state.snapshotId)
        server.shutdown()
    }
}
