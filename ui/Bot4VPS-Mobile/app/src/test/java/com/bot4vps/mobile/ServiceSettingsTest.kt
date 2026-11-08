package com.bot4vps.mobile

import com.bot4vps.mobile.data.model.*
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class ServiceSettingsTest {
    private val json = Json { ignoreUnknownKeys = true }
    private fun obj(value: String) = json.parseToJsonElement(value).jsonObject

    @Test fun networkAvailabilityDoesNotOverrideReachableSshPort() {
        val reachable = ServiceServer.parse(obj("""{"id":"srv","online":false,"port_ok":true,"status":{"installed":true}}"""))!!
        assertFalse(reachable.blocked)
        assertTrue(reachable.installed)
        val unknownPort = reachable.copy(portOk = null)
        assertTrue(unknownPort.blocked)
        assertTrue(reachable.copy(online = true, portOk = false).blocked)
    }

    @Test fun installationFiltersIncludeUnavailableInstalledServers() {
        val installed = ServiceServer("1", "VPN", "10.0.0.1", "Home", false, false, obj("""{"installed":true}"""))
        val absent = ServiceServer("2", "New", "10.0.0.2", "Work")
        val classic = installed.copy(id = "3", status = obj("""{"installed":true,"needs_migration":true}"""))
        val rows = listOf(installed, absent, classic)
        assertEquals(listOf(installed, classic), filterServiceServers(rows, InstallationFilter.INSTALLED, " vpn ", "Home"))
        assertEquals(listOf(absent), filterServiceServers(rows, InstallationFilter.ABSENT, "", null))
        assertEquals(listOf(classic), filterServiceServers(rows, InstallationFilter.CLASSIC, "", null))
        assertEquals(listOf(installed, classic), filterServiceServers(rows, InstallationFilter.BLOCKED, "", null))
    }

    @Test fun disabledMonitoringAndCategoryUseDifferentConfigurationKeys() {
        val settings = NotificationSettings(obj("""{"online":{"enabled":false,"interval":5},"ssl":{"enabled":true,"interval":720}}"""), obj("""{"tasks":false}"""), true, null)
        val online = notificationCategories.first { it.name == "online" }
        val tasks = notificationCategories.first { it.name == "tasks" }
        assertFalse(settings.enabled(online))
        assertFalse(settings.enabled(tasks))
        assertTrue(settings.withEnabled(online, true).enabled(online))
        assertFalse(settings.withEnabled(online, true).enabled(tasks))
        assertEquals(5, settings.withEnabled(online, true).interval("online"))
        assertEquals(720, settings.interval("ssl"))
    }

    @Test fun telegramStatusUsesRuntimeAndKnownDeliveryFailures() {
        assertNull(telegramDeliveryIssue(null))
        assertNull(telegramDeliveryIssue(obj("""{"enabled":true,"status":{"state":"running"}}""")))
        assertNotNull(telegramDeliveryIssue(obj("""{"enabled":false,"status":{"state":"running"}}""")))
        assertNotNull(telegramDeliveryIssue(obj("""{"status":{"state":"running"},"health":{"ok":false,"code":"BOT_BLOCKED","reason":"Бот заблокирован"}}""")))
        assertNull(telegramDeliveryIssue(obj("""{"status":{"state":"running"},"health":{"ok":false,"code":"OTHER"}}""")))
    }

    @Test fun serverDetailDecodesQueueAndCachedSystem() {
        val detail = json.decodeFromString<ServerDetailResponse>("""{"server":{"id":"s"},"monitor":{"system":{"os":"Ubuntu"},"availability":{"online":true,"port_ok":false}},"queue":[{"id":"task-1"}],"queue_state":{"paused":true}}""")
        assertTrue(detail.queueState.flag("paused"))
        assertEquals("task-1", detail.queue.single().id)
        assertEquals("Ubuntu", ((detail.monitor as JsonObject)["system"] as JsonObject).text("os"))
    }
    @Test fun backgroundUpdatesRetainServerOrderAcrossStatusChanges() {
        assertEquals(listOf("a", "b", "c"), retainServerOrder(listOf("a", "b", "c"), listOf("c", "b", "a")))
        assertEquals(listOf("b", "c", "d"), retainServerOrder(listOf("a", "b", "c"), listOf("d", "c", "b")))
    }

    @Test fun exportRequiresAtLeastOneSelectedProfile() {
        val schema = obj("""{"type":"array","minItems":1,"items":{"type":"string"}}""")
        assertNotNull(NativeForm.validate(schema, JsonArray(emptyList()), "Профили"))
        assertNull(NativeForm.validate(schema, JsonArray(listOf(JsonPrimitive("client"))), "Профили"))
    }

}
