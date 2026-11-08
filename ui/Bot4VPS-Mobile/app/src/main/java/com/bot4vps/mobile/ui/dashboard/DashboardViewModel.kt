package com.bot4vps.mobile.ui.dashboard

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

data class SystemSample(val time: Long, val cpu: Double?, val ram: Double?, val rx: Double?, val tx: Double?, val disk: Double? = null)
data class DashboardState(val system: JsonObject? = null, val summary: JsonObject = JsonObject(emptyMap()),
    val servers: List<ServerSummary> = emptyList(), val events: List<JsonObject> = emptyList(), val samples: List<SystemSample> = emptyList(),
    val widgetIds: List<String> = emptyList(), val metrics: Map<String, ServerMetrics> = emptyMap(),
    val serverSamples: Map<String, List<SystemSample>> = emptyMap(), val update: JsonObject? = null, val loading: Boolean = true, val systemError: String? = null, val serverError: String? = null, val eventsError: String? = null) {
    val widgetServers get() = widgetIds.mapNotNull { id -> servers.find { it.id == id } }
    val online get() = servers.count { it.online == true }
    val offline get() = servers.count { it.online == false }
}

@HiltViewModel
class DashboardViewModel @Inject constructor(private val panel: NativePanelClient, private val realtime: RealtimeHub, private val servers: ServerRepository) : ViewModel() {
    private val _state = MutableStateFlow(DashboardState())
    val state = _state.asStateFlow()
    private var request: Job? = null
    init { refresh() }
    fun refresh() = refresh(true)
    private fun refresh(reselect: Boolean) {
        if (request?.isActive == true) return
        request = viewModelScope.launch {
            _state.update { it.copy(loading = reselect || it.servers.isEmpty()) }
            supervisorScope {
                launch { loadSystem() }
                launch {
                    try { val list = servers.getServers(); _state.update { it.copy(servers = ordered(it.servers, list), widgetIds = if (reselect || it.widgetIds.isEmpty()) pickDashboardServers(list).map { row -> row.id } else it.widgetIds.filter { id -> list.any { row -> row.id == id } }, serverError = null) } }
                    catch (e: CancellationException) { throw e }
                    catch (e: Exception) { _state.update { it.copy(serverError = errorText(e)) } }
                }
                launch {
                    try { val update = panel.checkedObject("GET", "/api/update/state"); _state.update { it.copy(update = update) } }
                    catch (e: CancellationException) { throw e }
                    catch (_: Exception) { }
                }
                launch {
                    try { val events = panel.checkedObject("GET", "/api/events", query = mapOf("limit" to listOf("5"))).objects("events"); _state.update { it.copy(events = events, eventsError = null) } }
                    catch (e: CancellationException) { throw e }
                    catch (e: Exception) { _state.update { it.copy(eventsError = errorText(e)) } }
                }
            }
            loadServerMetrics()
            _state.update { it.copy(loading = false) }
        }
    }
    private fun ordered(previous: List<ServerSummary>, incoming: List<ServerSummary>): List<ServerSummary> {
        val rows = incoming.associateBy { it.id }
        return retainServerOrder(previous.map { it.id }, incoming.map { it.id }).mapNotNull { rows[it] }
    }
    private suspend fun loadSystem() {
        try {
            val system = panel.checkedObject("GET", "/api/system")
            val sample = SystemSample(System.currentTimeMillis(), system.number("cpu"), system.number("ram_pct"), system.number("net_rx"), system.number("net_tx"), system.number("disk_pct"))
            _state.update { it.copy(system = system, systemError = null, samples = (it.samples + sample).takeLast(60)) }
        } catch (e: CancellationException) { throw e }
        catch (e: Exception) { _state.update { it.copy(systemError = errorText(e), samples = (it.samples + SystemSample(System.currentTimeMillis(), null, null, null, null)).takeLast(60)) } }
    }
    private suspend fun loadServerMetrics() = supervisorScope {
        val shown = _state.value.widgetServers
        shown.map { server -> launch {
            val metric = if (server.online == false) ServerMetrics(error = "Сервер офлайн") else try { servers.getMetrics(server.id) }
                catch (e: CancellationException) { throw e }
                catch (e: Exception) { ServerMetrics(error = errorText(e)) }
            val sample = SystemSample(System.currentTimeMillis(), metric.cpu.takeIf { metric.ok }, metric.ramPct.takeIf { metric.ok }, null, null)
            _state.update { old -> old.copy(metrics = old.metrics + (server.id to metric),
                serverSamples = old.serverSamples + (server.id to (old.serverSamples[server.id].orEmpty() + sample).takeLast(20))) }
        } }.joinAll()
        _state.update { old -> old.copy(metrics = old.metrics.filterKeys { it in old.widgetIds }, serverSamples = old.serverSamples.filterKeys { it in old.widgetIds }) }
    }
    suspend fun observe() = coroutineScope {
        refresh(false)
        launch {
            realtime.events.filter { it.type == "snapshot" }.conflate().collect { event ->
                val snapshot = event.data as? JsonObject ?: return@collect
                val rows = (snapshot["servers"] as? JsonArray)?.mapNotNull { row -> runCatching { panel.json.decodeFromJsonElement<ServerSummary>(row) }.getOrNull() }
                val events = (snapshot["events"] as? JsonArray)?.mapNotNull { it as? JsonObject }?.take(5)
                val summary = snapshot["summary"] as? JsonObject
                _state.update { old ->
                    val queues = snapshot.objects("queues")
                    val queued = queues.sumOf { (it["queue"] as? JsonArray)?.size ?: 0 }
                    old.copy(servers = rows?.let { incoming -> ordered(old.servers, incoming.map { row ->
                        val previous = old.servers.find { it.id == row.id }
                        if (previous == null) row else {
                            val raw = snapshot.objects("servers").find { it.text("id") == row.id }!!
                            runCatching { panel.json.decodeFromJsonElement<ServerSummary>(JsonObject(panel.json.encodeToJsonElement(previous).jsonObject + raw)) }.getOrDefault(previous)
                        }
                    }) } ?: old.servers, events = events ?: old.events,
                        summary = if (summary != null) JsonObject(old.summary + summary + ("queued_tasks" to JsonPrimitive(queued))) else old.summary)
                }
            }
        }
        var tick = 0
        while (true) {
            delay(3000)
            if (request?.isActive == true) continue
            if (++tick % 5 == 0) refresh(false) else supervisorScope { launch { loadSystem() }; launch { loadServerMetrics() } }
        }
    }
}

/** Same priority and size as the mobile web widget; manual refresh starts a new selection. */
fun pickDashboardServers(servers: List<ServerSummary>): List<ServerSummary> {
    val (problems, healthy) = servers.partition { it.online != true || !it.sshError.isNullOrBlank() }
    return (problems.shuffled() + healthy.shuffled()).take(6)
}
