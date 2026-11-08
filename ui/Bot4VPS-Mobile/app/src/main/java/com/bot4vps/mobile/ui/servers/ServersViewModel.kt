package com.bot4vps.mobile.ui.servers

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.bot4vps.mobile.data.api.*
import com.bot4vps.mobile.data.model.*
import com.bot4vps.mobile.data.repository.ServerRepository
import com.bot4vps.mobile.data.repository.GroupRepository
import com.bot4vps.mobile.data.local.PreferencesManager
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import kotlinx.serialization.json.*
import javax.inject.Inject

data class ServersUiState(val servers: List<ServerSummary> = emptyList(), val selectedGroup: String? = null,
    val search: String = "", val summary: SummaryResponse? = null, val isLoading: Boolean = false, val error: String? = null,
    val sort: ServerListSort = ServerListSort.NAME, val descending: Boolean = false,
    val catalogGroups: List<String> = emptyList(), val groupDisplay: GroupDisplaySettings = GroupDisplaySettings()) {
    val groups get() = groupDisplay.visible((catalogGroups + servers.mapNotNull { it.group?.takeIf { group -> group.isNotBlank() && group != "—" } }).distinct())
    val filtered get() = servers.filter { server -> (selectedGroup == null || server.group == selectedGroup) &&
        (search.isBlank() || listOfNotNull(server.name, server.host, server.hostIp, server.group).any { it.contains(search.trim(), true) }) }
}

@HiltViewModel
class ServersViewModel @Inject constructor(private val repo: ServerRepository, private val realtime: RealtimeHub, private val json: Json,
    private val groups: GroupRepository, private val prefs: PreferencesManager) : ViewModel() {
    private val _ui = MutableStateFlow(ServersUiState())
    val uiState = _ui.asStateFlow()
    private var request: Job? = null
    init {
        viewModelScope.launch { groups.groups.collect { rows -> _ui.update { it.copy(catalogGroups = rows.orEmpty().map { row -> row.name }) } } }
        viewModelScope.launch { prefs.groupDisplay.collect { display -> _ui.update { old -> old.copy(groupDisplay = display,
            selectedGroup = old.selectedGroup?.takeUnless { it in display.hidden }) } } }
        viewModelScope.launch { groups.mutations.collect { change ->
            request?.cancel()
            request = null
            _ui.update { old -> old.copy(selectedGroup = when {
                old.selectedGroup == change.deleted -> null
                old.selectedGroup != null && old.selectedGroup == change.oldName -> change.newName
                else -> old.selectedGroup
            }, servers = old.servers.map { server -> if (change.oldName != null && server.group == change.oldName) server.copy(group = change.newName) else server }) }
            refresh()
        } }
        refresh()
    }
    fun refresh() {
        if (request?.isActive == true) return
        request = viewModelScope.launch {
            _ui.update { it.copy(isLoading = true, error = null) }
            try {
                val list = repo.getServers()
                runCatching { groups.refresh() }.onFailure { if (it is CancellationException) throw it }
                val summary = repo.summary()
                _ui.update { old ->
                    val byId = list.associateBy { it.id }
                    val ordered = if (old.servers.isEmpty()) sortServerList(list, old.sort, old.descending)
                        else old.servers.mapNotNull { byId[it.id] } + list.filter { row -> old.servers.none { it.id == row.id } }
                    old.copy(servers = ordered, summary = summary, isLoading = false,
                        selectedGroup = old.selectedGroup?.takeIf { selected -> selected in old.catalogGroups || list.any { it.group == selected } })
                }
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) { _ui.update { it.copy(isLoading = false, error = errorText(e)) } }
        }
    }
    fun selectGroup(group: String?) { _ui.update { it.copy(selectedGroup = group) } }
    fun search(query: String) { _ui.update { it.copy(search = query) } }
    fun sort(key: ServerListSort) {
        _ui.update { old ->
            val descending = if (key == old.sort) !old.descending else key == ServerListSort.SSL
            old.copy(sort = key, descending = descending, servers = sortServerList(old.servers, key, descending))
        }
    }
    suspend fun observe() {
        refresh()
        realtime.events.filter { it.type == "snapshot" }.collect { event ->
            val snapshot = event.data as? JsonObject ?: return@collect
            val incoming = snapshot["servers"] as? JsonArray ?: return@collect
            if (_ui.value.isLoading || request?.isActive == true) return@collect
            val previous = _ui.value.servers.associateBy { it.id }
            if (incoming.mapNotNull { (it as? JsonObject)?.text("id") }.toSet() != previous.keys) {
                refresh(); return@collect
            }
            val updates = incoming.mapNotNull { value ->
                val row = value as? JsonObject ?: return@mapNotNull null
                val old = previous[row.text("id")] ?: return@mapNotNull null
                runCatching { json.decodeFromJsonElement<ServerSummary>(JsonObject(json.encodeToJsonElement(old).jsonObject + row)) }.getOrNull()
            }.associateBy { it.id }
            _ui.update { it.copy(servers = it.servers.map { row -> updates[row.id] ?: row }) }
        }
    }
}
