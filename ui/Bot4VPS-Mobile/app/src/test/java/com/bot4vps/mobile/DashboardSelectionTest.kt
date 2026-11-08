package com.bot4vps.mobile

import com.bot4vps.mobile.data.model.ServerSummary
import com.bot4vps.mobile.ui.dashboard.pickDashboardServers
import org.junit.Assert.*
import org.junit.Test

class DashboardSelectionTest {
    @Test fun problemsAreIncludedBeforeHealthyServersAndSelectionIsBounded() {
        val healthy = (1..10).map { ServerSummary("healthy$it", online = true) }
        val problems = listOf(ServerSummary("offline", online = false), ServerSummary("ssh", online = true, sshError = "auth"))
        repeat(20) {
            val selected = pickDashboardServers(healthy + problems)
            assertEquals(6, selected.size)
            assertEquals(problems.map { it.id }.toSet(), selected.take(2).map { it.id }.toSet())
            assertEquals(6, selected.map { it.id }.distinct().size)
        }
    }
    @Test fun emptyAndSmallInventoriesRemainComplete() {
        assertTrue(pickDashboardServers(emptyList()).isEmpty())
        val servers = listOf(ServerSummary("one", online = true), ServerSummary("two", online = false))
        assertEquals(servers.map { it.id }.toSet(), pickDashboardServers(servers).map { it.id }.toSet())
    }
}
