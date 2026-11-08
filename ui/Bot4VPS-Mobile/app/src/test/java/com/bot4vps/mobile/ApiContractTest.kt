package com.bot4vps.mobile

import com.bot4vps.mobile.data.api.PanelUrl
import com.bot4vps.mobile.data.api.encodeSegment
import com.bot4vps.mobile.data.model.*
import com.bot4vps.mobile.ui.terminal.TerminalBuffer
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class ApiContractTest {
    private val json = Json { ignoreUnknownKeys = true }

    @Test fun sessionUsesServerUserFieldAndAllowsAuthOff() {
        val signedIn = json.decodeFromString<MeResponse>("""{"auth_enabled":true,"user":"admin","theme":"dark"}""")
        assertTrue(signedIn.authenticated)
        assertEquals("admin",signedIn.username)
        assertFalse(json.decodeFromString<MeResponse>("""{"auth_enabled":true,"user":null}""").authenticated)
        assertTrue(json.decodeFromString<MeResponse>("""{"auth_enabled":false,"user":null}""").authenticated)
    }

    @Test fun enqueueReadsNestedTaskFromExistingApi() {
        val response = json.decodeFromString<EnqueueResponse>("""{"ok":true,"task":{"id":"task-1","name":"backup.sh","status":"queued"},"position":2,"ahead":1}""")
        assertEquals("task-1",response.task?.id)
        assertEquals(2,response.position)
        assertEquals(3,json.decodeFromString<SummaryResponse>("""{"ok":true,"servers":3,"running_tasks":1}""").servers)
    }

    @Test fun panelAddressPreservesProxyPrefixAndEncodesQueries() {
        val url = PanelUrl.endpoint("https://example.com:8443/panel/", "/api/files/read",mapOf("name" to listOf("a b.sh")))
        assertEquals("/panel/api/files/read",url.encodedPath)
        assertEquals(8443,url.port)
        assertEquals("a b.sh",url.queryParameter("name"))
        assertEquals("a%2Fb%20c",encodeSegment("a/b c"))
    }

    @Test fun panelAddressRejectsCredentialsAndPageUrls() {
        assertTrue(runCatching { PanelUrl.normalize("https://admin:password@example.com") }.isFailure)
        assertTrue(runCatching { PanelUrl.normalize("https://example.com/?page=servers") }.isFailure)
        assertTrue(runCatching { PanelUrl.normalize("file:///etc/passwd") }.isFailure)
    }

    @Test fun restoreApplyDoesNotResubmitPreparationFields() {
        val body = RestoreRequests.apply("op-1",JsonPrimitive("secret"),false)
        assertEquals(JsonPrimitive("op-1"),body["prepared_operation_id"])
        assertEquals(JsonPrimitive(true),body["confirm_without_protective"])
        assertEquals(JsonPrimitive(true),body["apply"])
        assertFalse(body.containsKey("restore_mode"))
        assertFalse(body.containsKey("selected_paths"))
        assertFalse(body.containsKey("protective_backup"))
        assertTrue(runCatching { RestoreRequests.apply("",null,true) }.isFailure)
    }

    @Test fun nativeFormValidatesNestedRequiredFieldsAndMasksSecrets() {
        val schema = json.parseToJsonElement("""{"type":"object","required":["port","password"],"properties":{"port":{"type":"integer","title":"Порт","minimum":1,"maximum":65535},"password":{"type":"string","secret":true,"minLength":10}}}""").jsonObject
        assertNotNull(NativeForm.validate(schema,json.parseToJsonElement("""{"port":0,"password":"long-password"}""")))
        assertNotNull(NativeForm.validate(schema,json.parseToJsonElement("""{"port":22}""")))
        val valid = json.parseToJsonElement("""{"port":22,"password":"long-password"}""")
        assertNull(NativeForm.validate(schema,valid))
        assertEquals(JsonPrimitive("••••••"),(NativeForm.redact(schema,valid) as JsonObject)["password"])
    }

    @Test fun terminalCarriesEscapeSequenceAcrossNetworkFrames() {
        val terminal=TerminalBuffer(20,6)
        terminal.append("old\u001b[")
        terminal.append("2J\u001b[Hnew")
        assertEquals("new",terminal.lines()[0])
        terminal.append("\rOK\u001b[K")
        assertEquals("OK",terminal.lines()[0])
    }

    @Test fun optionalObjectsAreOmittedInsteadOfSubmittingEmptyContinuation() {
        val schema = json.parseToJsonElement("""{"type":"object","properties":{"continuation":{"type":"object","nullable":true},"selected_rules":{"type":"array","nullable":true,"items":{"type":"string"}},"encrypt":{"type":"boolean","nullable":true}}}""").jsonObject
        assertEquals(JsonObject(emptyMap()),NativeForm.initial(schema))
    }

    @Test fun probeUsesNestedSshStatusRatherThanMissingOkFlag() {
        val response = json.decodeFromString<ProbeResponse>("""{"info":{"ssh":true,"hostname":"vps","os":"Ubuntu"},"ssh_error_human":"","host_key_mismatch":false}""")
        assertTrue(response.info?.ssh == true)
        assertEquals("vps", response.info?.hostname)
    }

    @Test fun explicitClearAcceptsNullableObjectsAndRejectsRequiredNumbers() {
        val nullable = json.parseToJsonElement("""{"type":"object","nullable":true,"properties":{"path":{"type":"string"}},"required":["path"]}""").jsonObject
        assertNull(NativeForm.validate(nullable, JsonNull))
        assertNotNull(NativeForm.validate(json.parseToJsonElement("""{"type":"integer"}""").jsonObject, JsonNull, "Порт"))
    }

    @Test fun terminalRestoresCursorSafelyAfterResize() {
        val terminal = TerminalBuffer(80, 24)
        terminal.append("\u001b[24;80H\u001b7")
        terminal.resize(20, 6)
        terminal.append("\u001b8X")
        assertEquals('X', terminal.cells[5][19].char)
    }
}
