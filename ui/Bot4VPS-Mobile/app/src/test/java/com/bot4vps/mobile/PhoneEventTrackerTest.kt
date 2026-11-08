package com.bot4vps.mobile

import com.bot4vps.mobile.data.model.*
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class PhoneEventTrackerTest {
    private fun event(id: String, time: Int, type: String = "server", read: Boolean = false) = buildJsonObject {
        put("id", id); put("ts_epoch", time); put("type", type); put("read", read)
    }
    @Test fun firstOptInDoesNotReplayHistory() {
        val tracker = PhoneEventTracker(null)
        val old = event("old", 1)
        assertTrue(tracker.accept(listOf(old)).isEmpty())
        tracker.checkpoint(listOf(old))
        val fresh = event("new", 2)
        assertEquals(listOf(fresh), tracker.accept(listOf(fresh, old)))
    }
    @Test fun reconnectDeduplicatesAndDoesNotDependOnTelegramReadFlag() {
        val tracker = PhoneEventTracker(setOf("delivered"))
        val fresh = event("new", 2, read = true)
        val old = event("delivered", 1)
        assertEquals(listOf(fresh), tracker.accept(listOf(fresh, fresh, old)))
        val restored = PhoneEventTracker(tracker.checkpoint(listOf(fresh, old)))
        assertTrue(restored.accept(listOf(fresh, old)).isEmpty())
    }
    @Test fun sharedTimestampDoesNotLoseASecondEvent() {
        val tracker = PhoneEventTracker(setOf("first"))
        val second = event("second", 10)
        assertEquals(listOf(second), tracker.accept(listOf(second, event("first", 10))))
    }
    @Test fun localCategoriesUseTheEventType() {
        assertEquals("online", phoneEventCategory(event("a", 1)))
        assertEquals("tasks", phoneEventCategory(event("b", 1, "task")))
        assertEquals("ssl", phoneEventCategory(event("c", 1, "ssl")))
        assertEquals("system", phoneEventCategory(event("d", 1, "database")))
        assertEquals("backups", phoneEventCategory(event("e", 1, "backup")))
    }
}
