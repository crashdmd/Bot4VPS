package com.bot4vps.mobile

import com.bot4vps.mobile.data.model.*
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class PanelWorkflowsTest {
    @Test fun unsupportedPanelActionsHaveNoEntrypoints() {
        assertTrue(PanelWorkflows.views("backups").isEmpty())
        assertTrue(PanelWorkflows.actions("backups","catalog").isEmpty())
        assertTrue(PanelWorkflows.enabled("POST /api/backups/create"))
        assertTrue(PanelWorkflows.enabled("POST /api/settings/backup-password"))
        assertTrue(PanelWorkflows.enabled("GET /api/services/3x-ui/{server_id}/db-export"))
        assertFalse(PanelWorkflows.enabled("POST /api/setup/complete"))
        assertFalse(PanelWorkflows.enabled("GET /api/setup/status"))
        assertTrue(PanelWorkflows.enabled("POST /api/auth/recover"))
        assertTrue(PanelWorkflows.enabled("POST /api/auth/totp/setup"))
        assertTrue(PanelWorkflows.enabled("GET /api/servers/{server_id}/quick-setup"))
    }
    @Test fun fileActionsFollowDirectoryContext() {
        val root=PanelWorkflows.actions("files","docker").map { it.id }
        val project=PanelWorkflows.actions("files","docker",true).map { it.id }
        assertTrue("POST /api/files/docker/projects" in root)
        assertFalse("POST /api/files/docker/projects" in project)
        assertTrue("POST /api/files/docker/upload" in project)
        assertFalse("POST /api/files/docker/upload" in root)
        assertEquals(setOf("POST /api/keys/create","POST /api/files/upload"),PanelWorkflows.actions("files","keys").map { it.id }.toSet())
    }
    @Test fun helpersNeverBecomeSectionActions() {
        val ids=listOf("files","audit","events","queues","settings","update","telegram").flatMap { section-> PanelWorkflows.views(section).flatMap { PanelWorkflows.actions(section,it.id) } }.map { it.id }
        assertFalse(ids.any { it.startsWith("GET ") || it.contains("/status") || it.contains("/facets") || it.contains("/maintenance") })
        assertFalse("POST /api/events/mark-read" in ids)
    }
    @Test fun savingDoesNotRequireAnExtraConfirmationButRestartDoes() {
        val editor=NativeOperation("POST /api/files/write","POST","/api/files/write","files","Редактор")
        assertFalse(PanelWorkflows.confirm(editor))
        assertEquals("Сохранить",PanelWorkflows.button(editor))
        val port=NativeOperation("POST /api/settings/web/port","POST","/api/settings/web/port","settings","Порт")
        assertTrue(PanelWorkflows.confirm(port))
        assertTrue(PanelWorkflows.confirm(editor.copy(method="DELETE",destructive=true)))
    }
    @Test fun changingConnectionPreservesHostAndProxyPath() {
        val base="http://[2001:db8::1]:8080/panel/"
        assertEquals("http://[2001:db8::1]:8443/panel/",connectionTarget(base,"POST /api/settings/web/port",buildJsonObject { put("port",8443) }))
        assertEquals("https://[2001:db8::1]:8080/panel/",connectionTarget(base,"POST /api/settings/web/tls/self-signed",buildJsonObject { }))
        assertEquals(base,connectionTarget(base,"POST /api/settings/web/tls/proxy",buildJsonObject { }))
        assertFalse(connectionOperation("POST /api/settings/web/tls/upload"))
        assertTrue(runCatching { connectionTarget(base,"POST /api/settings/web/port",buildJsonObject { put("port",70000) }) }.isFailure)
    }
}
