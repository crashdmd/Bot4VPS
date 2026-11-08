package com.bot4vps.mobile.ui.settings

import androidx.compose.runtime.*
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.bot4vps.mobile.data.api.*
import com.bot4vps.mobile.data.local.PreferencesManager
import com.bot4vps.mobile.data.model.*
import com.bot4vps.mobile.data.repository.checkedObject
import com.bot4vps.mobile.data.repository.checkPanelUpdate
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.first
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.*
import java.util.UUID
import javax.inject.Inject

data class VersionNotes(val version: String, val text: String, val current: Boolean = false)
data class UpdateConfirmation(val kind: String, val notes: VersionNotes, val preview: JsonObject)

@HiltViewModel
class UpdatesViewModel @Inject constructor(private val panel: NativePanelClient, private val prefs: PreferencesManager) : ViewModel() {
    var update by mutableStateOf<JsonObject?>(null); private set
    var automatic by mutableStateOf(false); private set
    var busy by mutableStateOf(false); private set
    var error by mutableStateOf<String?>(null); private set
    var message by mutableStateOf<String?>(null); private set
    var latest by mutableStateOf(false); private set
    fun dismissLatest() { latest = false }
    fun acceptSnapshot(state: JsonObject?) { if (state != null && !busy && run == null && confirmation == null) update = state }
    var notes by mutableStateOf<VersionNotes?>(null); private set
    var versions by mutableStateOf<List<String>?>(null); private set
    var confirmation by mutableStateOf<UpdateConfirmation?>(null); private set
    var run by mutableStateOf<MaintenanceRun?>(null); private set
    var progress by mutableStateOf<MaintenanceDecision?>(null); private set
    var requiresLogin by mutableStateOf(false); private set
    var operationKind by mutableStateOf<String?>(null); private set
    var startedAt by mutableStateOf<Long?>(null); private set
    private var snapshot: JsonObject? = null
    private var loaded = false
    val active get() = run != null || update?.text("status") in updateBusyStatuses || (snapshot?.get("maintenance") as? JsonObject)?.text("phase") in setOf("waiting", "stopping")
    val available get() = (update?.get("available") as? JsonObject)?.text("version")
    init { viewModelScope.launch {
        val stored = prefs.pendingMaintenance.first()
        run = stored?.let { runCatching { Json.decodeFromString<MaintenanceRun>(it) }.getOrNull() }
        operationKind = run?.kind; startedAt = run?.started
        refresh()
    } }
    private suspend fun load() = coroutineScope {
        val state = async { panel.checkedObject("GET", "/api/update/state") }
        val monitor = async { panel.checkedObject("GET", "/api/monitor/config") }
        update = state.await(); automatic = (monitor.await()["update"] as? JsonObject)?.flag("enabled") == true
        loaded = true
    }
    fun refresh() = action { load() }
    fun automatic(enabled: Boolean) = action {
        panel.checkedObject("POST", "/api/monitor/config", buildJsonObject { put("name", "update"); put("enabled", enabled) })
        automatic = enabled
    }
    fun check() = action {
        if (active) return@action
        val result = checkPanelUpdate { method, path -> panel.checkedObject(method, path) }
        update = result.state; message = result.message; error = result.error
    }
    fun currentNotes() = action {
        val result = panel.checkedObject("GET", "/api/update/changelog")
        notes = VersionNotes(result.text("version").orEmpty(), result.text("changelog").orEmpty(), true)
    }
    fun dismissNotes() { notes = null }
    fun rollbackVersions() = action {
        notes = null
        val result = panel.checkedObject("GET", "/api/update/versions")
        versions = (result["versions"] as? JsonArray).orEmpty().mapNotNull { (it as? JsonPrimitive)?.contentOrNull }.filterNot { samePanelVersion(it, update?.text("current_version")) }
    }
    fun dismissVersions() { versions = null }
    fun versionNotes(version: String) = action {
        val result = panel.checkedObject("GET", "/api/update/versions/${encodeSegment(version)}")
        notes = VersionNotes(version, result.text("changelog").orEmpty())
    }
    fun checkFromDashboard() = action {
        require(!active) { "Операция с панелью уже выполняется" }
        latest = false
        val result = checkPanelUpdate { method, path -> panel.checkedObject(method, path) }
        update = result.state; error = result.error
        if (result.error != null) return@action
        if (available == null) latest = true else prepareConfirmation("update", available)
    }
    fun prepare(kind: String = "update", target: String? = available) = action { prepareConfirmation(kind, target) }
    private suspend fun prepareConfirmation(kind: String, target: String?) {
        require(!active && !target.isNullOrBlank()) { "Нет доступной версии для установки" }
        val result = panel.checkedObject("GET", if (kind == "update") "/api/update/changelog_new" else "/api/update/versions/${encodeSegment(target)}")
        require(samePanelVersion(result.text("version"), target)) { "Доступная версия изменилась. Повторите проверку." }
        val preview = withTimeout(4000) { panel.checkedObject("GET", "/api/system/maintenance") }
        maintenanceTaskWarning(preview)
        confirmation = UpdateConfirmation(kind, VersionNotes(target, result.text("changelog").orEmpty()), preview)
        versions = null
    }
    fun prepareRestart() = action {
        require(!active) { "Операция с панелью уже выполняется" }
        val preview=withTimeout(4000) { panel.checkedObject("GET","/api/system/maintenance") }
        maintenanceTaskWarning(preview)
        confirmation=UpdateConfirmation("restart",VersionNotes(preview.text("version").orEmpty(),""),preview)
    }
    fun dismissConfirmation() { if (!busy) confirmation = null }
    fun install() = action {
        val ready = confirmation ?: return@action
        confirmation = null
        val pending = MaintenanceRun(UUID.randomUUID().toString(), ready.kind, ready.notes.version, ready.preview.text("instance_id")!!, System.currentTimeMillis())
        operationKind = pending.kind; startedAt = pending.started
        prefs.rememberMaintenance(Json.encodeToString(pending)); run = pending
        progress = MaintenanceDecision(MaintenancePhase.EXECUTING, "Запускаем операцию с панелью")
        try { withTimeout(10000) { panel.checkedObject("POST", "/api/system/maintenance/begin", buildJsonObject {
            put("id", pending.id); put("kind", pending.kind); if(pending.kind != "restart") put("target", pending.target)
        }) } }
        catch (e: TimeoutCancellationException) { progress = MaintenanceDecision(MaintenancePhase.EXECUTING, "Ответ не получен. Проверяем состояние операции") }
        catch (e: CancellationException) { throw e }
        catch (e: ApiError) {
            if (e.status !in setOf(408, 502, 503, 504)) { run = null; prefs.rememberMaintenance(null); throw e }
        }
        catch (_: java.io.IOException) { progress = MaintenanceDecision(MaintenancePhase.EXECUTING, "Связь потеряна. Проверяем состояние операции") }
    }
    fun control(command: String) = action {
        val pending = run ?: return@action
        require(command in setOf("cancel", "force") && progress?.phase == MaintenancePhase.WAITING)
        panel.checkedObject("POST", "/api/system/maintenance/${encodeSegment(pending.id)}/$command")
        poll()
    }
    fun closeProgress() { if (run == null) progress = null }
    suspend fun observe() {
        while (!loaded && run == null) delay(100)
        while (true) {
            if (!busy && !requiresLogin && (run != null || active)) poll()
            delay(1500)
        }
    }
    private suspend fun poll() {
        try {
            val live = withTimeout(4000) { panel.checkedObject("GET", "/api/system/maintenance") }
            val state = withTimeout(4000) { panel.checkedObject("GET", "/api/update/state") }
            snapshot = live; update = state
            val pending = run ?: return
            val fresh = pending.copy(seenBusy = pending.seenBusy || state.text("status") in updateBusyStatuses)
            val result = maintenanceDecision(fresh, live, state)
            progress = result
            if (result.phase in setOf(MaintenancePhase.DONE, MaintenancePhase.CANCELLED, MaintenancePhase.FAILED)) {
                run = null; prefs.rememberMaintenance(null)
                if (result.phase == MaintenancePhase.FAILED) error = result.message else message = result.message
            } else { run = fresh; prefs.rememberMaintenance(Json.encodeToString(fresh)) }
        } catch (e: TimeoutCancellationException) { progress = MaintenanceDecision(MaintenancePhase.EXECUTING, "Панель временно недоступна. Ожидаем восстановления связи") }
        catch (e: CancellationException) { throw e }
        catch (e: ApiError) { if (e.status in setOf(401, 403)) requiresLogin = true; else progress = MaintenanceDecision(MaintenancePhase.EXECUTING, "Проверяем связь и состояние операции") }
        catch (_: Exception) { progress = MaintenanceDecision(MaintenancePhase.EXECUTING, "Панель временно недоступна. Ожидаем восстановления связи") }
    }
    private fun action(block: suspend () -> Unit) {
        if (busy) return
        busy = true; error = null; message = null
        viewModelScope.launch {
            try { block() }
            catch (e: TimeoutCancellationException) { error = "Панель не ответила вовремя. Повторите проверку связи." }
            catch (e: CancellationException) { throw e }
            catch (e: Exception) {
                if(e is ApiError && e.status in setOf(401,403)) requiresLogin=true
                error = if(e is ApiError && e.status == 404) "Действие недоступно в этой версии панели. Выполните его в веб-интерфейсе." else errorText(e)
            }
            finally { busy = false }
        }
    }
}
