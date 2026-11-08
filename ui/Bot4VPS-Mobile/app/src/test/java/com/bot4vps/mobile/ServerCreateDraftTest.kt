package com.bot4vps.mobile

import com.bot4vps.mobile.data.model.*
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class ServerCreateDraftTest {
    @Test fun onlyDomainsAreSuggestedForCertificates() {
        assertEquals("blackcow.ignorelist.com", certificateDomainFromHost(" BlackCow.IgnoreList.com. "))
        assertEquals("xn--e1afmkfd.xn--p1ai", certificateDomainFromHost("пример.рф"))
        listOf("192.0.2.10", "999.0.0.1", "2001:db8::1", "[2001:db8::1]", "localhost", "https://example.com", "-bad.example", "").forEach {
            assertNull(it, certificateDomainFromHost(it))
        }
    }
    @Test fun suggestionFollowsHostChangesAndDisappearsForAnIp() {
        val first = updateServerCreateField(JsonObject(emptyMap()), "host", JsonPrimitive("one.example.com"))
        assertEquals("one.example.com", first.text("ssl_host"))
        val second = updateServerCreateField(first, "host", JsonPrimitive("two.example.com"))
        assertEquals("two.example.com", second.text("ssl_host"))
        assertNull(updateServerCreateField(second, "host", JsonPrimitive("192.0.2.10")).text("ssl_host"))
    }
    @Test fun manuallyEnteredCertificateDomainSurvivesHostChanges() {
        val draft = buildJsonObject { put("host", "one.example.com"); put("ssl_host", "cert.example.org") }
        assertEquals("cert.example.org", updateServerCreateField(draft, "host", JsonPrimitive("192.0.2.10")).text("ssl_host"))
    }
    @Test fun certificateToggleDoesNotEraseTheDraftButControlsThePayload() {
        val draft = buildJsonObject { put("host", "one.example.com"); put("ssl_host", "one.example.com"); put("certificate_check", true) }
        val off = updateServerCreateField(draft, "certificate_check", JsonPrimitive(false))
        assertEquals("one.example.com", off.text("ssl_host"))
        assertEquals(JsonNull, serverCreatePayload(off)["ssl_host"])
        assertEquals("one.example.com", serverCreatePayload(updateServerCreateField(off, "certificate_check", JsonPrimitive(true))).text("ssl_host"))
    }
    @Test fun savingDoesNotAutomaticallyProbeSshAndKeepsTheSudoPassword() {
        val draft = buildJsonObject { put("auth_type", "key"); put("key_path", "/opt/bot4vps/keys/id_ed25519"); put("password", "sudo-password"); put("test", true) }
        val payload = serverCreatePayload(draft)
        assertFalse(payload.flag("test"))
        assertEquals("sudo-password", payload.text("password"))
        assertEquals(draft["key_path"], payload["key_path"])
        assertEquals(JsonNull, serverCreatePayload(JsonObject(draft + ("auth_type" to JsonPrimitive("password"))))["key_path"])
    }
}
