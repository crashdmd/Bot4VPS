package com.bot4vps.mobile

import com.bot4vps.mobile.data.model.*
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class AuditRecordTest {
    @Test fun actorAndServerAreReadFromNestedObjects() {
        val data=Json.parseToJsonElement("""{"started_at":100,"ts":90,"actor":{"type":"web","id":"user","role":"admin","ip":"127.0.0.1"},"server":{"id":"deleted","name":"Удалённый сервер"}}""").jsonObject
        assertEquals(100L,data.auditStart())
        assertEquals("Удалённый сервер",auditServer(data))
        assertEquals("Веб: user · admin",auditActor(data))
        assertTrue(auditActor(data,true).endsWith("127.0.0.1"))
    }
    @Test fun incompleteAndRuleSelectionOverrideAStaleResult() {
        assertEquals("incomplete",auditResult(Json.parseToJsonElement("""{"status":"incomplete","result":"ok"}""").jsonObject))
        assertEquals("awaiting_rule_selection",auditResult(Json.parseToJsonElement("""{"status":"waiting_rule_selection","result":"ok"}""").jsonObject))
        assertNull(auditDuration(-1.0)); assertNull(auditDuration(Double.NaN))
        assertEquals("1 ч 1 мин",auditDuration(3660.0))
    }
    @Test fun defaultsAndFiltersUseTheSameWindowForCursorPages() {
        val filter=AuditFilters(actor="web:user:with:colon",server="deleted",result="incomplete",search=" error ")
        val query=filter.query(1_000_000)
        assertEquals(listOf("395200"),query["from"])
        assertEquals(listOf("1000000"),query["to"])
        assertEquals(listOf("web"),query["actor_type"])
        assertEquals(listOf("user:with:colon"),query["actor_id"])
        assertEquals(listOf("deleted"),query["server_id"])
        assertEquals(listOf("error"),query["q"])
        assertEquals(listOf("50"),query["limit"])
        val next=query+("cursor" to listOf("opaque"))
        assertEquals(query["to"],next["to"])
    }
    @Test fun badWindowsAndOversizedSearchAreRejectedBeforeRequest() {
        assertThrows(IllegalArgumentException::class.java) { AuditFilters(from=20,to=10).query(30) }
        assertThrows(IllegalArgumentException::class.java) { AuditFilters(search="x".repeat(201)).query(30) }
    }
}
