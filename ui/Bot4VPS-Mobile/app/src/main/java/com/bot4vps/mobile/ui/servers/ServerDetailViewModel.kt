package com.bot4vps.mobile.ui.servers

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

data class ServerDetailUiState(val server: ServerCore? = null, val monitor: JsonObject = JsonObject(emptyMap()),
    val metrics: ServerMetrics? = null, val runningTask: TaskSummary? = null, val queue: List<TaskSummary> = emptyList(),
    val queueState: JsonObject = JsonObject(emptyMap()), val services: Map<ServiceKind, ServiceServer> = emptyMap(),
    val serviceErrors: Map<ServiceKind, String> = emptyMap(), val events: List<JsonObject> = emptyList(), val eventsError: String? = null,
    val keyExists: Boolean? = null, val probe: ProbeResponse? = null, val command: String = "", val execOutput: String? = null,
    val isLoading: Boolean = true, val actionMessage: String? = null, val error: String? = null, val busy: Boolean = false) {
    val availability get() = monitor["availability"] as? JsonObject ?: JsonObject(emptyMap())
    val online get() = (availability["online"] as? JsonPrimitive)?.booleanOrNull
    val portOk get() = (availability["port_ok"] as? JsonPrimitive)?.booleanOrNull
    val blocked get() = keyExists == false || portOk == false || portOk == null && online == false || probe?.hostKeyMismatch == true
}

@HiltViewModel
class ServerDetailViewModel @Inject constructor(saved: SavedStateHandle, private val repo: ServerRepository,
    private val serviceRepo: ServiceRepository, private val panel: NativePanelClient) : ViewModel() {
    private val serverId: String = checkNotNull(saved["serverId"])
    private val _ui = MutableStateFlow(ServerDetailUiState())
    val ui = _ui.asStateFlow()
    private var request: Job? = null
    private var ticks = 0
    init { load() }
    fun onCommandChange(value: String) { _ui.update { it.copy(command = value) } }
    fun load() { reload(true, true) }
    private fun reload(extras: Boolean, manual: Boolean = false) {
        request?.cancel()
        request = viewModelScope.launch {
            _ui.update { it.copy(isLoading = manual || it.server == null) }
            try {
                val detail = repo.getServer(serverId)
                require(detail.server != null) { "Панель не вернула сведения о сервере" }
                _ui.update { it.copy(server = detail.server, monitor = detail.monitor as? JsonObject ?: JsonObject(emptyMap()),
                    runningTask = detail.runningTask, queue = detail.queue, queueState = detail.queueState, keyExists = detail.keyExists) }
                if (extras) supervisorScope {
                    val metrics = launch {
                        try { val data = repo.getMetrics(serverId); _ui.update { it.copy(metrics = data, probe = if (data.ok) null else it.probe) } }
                        catch (e: CancellationException) { throw e }
                        catch (e: Exception) { _ui.update { it.copy(metrics = ServerMetrics(error = errorText(e))) } }
                    }
                    val services = launch {
                        ServiceKind.entries.filter { it != ServiceKind.SCRIPTS }.map { kind -> launch {
                            try {
                                val row = serviceRepo.servers(kind).find { it.id == serverId } ?: error("Сервер не найден")
                                _ui.update { it.copy(services = it.services + (kind to row), serviceErrors = it.serviceErrors - kind) }
                            } catch (e: CancellationException) { throw e }
                            catch (e: Exception) { _ui.update { it.copy(serviceErrors = it.serviceErrors + (kind to errorText(e))) } }
                        } }.joinAll()
                    }
                    val events = launch {
                        try {
                            val rows = panel.checkedObject("GET", "/api/events", query = mapOf("limit" to listOf("200"))).objects("events").filter {
                                it.text("server_id") == serverId || (it["details"] as? JsonObject)?.text("server_id") == serverId
                            }.take(5)
                            _ui.update { it.copy(events = rows, eventsError = null) }
                        } catch (e: CancellationException) { throw e }
                        catch (e: Exception) { _ui.update { it.copy(eventsError = errorText(e)) } }
                    }
                    joinAll(metrics, services, events)
                }
                _ui.update { it.copy(isLoading = false, error = null) }
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) { _ui.update { it.copy(isLoading = false, error = errorText(e)) } }
        }
    }
    suspend fun poll() {
        if (_ui.value.busy || request?.isActive == true) return
        ticks++
        reload(ticks % 3 == 0); request?.join()
    }
    fun probe() = action {
        val result = repo.probe(serverId)
        _ui.update { it.copy(probe = result) }
        load()
        if (result.info?.ssh == true) "SSH-соединение работает"
        else result.sshErrorHuman?.takeIf(String::isNotBlank) ?: result.info?.sshError ?: result.error ?: "SSH недоступен"
    }
    fun reboot() = action {
        val result = repo.reboot(serverId)
        require(result.ok) { result.error ?: result.detail ?: "Не удалось отправить перезагрузку" }
        result.message ?: "Перезагрузка отправлена"
    }
    fun exec() {
        if (_ui.value.busy || _ui.value.blocked) return
        val command = _ui.value.command.trim()
        if (command.isBlank()) { _ui.update { it.copy(actionMessage = "Введите команду") }; return }
        action {
            val result = repo.exec(serverId, command)
            val output = listOfNotNull(result.stdout?.takeIf(String::isNotBlank), result.stderr?.takeIf(String::isNotBlank)).joinToString("\n")
            _ui.update { it.copy(execOutput = "${output.ifBlank { if (result.ok) "(пусто)" else "Ошибка выполнения" }}\n[exit ${result.exitCode ?: "—"}]") }
            "Команда выполнена"
        }
    }
    private fun action(block: suspend () -> String) {
        if (_ui.value.busy) return
        viewModelScope.launch {
            _ui.update { it.copy(busy = true, actionMessage = null) }
            try { val message = block(); _ui.update { it.copy(busy = false, actionMessage = message) } }
            catch (e: CancellationException) { throw e }
            catch (e: Exception) { _ui.update { it.copy(busy = false, actionMessage = errorText(e)) } }
        }
    }
}
