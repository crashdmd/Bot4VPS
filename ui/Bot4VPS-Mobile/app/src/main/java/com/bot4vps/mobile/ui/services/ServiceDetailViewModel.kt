package com.bot4vps.mobile.ui.services

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.bot4vps.mobile.data.api.*
import com.bot4vps.mobile.data.model.*
import com.bot4vps.mobile.data.repository.*
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import kotlinx.serialization.json.*
import javax.inject.Inject

data class ServiceEditor(val operation: NativeOperation, val title: String, val schema: JsonObject,
    val initial: JsonObject, val values: Map<String, JsonElement>, val wrapParams: Boolean, val locked: Set<String>,
    val xuiAction: String? = null, val description: String? = null, val choices: Map<String, List<Pair<String, String>>> = emptyMap())
data class ServiceDetailState(val detail: ServiceDetail? = null, val loading: Boolean = true, val busy: Boolean = false,
    val error: String? = null, val notice: String? = null, val tab: String = "overview", val search: String = "",
    val site: JsonObject? = null, val siteLoading: Boolean = false, val recordFilter: String = "all", val editor: ServiceEditor? = null, val task: TaskSummary? = null)

@HiltViewModel
class ServiceDetailViewModel @Inject constructor(saved: SavedStateHandle, private val repo: ServiceRepository,
    private val panel: NativePanelClient, private val contracts: ContractRepository, private val tasks: TaskRepository,
    private val workflow: NativeWorkflow, private val realtime: RealtimeHub) : ViewModel() {
    val kind = ServiceKind.find(saved.get<String>("serviceId")) ?: error("Сервис не найден")
    val serverId: String = checkNotNull(saved["serverId"])
    private val _state = MutableStateFlow(ServiceDetailState(tab = if (kind == ServiceKind.DOCKER) "containers" else if (kind == ServiceKind.WIREGUARD) "profiles" else "overview"))
    val state = _state.asStateFlow()
    private var request: Job? = null
    private var contract: NativeContract? = null
    init {
        viewModelScope.launch {
            try { contract = contracts.load() }
            catch (e: CancellationException) { throw e }
            catch (e: Exception) { _state.update { it.copy(error = errorText(e)) } }
        }
        refresh()
    }
    fun refresh() = refresh(false)
    private fun refresh(background: Boolean) {
        if (_state.value.busy || _state.value.editor != null || _state.value.site != null || _state.value.siteLoading) return
        if (request?.isActive == true) return
        val tab = _state.value.tab
        request = viewModelScope.launch {
            _state.update { it.copy(loading = !background || it.detail == null) }
            try { val detail = repo.detail(kind, serverId, tab); _state.update { it.copy(detail = detail, loading = false, error = null) } }
            catch (e: CancellationException) { throw e }
            catch (e: Exception) { _state.update { it.copy(loading = false, error = errorText(e)) } }
        }
    }
    fun tab(value: String) { if (_state.value.busy || _state.value.editor != null) return; request?.cancel(); _state.update { it.copy(tab = value, search = "", recordFilter = "all") }; refresh() }
    fun search(value: String) { _state.update { it.copy(search = value) } }
    fun filter(value: String) { _state.update { it.copy(recordFilter = value) } }
    fun dismissEditor() { if (!_state.value.busy) _state.update { it.copy(editor = null, error = null) } }

    fun edit(id: String, title: String, values: Map<String, JsonElement> = emptyMap(), locked: Set<String> = emptySet()) {
        if (_state.value.busy) return
        if (_state.value.detail?.server?.blocked == true) { _state.update { it.copy(error = it.detail?.server?.blockReason) }; return }
        val op = contract?.operations?.find { it.id == id } ?: run { _state.update { it.copy(error = "Настройки действия ещё загружаются. Повторите попытку.") }; return }
        val wrap = op.body?.properties()?.containsKey("params") == true
        val schema = if (wrap) op.body?.properties()?.get("params") else op.body
        val action = id.substringAfterLast('/')
        val data = _state.value.detail?.state ?: JsonObject(emptyMap())
        val explicit = if (kind == ServiceKind.XUI) xuiForm(action, data, values) else null
        val fields = explicit ?: schema ?: JsonObject(mapOf("type" to JsonPrimitive("object")))
        val initial = NativeForm.initial(fields) as? JsonObject ?: JsonObject(emptyMap())
        val bodyValues = values.filterKeys { it in fields.properties() || explicit == null && wrap && fields["additionalProperties"] != null }
        _state.update { it.copy(editor = ServiceEditor(op, title, fields, JsonObject(initial + bodyValues), values, wrap, if (explicit != null) locked - fields.properties().keys else locked,
            xuiAction = action.takeIf { explicit != null }, description = if (explicit != null) xuiActionDescription(action, data) else null,
            choices = if (action in setOf("cert_renew", "cert_remove")) mapOf("certificate" to xuiCertificates(data).map { it.id to it.label }) else emptyMap()), error = null) }
    }

    fun action(action: String, title: String, params: Map<String, JsonElement> = emptyMap(), quick: Boolean = false, locked: Set<String> = params.keys) =
        edit("POST /api/services/${kind.id}/{server_id}/${if (quick) "action" else "enqueue"}/$action", title, params, locked)

    fun submit(values: JsonObject) {
        val s = _state.value; val editor = s.editor ?: return
        if (s.busy) return
        NativeForm.validate(editor.schema, values)?.let { error -> _state.update { it.copy(error = error) }; return }
        editor.xuiAction?.let { action ->
            xuiFormError(action, values)?.let { error -> _state.update { it.copy(error = error) }; return }
        }
        request?.cancel()
        _state.update { it.copy(busy = true, loading = false, error = null, notice = null) }
        viewModelScope.launch {
            try {
                val server = repo.servers(kind).find { it.id == serverId } ?: error("Сервер не найден")
                require(!server.blocked) { server.blockReason }
                var path = editor.operation.path.replace("{server_id}", encodeSegment(serverId))
                editor.values.forEach { (key, value) -> path = path.replace("{$key}", encodeSegment(value.jsonPrimitive.content)) }
                require(!path.contains('{')) { "Не выбран объект действия" }
                val params = if (editor.xuiAction != null) {
                    val current = if (editor.xuiAction in setOf("cert_renew", "cert_remove")) repo.detail(kind, serverId, "overview").state else s.detail?.state ?: JsonObject(emptyMap())
                    JsonObject(xuiParams(editor.xuiAction, values, current) + editor.values.filterKeys { it in editor.locked } +
                        if (editor.xuiAction == "cert_issue_ip") mapOf("set_panel" to JsonPrimitive(true)) else emptyMap())
                } else values
                val body = if (editor.wrapParams) JsonObject(mapOf("params" to params)) else params
                val response = panel.checkedObject(editor.operation.method, path, body)
                val brief = response["task"] as? JsonObject
                val taskId = brief?.text("id") ?: response.text("task_id") ?: response.text("id")
                val accepted = taskId?.let { TaskSummary(id = it, name = brief?.text("name") ?: editor.title, status = brief?.text("status") ?: "queued") }
                _state.update { it.copy(busy = false, editor = null, task = accepted ?: it.task,
                    notice = if (taskId != null) "Задача принята. Выполнение отображается ниже." else if (response["sync_ok"] == JsonPrimitive(false)) "Действие выполнено, но состояние не обновлено: ${response.text("sync_error")}" else "Изменения применены") }
                request = null
                refresh()
                if (taskId != null) {
                    try { val fresh = tasks.task(taskId); _state.update { if (it.task?.id == taskId) it.copy(task = fresh) else it } }
                    catch (e: CancellationException) { throw e }
                    catch (e: Exception) { _state.update { it.copy(error = "Задача принята, но её состояние пока недоступно: ${errorText(e)}") } }
                }
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) { _state.update { it.copy(busy = false, error = errorText(e)) } }
        }
    }

    fun dismissSite() { _state.update { it.copy(site = null) } }
    fun openSite() {
        if (_state.value.busy || _state.value.siteLoading) return
        request?.cancel()
        _state.update { it.copy(siteLoading = true, loading = false, error = null) }
        viewModelScope.launch {
            try {
                val response = panel.checkedObject("POST", "/api/services/3x-ui/${encodeSegment(serverId)}/action/fakesite_info", buildJsonObject { put("params", buildJsonObject {}) })
                val site = response["fakesite"] as? JsonObject ?: error("Не удалось получить состояние SelfSNI")
                require(!site.text("checked_at").isNullOrBlank()) { "Для проверки SelfSNI перезапустите Bot4VPS после обновления панели" }
                _state.update { it.copy(siteLoading = false, site = site) }
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) { _state.update { it.copy(siteLoading = false, error = errorText(e)) } }
        }
    }

    fun handoff(id: String, values: Map<String, JsonElement> = emptyMap()) { workflow.put(id, JsonObject(values + ("server_id" to JsonPrimitive(serverId)))) }

    suspend fun observe() {
        realtime.events.filter { it.type == "snapshot" }.conflate().collect {
            if (!_state.value.loading && !_state.value.busy && _state.value.editor == null && _state.value.site == null && !_state.value.siteLoading) refresh(true)
            delay(6000)
        }
    }

    suspend fun poll() {
        val task = _state.value.task ?: return
        if (task.isDone) return
        try {
            val fresh = tasks.task(task.id)
            _state.update { it.copy(task = fresh) }
            if (fresh.isDone) refresh()
        } catch (e: CancellationException) { throw e }
        catch (e: Exception) { _state.update { it.copy(error = errorText(e)) } }
    }
}
