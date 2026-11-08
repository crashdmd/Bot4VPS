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
import javax.inject.Inject

data class ServicesState(val selected: ServiceKind? = null, val rows: List<ServiceServer> = emptyList(),
    val filter: InstallationFilter = InstallationFilter.ALL, val search: String = "", val group: String? = null,
    val order: List<String> = emptyList(), val loaded: Boolean = false, val loading: Boolean = false, val error: String? = null, val sortByName: Boolean = false) {
    val filtered get() = filterServiceServers(rows, filter, search, group).let { list ->
        if (sortByName) list.sortedBy { it.name.lowercase() }
        else list.sortedBy { order.indexOf(it.id).let { index -> if (index < 0) Int.MAX_VALUE else index } }
    }
}

@HiltViewModel
class ServicesViewModel @Inject constructor(private val saved: SavedStateHandle, private val repo: ServiceRepository, private val realtime: RealtimeHub) : ViewModel() {
    private val _state = MutableStateFlow(ServicesState(selected = ServiceKind.find(saved.get<String>("selected_service"))))
    val state = _state.asStateFlow()
    private var request: Job? = null
    init { if (_state.value.selected != null) refresh() }
    fun select(kind: ServiceKind?) {
        request?.cancel()
        saved["selected_service"] = kind?.id
        _state.value = ServicesState(selected = kind)
        refresh()
    }
    fun filter(value: InstallationFilter) { _state.update { it.copy(filter = value) } }
    fun search(value: String) { _state.update { it.copy(search = value) } }
    fun group(value: String?) { _state.update { it.copy(group = value) } }
    fun sort() { _state.update { it.copy(sortByName = !it.sortByName) } }
    fun refresh() { fetch(false) }
    private fun fetch(background: Boolean) {
        val kind = _state.value.selected ?: return
        if (kind == ServiceKind.SCRIPTS || request?.isActive == true) return
        request = viewModelScope.launch {
            _state.update { it.copy(loading = !background || !it.loaded, error = if (background) it.error else null) }
            try {
                val rows = repo.servers(kind)
                _state.update { old ->
                    val ranked = rows.sortedWith(compareBy<ServiceServer> { if (it.installed) 0 else if (it.classic) 1 else 2 }.thenBy { it.name.lowercase() }).map { it.id }
                    val order = if (old.order.isNotEmpty()) retainServerOrder(old.order, ranked) else ranked
                    old.copy(rows = rows, order = order, loaded = true, loading = false, error = null)
                }
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) { _state.update { it.copy(loading = false, error = errorText(e)) } }
        }
    }
    suspend fun observe() {
        fetch(true)
        realtime.events.filter { it.type == "snapshot" }.conflate().collect {
            fetch(true)
            request?.join()
            delay(6000)
        }
    }
}
