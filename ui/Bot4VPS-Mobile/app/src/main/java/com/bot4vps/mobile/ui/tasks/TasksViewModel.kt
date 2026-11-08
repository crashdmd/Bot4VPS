package com.bot4vps.mobile.ui.tasks

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.bot4vps.mobile.data.api.errorText
import com.bot4vps.mobile.data.model.*
import com.bot4vps.mobile.data.repository.*
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import javax.inject.Inject

data class TasksUiState(val tasks: List<TaskSummary> = emptyList(), val selected: TaskSummary? = null,
    val servers: List<ServerSummary> = emptyList(), val serverId: String? = null, val filter: String = "all",
    val loaded: Boolean = false, val isLoading: Boolean = false, val busy: Boolean = false, val error: String? = null,
    val notice: String? = null) {
    val filtered get() = tasks.filter { task -> when (filter) {
        "active" -> !task.isDone
        "done" -> task.isDone
        "failed" -> task.status == "failed"
        else -> true
    } }
}

@HiltViewModel
class TasksViewModel @Inject constructor(private val saved: SavedStateHandle, private val repo: TaskRepository,
    private val servers: ServerRepository) : ViewModel() {
    private val initialTask = saved.get<String>("taskId")?.takeIf(String::isNotBlank)
    private val _ui = MutableStateFlow(TasksUiState(serverId = saved.get<String>("serverId")?.takeIf(String::isNotBlank),
        selected = initialTask?.let { TaskSummary(id = it, name = "Загрузка задачи…") }))
    val ui = _ui.asStateFlow()
    private var listRequest: Job? = null
    private var detailRequest: Job? = null
    init {
        viewModelScope.launch {
            try { val list = servers.getServers(); _ui.update { it.copy(servers = list) } }
            catch (e: CancellationException) { throw e }
            catch (_: Exception) { /* History remains usable without server choices. */ }
        }
        refresh()
        initialTask?.let { open(TaskSummary(id = it, name = "Загрузка задачи…")) }
    }
    fun server(id: String?) { saved["serverId"] = id; _ui.update { it.copy(serverId = id) }; refresh() }
    fun filter(value: String) { _ui.update { it.copy(filter = value) } }
    fun refresh() {
        if (_ui.value.busy) return
        listRequest?.cancel()
        val id = _ui.value.serverId
        listRequest = viewModelScope.launch {
            _ui.update { it.copy(isLoading = !it.loaded) }
            try { val rows = repo.history(80, id); _ui.update { it.copy(tasks = rows, isLoading = false, loaded = true, error = null) } }
            catch (e: CancellationException) { throw e }
            catch (e: Exception) { _ui.update { it.copy(isLoading = false, error = errorText(e)) } }
        }
    }
    fun open(task: TaskSummary) {
        if (_ui.value.busy) return
        detailRequest?.cancel()
        _ui.update { it.copy(selected = task, error = null) }
        detailRequest = viewModelScope.launch {
            try { val full = repo.task(task.id); _ui.update { if (it.selected?.id == task.id) it.copy(selected = full) else it } }
            catch (e: CancellationException) { throw e }
            catch (e: Exception) { _ui.update { it.copy(error = errorText(e)) } }
        }
    }
    fun closeDetail() { detailRequest?.cancel(); _ui.update { it.copy(selected = null, error = null) }; refresh() }
    suspend fun poll() {
        if (_ui.value.busy || detailRequest?.isActive == true || listRequest?.isActive == true) return
        try {
            val selected = _ui.value.selected
            if (selected != null && !selected.isDone) {
                val full = repo.task(selected.id)
                _ui.update { if (it.selected?.id == full.id) it.copy(selected = full, error = null) else it }
            } else if (selected == null) {
                refresh(); listRequest?.join()
            }
        } catch (e: CancellationException) { throw e }
        catch (e: Exception) { _ui.update { it.copy(error = errorText(e)) } }
    }
    fun cancelSelected() {
        val selected = _ui.value.selected ?: return
        if (_ui.value.busy || selected.isDone) return
        viewModelScope.launch {
            _ui.update { it.copy(busy = true, error = null) }
            try { repo.cancel(selected.id); _ui.update { it.copy(busy = false) }; open(selected) }
            catch (e: CancellationException) { throw e }
            catch (e: Exception) { _ui.update { it.copy(busy = false, error = errorText(e)) } }
        }
    }
    fun consumeNotice() { _ui.update { it.copy(notice = null) } }
    fun clearHistory() {
        if (_ui.value.busy || _ui.value.selected != null) return
        listRequest?.cancel()
        _ui.update { it.copy(busy = true, isLoading = false, error = null, notice = null) }
        viewModelScope.launch {
            var cleared = false
            try {
                repo.clearHistory()
                cleared = true
                _ui.update { it.copy(tasks = emptyList(), loaded = true, notice = "История задач очищена") }
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) { _ui.update { it.copy(error = errorText(e)) } }
            finally { _ui.update { it.copy(busy = false) } }
            if (cleared) refresh()
        }
    }
}
