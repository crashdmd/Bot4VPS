package com.bot4vps.mobile.ui.tasks

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.repeatOnLifecycle
import com.bot4vps.mobile.data.model.TaskSummary
import com.bot4vps.mobile.ui.components.*
import com.bot4vps.mobile.ui.services.taskStatusLabel
import kotlinx.coroutines.delay

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TasksScreen(onEvents: () -> Unit = {}, onBack: (() -> Unit)? = null, viewModel: TasksViewModel = hiltViewModel()) {
    val state by viewModel.ui.collectAsStateWithLifecycle()
    val selected = state.selected
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(lifecycle, viewModel) { lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) { while (true) { delay(2000); viewModel.poll() } } }
    var confirmCancel by remember { mutableStateOf(false) }
    var confirmClear by remember { mutableStateOf(false) }
    val snack = remember { SnackbarHostState() }
    LaunchedEffect(state.notice) { state.notice?.let { snack.showSnackbar(it); viewModel.consumeNotice() } }
    if (confirmClear) AlertDialog(onDismissRequest = { confirmClear = false },
        title = { Text("Очистить историю задач?") },
        text = { Text("Будут удалены записи завершённых задач всех серверов и их сохранённые логи. Активные задачи продолжат работу.") },
        confirmButton = { TextButton(onClick = { confirmClear = false; viewModel.clearHistory() }, enabled = !state.busy) { Text("Очистить") } },
        dismissButton = { TextButton(onClick = { confirmClear = false }) { Text("Отмена") } })
    if (confirmCancel && selected != null) AlertDialog(onDismissRequest = { confirmCancel = false },
        title = { Text("Отменить задачу?") }, text = { Text("Уже выполненные изменения сохранятся.") },
        confirmButton = { TextButton(onClick = { confirmCancel = false; viewModel.cancelSelected() }) { Text("Отменить задачу") } },
        dismissButton = { TextButton(onClick = { confirmCancel = false }) { Text("Назад") } })
    if (selected != null) {
        BackHandler { viewModel.closeDetail() }
        TaskDetail(selected, state.busy, state.error, viewModel::closeDetail, { viewModel.open(selected) }, { confirmCancel = true })
        return
    }
    PanelScaffold(topBar = { PanelTopBar(title = { Text("История задач", fontWeight = FontWeight.SemiBold) },
        navigationIcon = { onBack?.let { IconButton(onClick = it) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Назад") } } },
        actions = { IconButton(onClick = viewModel::refresh, enabled = !state.isLoading && !state.busy) { Icon(Icons.Default.Refresh, "Обновить") } }) },
        snackbarHost = { SnackbarHost(snack) }) { padding ->
        Refreshable(state.isLoading || state.busy, viewModel::refresh, Modifier.fillMaxSize().padding(padding)) {
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = refreshArrangement(12.dp)) {
            item { Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                PanelSecondaryButton(onClick = onEvents, modifier = Modifier.weight(1f)) { Text("События") }
                PanelSecondaryButton(onClick = { confirmClear = true }, enabled = !state.busy && !state.isLoading, modifier = Modifier.weight(1f)) { Text("Очистить") }
            } }
            item { SearchableChoice("Сервер", state.serverId, state.servers.map { it.id to listOfNotNull(it.name ?: it.id, it.host).joinToString(" · ") }, viewModel::server, allowEmpty = true) }
            item { LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) { listOf("all" to "Все", "active" to "Активные", "done" to "Завершённые", "failed" to "Ошибки").forEach { (id, label) -> item { PanelTab(state.filter == id, { viewModel.filter(id) }, label = { Text(label) }) } } } }
            state.error?.let { item { ErrorCard(it, viewModel::refresh) } }
            if (state.isLoading || state.busy) item { LinearProgressIndicator(Modifier.fillMaxWidth()) }
            if (!state.isLoading && state.filtered.isEmpty() && state.error == null) item { PanelCard { Text("Задач с выбранными фильтрами нет") } }
            items(state.filtered, key = { it.id }) { task -> PanelSurfaceCard(onClick = { viewModel.open(task) }, modifier = Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("${task.emoji.orEmpty()} ${task.name ?: task.id}".trim(), style = MaterialTheme.typography.titleMedium)
                    StatusBadge(taskStatusLabel(task.status), taskTone(task))
                    Text(task.serverName ?: task.serverId ?: "—", style = MaterialTheme.typography.bodyMedium)
                    Text(listOfNotNull(task.createdAt?.let(::displayTime), task.duration).joinToString(" · "), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            } }
        }
    }
    }
}

private fun taskTone(task: TaskSummary) = when (task.status) { "success", "completed" -> StatusTone.GOOD; "failed", "cancelled" -> StatusTone.BAD; "success_warn" -> StatusTone.WARNING; else -> StatusTone.NEUTRAL }

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun TaskDetail(task: TaskSummary, busy: Boolean, error: String?, onBack: () -> Unit, onRetry: () -> Unit, onCancel: () -> Unit) {
    val output = task.outputLines.takeIf { it.isNotEmpty() }?.joinToString("\n") ?: task.result?.output ?: task.error ?: "Нет вывода"
    PanelScaffold(topBar = { PanelTopBar(title = { Text(task.name ?: "Задача") }, navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Назад") } },
        actions = { IconButton(onClick = onRetry, enabled = !busy) { Icon(Icons.Default.Refresh, "Обновить вывод") } }) }) { padding ->
        LazyColumn(Modifier.fillMaxSize().padding(padding), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            error?.let { item { ErrorCard(it, onRetry) } }
            if (busy) item { LinearProgressIndicator(Modifier.fillMaxWidth()) }
            item { PanelCard {
                StatusBadge(taskStatusLabel(task.status), taskTone(task))
                InfoRow("Сервер", task.serverName ?: task.serverId ?: "—")
                InfoRow("Начало", displayTime(task.startedAt ?: task.createdAt))
                InfoRow("Длительность", task.duration ?: "—")
                if (!task.isDone) PanelSecondaryButton(onClick = onCancel, enabled = !busy) { Text("Отменить задачу") }
            } }
            task.error?.let { item { ErrorCard(it) } }
            item { Text("Вывод", style = MaterialTheme.typography.titleMedium) }
            item { PanelCard { SelectionContainer { Text(output, fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.bodySmall) } } }
        }
    }
}
