package com.bot4vps.mobile

import com.bot4vps.mobile.data.model.*
import com.bot4vps.mobile.ui.servers.ServersUiState
import org.junit.Assert.*
import org.junit.Test

class GroupDisplaySettingsTest {
    @Test fun catalogIncludesEmptyGroups() {
        val state=ServersUiState(catalogGroups=listOf("Пустая","Рабочая"))
        assertEquals(listOf("Пустая","Рабочая"),state.groups)
        assertTrue(state.copy(selectedGroup="Пустая").filtered.isEmpty())
    }
    @Test fun orderVisibilityAndRenameDoNotLoseNewGroups() {
        val settings=GroupDisplaySettings(listOf("Б","А"),setOf("А"))
        assertEquals(listOf("Б","В"),settings.visible(listOf("А","Б","В")))
        val renamed=settings.renamed("А","Г")
        assertEquals(listOf("Б","Г","В"),renamed.visible(listOf("Г","Б","В")))
        assertFalse("А" in renamed.order)
        assertTrue(renamed.deleted("Б").order.none { it=="Б" })
    }
    @Test fun defaultAndOldSystemSettingBecomeDark() {
        assertEquals("dark",normalizePanelTheme(null))
        assertEquals("dark",normalizePanelTheme("system"))
        listOf("dark","light","glass").forEach { assertEquals(it,normalizePanelTheme(it)) }
    }
}
