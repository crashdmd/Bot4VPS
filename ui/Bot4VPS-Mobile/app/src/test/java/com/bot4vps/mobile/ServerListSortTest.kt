package com.bot4vps.mobile

import com.bot4vps.mobile.data.model.*
import kotlinx.serialization.json.Json
import org.junit.Assert.*
import org.junit.Test

class ServerListSortTest {
    @Test fun uptimeUsesSecondsRatherThanFormattedText() {
        val rows = listOf(ServerSummary("short", uptime = "9 ч.", uptimeSeconds = 32400.0),
            ServerSummary("long", uptime = "2 д.", uptimeSeconds = 172800.0))
        assertEquals(listOf("short", "long"), sortServerList(rows, ServerListSort.UPTIME, false).map { it.id })
    }

    @Test fun namesIgnoreCaseAndEqualValuesKeepTheirOrder() {
        val rows = listOf(ServerSummary("a", name = "beta"), ServerSummary("b", name = "ALPHA"), ServerSummary("c", name = "alpha"))
        assertEquals(listOf("b", "c", "a"), sortServerList(rows, ServerListSort.NAME, false).map { it.id })
    }

    @Test fun onlineWithSshErrorStillSortsWithOnlineServers() {
        val rows = listOf(ServerSummary("offline", online = false), ServerSummary("unknown"),
            ServerSummary("online", online = true, sshError = "Нет ключа"))
        assertEquals(listOf("online", "offline", "unknown"), sortServerList(rows, ServerListSort.STATUS, false).map { it.id })
    }

    @Test fun missingCertificateDurationDoesNotLookLikeAnExpiredCertificate() {
        val rows = listOf(ServerSummary("unknown"), ServerSummary("expired", sslDaysLeft = -2), ServerSummary("valid", sslDaysLeft = 10))
        assertEquals(listOf("valid", "expired", "unknown"), sortServerList(rows, ServerListSort.SSL, true).map { it.id })
    }

    @Test fun summaryAcceptsFractionalUptimeFromTheExistingApi() {
        val server = Json.decodeFromString<ServerSummary>("""{"id":"host","uptime_seconds":86400.5}""")
        assertEquals(86400.5, server.uptimeSeconds!!, 0.0)
        assertNull(Json.decodeFromString<ServerSummary>("""{"id":"host"}""").uptimeSeconds)
    }
}
