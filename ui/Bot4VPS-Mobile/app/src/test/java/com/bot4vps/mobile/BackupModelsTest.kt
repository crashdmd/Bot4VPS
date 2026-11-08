package com.bot4vps.mobile

import com.bot4vps.mobile.data.model.*
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class BackupModelsTest {
    private fun obj(raw: String) = Json.parseToJsonElement(raw).jsonObject
    @Test fun catalogNeverMixesPanelServerOrImportedNamespaces() {
        val data=obj("""{"catalog":[{"backup_id":"same","type":"bot4vps"},{"backup_id":"same","type":"server","source":{"server_id":"a"}},{"backup_id":"b","type":"server","source":{"server_id":"b"}}],"imported_archives":[{"entry_key":"same","destination":{"scope":"bot4vps"}},{"entry_key":"same","destination":{"scope":"server","server_id":"a"}}]}""")
        assertEquals(listOf("backup:same","import:same"),BackupArchive.list(data,null).map { it.key })
        val rows=BackupArchive.list(data,"a")
        assertEquals(listOf("backup:same","import:same"),rows.map { it.key })
        assertTrue(rows.all { it.serverId=="a" && it.query==mapOf("server_id" to listOf("a")) })
        assertTrue(BackupArchive.list(data,"unknown").isEmpty())
    }
    @Test fun editorKeepsExclusionsLimitsAndUnknownScheduleOptions() {
        val old=obj("""{"schema_version":1,"sources":[{"path":"/etc","exclusions":["cache/*"]},{"path":"/home","exclusions":[]}],"limits":{"max_source_bytes":123},"automatic":{"enabled":false,"daily_time":"04:00","keep_last":3,"timezone":"old","future":true},"notifications":{"backup":{"error":true}},"encrypt":true}""")
        val result=backupSettingsDraft(old,true,listOf(" /etc ","/var/lib", "/etc"),true,"05:30",7,true)
        assertEquals(old["limits"],result["limits"])
        assertEquals(old["notifications"],result["notifications"])
        assertEquals(old.objects("sources").first(),result.objects("sources").first())
        assertEquals(2,result.objects("sources").size)
        assertNull(result.objects("sources").find { it.text("path")=="/home" })
        assertTrue((result["automatic"] as JsonObject).flag("future"))
        assertNull((result["automatic"] as JsonObject)["timezone"])
    }
    @Test fun invalidSourceOrScheduleCannotEnableAutomaticEmptyArchive() {
        assertTrue(runCatching { backupSettingsDraft(null,true,emptyList(),true,"03:00",7,false) }.isFailure)
        assertTrue(runCatching { backupSettingsDraft(null,true,listOf("/etc/../home"),false,"03:00",7,false) }.isFailure)
        assertTrue(runCatching { backupSettingsDraft(null,false,emptyList(),true,"25:00",7,false) }.isFailure)
        assertTrue(runCatching { backupSettingsDraft(null,false,emptyList(),true,"03:00",0,false) }.isFailure)
    }
    @Test fun prepareDoesNotApplyOrSendUnnecessaryTarget() {
        val options=BackupRestoreOptions(mode="clean",protective=false,partial=true,selected=setOf("/etc"),password="once")
        val body=options.prepare(false)
        assertFalse(body.flag("apply"))
        assertFalse(body.flag("confirm"))
        assertNull(body["target_root"])
        assertEquals("selected",body.text("selection_mode"))
        assertEquals("once",body.text("password"))
        assertTrue(runCatching { options.copy(selected=emptySet()).prepare(false) }.isFailure)
        assertTrue(runCatching { options.copy(root="/").prepare(true) }.isFailure)
    }
    @Test fun applyCannotResendMutablePreparationParameters() {
        val body=RestoreRequests.apply("prepared-1",JsonPrimitive("once"),false)
        assertEquals("prepared-1",body.text("prepared_operation_id"))
        assertTrue(body.flag("apply") && body.flag("confirm") && body.flag("confirm_without_protective"))
        listOf("target_root","selection_mode","selected_paths","restore_mode","protective_backup").forEach { assertNull(body[it]) }
        assertTrue(runCatching { RestoreRequests.apply("",null,true) }.isFailure)
    }
    @Test fun completedOperationWithoutServerPlanCannotBeApplied() {
        assertFalse(backupPrepared(obj("""{"operation_id":"a","status":"completed","stage":"done"}""")))
        assertFalse(backupPrepared(obj("""{"operation_id":"a","status":"running","stage":"prepared","restore":{"plan":{}}}""")))
        assertFalse(backupPrepared(obj("""{"operation_id":"a","status":"completed","stage":"prepared"}""")))
        assertTrue(backupPrepared(obj("""{"operation_id":"a","type":"restore","status":"completed","stage":"prepared","restore":{"selection":{"version":3,"source":{}},"plan":{"mode":"merge","replace":[],"delete":null,"counts":{"replace":0,"delete":null}}}}""")))
    }
    @Test fun generalAuditNeverUsesFirstAutomaticallySelectedServer() {
        assertNull(auditNavigationServer(null,"first",false))
        assertNull(auditInitialServer("null"))
        assertNull(auditInitialServer(""))
        assertEquals("from-card",auditNavigationServer("from-card","first",false))
        assertEquals("chosen",auditNavigationServer(null,"chosen",true))
    }
    @Test fun migrationCountsAsInstalledAndNeverAsAbsent() {
        val classic=ServiceServer("s","WG","host",status=obj("""{"installed":false,"needs_migration":true}"""))
        assertTrue(classic.installed)
        assertEquals(listOf(classic),filterServiceServers(listOf(classic),InstallationFilter.INSTALLED,"",null))
        assertEquals(listOf(classic),filterServiceServers(listOf(classic),InstallationFilter.CLASSIC,"",null))
        assertTrue(filterServiceServers(listOf(classic),InstallationFilter.ABSENT,"",null).isEmpty())
    }
}
