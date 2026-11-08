package com.bot4vps.mobile.ui.dashboard

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.clickable
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.repeatOnLifecycle
import com.bot4vps.mobile.data.model.*
import com.bot4vps.mobile.ui.components.*
import com.bot4vps.mobile.ui.settings.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.text.font.FontWeight
import kotlinx.serialization.json.*
import java.time.LocalTime

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DashboardScreen(onBack: (() -> Unit)? = null, onServer: (String) -> Unit, onServers: () -> Unit, onAddServer: () -> Unit,
    onMonitor: () -> Unit, onEvents: () -> Unit, onEvent: (String) -> Unit, onLogin: () -> Unit, viewModel: DashboardViewModel = hiltViewModel(), updates: UpdatesViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    val listState = rememberLazyListState()
    LaunchedEffect(state.update) { updates.acceptSnapshot(state.update) }
    LaunchedEffect(lifecycle, viewModel) { lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) { viewModel.observe() } }
    UpdateDialogs(updates)
    LaunchedEffect(lifecycle, updates) { lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) { updates.observe() } }
    PanelScaffold(topBar = { PanelTopBar(title = { Text("Обзор") }, navigationIcon = { onBack?.let { IconButton(onClick = it) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Назад") } } },
        actions = { IconButton(onClick = { viewModel.refresh(); updates.refresh() }) { Icon(Icons.Default.Refresh, "Обновить") } }) }) { padding ->
        Refreshable(state.loading, { viewModel.refresh(); updates.refresh() }, Modifier.fillMaxSize().padding(padding)) {
        LazyColumn(Modifier.fillMaxSize(), state = listState, contentPadding = PaddingValues(16.dp), verticalArrangement = refreshArrangement(14.dp)) {
            item(key = "greeting") {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(when (LocalTime.now().hour) { in 5..11 -> "Доброе утро!"; in 12..17 -> "Добрый день!"; in 18..22 -> "Добрый вечер!"; else -> "Доброй ночи!" }, style = MaterialTheme.typography.headlineLarge)
                    Text("Вот что происходит с вашей инфраструктурой", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            item(key = "summary") { PanelCard("Серверы") {
                Text("${state.online} в сети · ${state.offline} офлайн · ${state.servers.size} всего", style = MaterialTheme.typography.bodyMedium)
                state.serverError?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error) }
                if (state.servers.isEmpty()) Text(if (state.loading) "Загрузка…" else "Нет серверов", color = MaterialTheme.colorScheme.onSurfaceVariant)
                state.widgetServers.forEach { server -> DashboardServerCard(server, state.metrics[server.id], state.serverSamples[server.id].orEmpty()) { onServer(server.id) } }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    TextButton(onClick = onServers, modifier = Modifier.weight(1f)) { Text("Все серверы →") }
                    TextButton(onClick = onAddServer, modifier = Modifier.weight(1f)) { Text("Добавить сервер") }
                }
            } }
            item(key = "system") { PanelCard("Состояние системы") {
                DashboardSystem(state.system.takeIf { state.systemError == null }, state.samples)
                state.systemError?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
                TextButton(onClick = onMonitor, modifier = Modifier.fillMaxWidth()) { Text("Подробная информация →") }

            } }
            item(key = "events") { PanelCard("Журнал уведомлений") {
                state.eventsError?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                if (state.events.isEmpty()) Text(if (state.loading) "Загрузка событий…" else "Событий пока нет", color = MaterialTheme.colorScheme.onSurfaceVariant)
                state.events.forEach { event -> Row(Modifier.fillMaxWidth().clickable { event.text("id")?.let(onEvent) }.padding(vertical = 6.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(event.text("message") ?: event.text("title") ?: "Событие", Modifier.weight(1f), style = MaterialTheme.typography.bodySmall, maxLines = 2)
                    Text(displayTime(event.text("timestamp")), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                } }
                TextButton(onClick = onEvents) { Text("Все события →") }
            } }
            item(key = "updates") { ActionRow("Обновления Bot4VPS", if (updates.busy) "Проверяем обновления…" else updates.available?.let { "Доступна версия $it" } ?: "Проверить наличие новой версии", Icons.Default.SystemUpdateAlt, updates::checkFromDashboard, enabled = !updates.busy && !updates.active) }
            updates.error?.let { item { ErrorCard(it, updates::checkFromDashboard) } }
            if (updates.progress != null) item { UpdateProgress(updates, onLogin) }
        }
    }
    }
}

@Composable
private fun DashboardServerCard(server: ServerSummary, metrics: ServerMetrics?, samples: List<SystemSample>, onClick: () -> Unit) {
    val online = server.online == true
    PanelSurfaceCard(onClick = onClick, modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(server.name ?: server.id, Modifier.weight(1f), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
                StatusBadge(if (!online) "Офлайн" else if (!server.sshError.isNullOrBlank() || metrics?.ok == false) "SSH недоступен" else "В сети", if (!online) StatusTone.BAD else if (!server.sshError.isNullOrBlank() || metrics?.ok == false) StatusTone.WARNING else StatusTone.GOOD)
            }
            LoadChart(metrics?.cpu, metrics?.ramPct, samples)
            Text(server.hostIp ?: server.host ?: "—", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(metrics?.uptime ?: metrics?.error ?: "Загрузка показателей…", style = MaterialTheme.typography.labelSmall, maxLines = 2, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}
