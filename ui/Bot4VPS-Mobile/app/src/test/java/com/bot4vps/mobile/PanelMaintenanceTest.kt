package com.bot4vps.mobile

import com.bot4vps.mobile.data.model.*
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class PanelMaintenanceTest {
    private val run=MaintenanceRun("op-1","update","1.2.3","old",1)
    private fun panel(instance:String="old",version:String="1.2.3",phase:String?=null,id:String="op-1")=buildJsonObject {
        put("instance_id",instance); put("version",version)
        if(phase!=null) put("maintenance",buildJsonObject { put("id",id); put("phase",phase); put("remaining_seconds",10) })
    }
    private fun updater(status:String="idle",version:String="1.2.3")=buildJsonObject { put("status",status); put("current_version",version) }
    @Test fun unchangedProcessCannotProveCompletionAfterLostResponse() {
        assertEquals(MaintenancePhase.EXECUTING,maintenanceDecision(run,panel(),updater()).phase)
        assertEquals(MaintenancePhase.DONE,maintenanceDecision(run,panel("new"),updater()).phase)
        assertEquals(MaintenancePhase.DONE,maintenanceDecision(run.copy(seenBusy=true),panel(),updater()).phase)
    }
    @Test fun bothVersionsMustMatchRequestedTarget() {
        assertEquals(MaintenancePhase.EXECUTING,maintenanceDecision(run,panel("new","1.2.2"),updater()).phase)
        assertEquals(MaintenancePhase.EXECUTING,maintenanceDecision(run,panel("new"),updater(version="1.2.2")).phase)
        assertTrue(samePanelVersion("v1.2.3","1.2.3"))
        assertFalse(samePanelVersion("1.2.3-rc1","1.2.3"))
        assertFalse(samePanelVersion("1.2.3.4","1.2.3"))
    }
    @Test fun onlyOurPreparationCanBeCancelledOrCountedAsWaiting() {
        assertEquals(MaintenancePhase.WAITING,maintenanceDecision(run,panel(phase="waiting"),updater()).phase)
        assertEquals(10,maintenanceDecision(run,panel(phase="waiting"),updater()).remaining)
        assertEquals(MaintenancePhase.CANCELLED,maintenanceDecision(run,panel(phase="cancelled"),updater()).phase)
        assertEquals(MaintenancePhase.EXECUTING,maintenanceDecision(run,panel(phase="waiting",id="other"),updater()).phase)
    }
    @Test fun oldUpdaterFailureCannotFalselyFailNewRequest() {
        assertEquals(MaintenancePhase.EXECUTING,maintenanceDecision(run,panel(),updater("failed")).phase)
        assertEquals(MaintenancePhase.FAILED,maintenanceDecision(run.copy(seenBusy=true),panel(),updater("failed")).phase)
        assertEquals(MaintenancePhase.FAILED,maintenanceDecision(run,panel(phase="failed"),updater()).phase)
    }
    @Test fun restartNeedsNewProcessAndIgnoresAnOldUpdateFailure() {
        val restart = run.copy(kind = "restart")
        assertEquals(MaintenancePhase.EXECUTING, maintenanceDecision(restart, panel(), updater("failed")).phase)
        assertEquals(MaintenancePhase.DONE, maintenanceDecision(restart, panel("new"), updater("failed")).phase)
        assertEquals(MaintenancePhase.DONE, maintenanceDecision(restart, panel("new", "1.2.2"), updater()).phase)
    }
    @Test fun restartLoadsManuallyUpdatedSourcesWithoutRequiringTheOldVersion() {
        val restart = run.copy(kind = "restart", target = "6.3.1")
        assertEquals(MaintenancePhase.EXECUTING, maintenanceDecision(restart, panel(version = "6.4.0"), updater()).phase)
        assertEquals(MaintenancePhase.DONE, maintenanceDecision(restart, panel("new", "6.4.0"), updater()).phase)
        assertEquals(MaintenancePhase.EXECUTING, maintenanceDecision(restart, panel("", "6.4.0"), updater()).phase)
        assertEquals(MaintenancePhase.EXECUTING, maintenanceDecision(restart.copy(instance = ""), panel("new", "6.4.0"), updater()).phase)
    }
    @Test fun rollbackStillRequiresBothVersionsToMatchItsTarget() {
        val rollback = run.copy(kind = "rollback")
        assertEquals(MaintenancePhase.EXECUTING, maintenanceDecision(rollback, panel("new", "6.4.0"), updater()).phase)
        assertEquals(MaintenancePhase.EXECUTING, maintenanceDecision(rollback, panel("new"), updater(version = "6.4.0")).phase)
        assertEquals(MaintenancePhase.DONE, maintenanceDecision(rollback, panel("new"), updater()).phase)
    }
    @Test fun unreadableTaskPreviewIsNeverTreatedAsEmpty() {
        assertTrue(runCatching { maintenanceTaskWarning(buildJsonObject { put("instance_id","old") }) }.isFailure)
        val queued=buildJsonObject { put("instance_id","old"); put("tasks",buildJsonObject { put("running",JsonArray(emptyList())); put("queued",2); put("grace_seconds",30) }) }
        assertTrue(maintenanceTaskWarning(queued).contains("В очереди: 2"))
        assertTrue(maintenanceTaskWarning(queued).contains("автоматически не возобновятся"))
    }
}
