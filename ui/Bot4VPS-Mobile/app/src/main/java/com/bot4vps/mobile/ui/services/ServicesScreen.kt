package com.bot4vps.mobile.ui.services

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.res.vectorResource
import com.bot4vps.mobile.R
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import com.bot4vps.mobile.data.model.*
import com.bot4vps.mobile.ui.components.*
import com.bot4vps.mobile.ui.scripts.ScriptsScreen

@Composable
fun serviceIcon(kind: ServiceKind): ImageVector = when (kind) {
    ServiceKind.WIREGUARD -> ImageVector.vectorResource(R.drawable.ic_service_wireguard)
    ServiceKind.DOCKER -> ImageVector.vectorResource(R.drawable.ic_service_docker)
    ServiceKind.XUI -> ImageVector.vectorResource(R.drawable.ic_service_xui)
    ServiceKind.SCRIPTS -> Icons.Default.Terminal
}

@Composable
fun serviceColor(kind: ServiceKind): Color {
    val light = MaterialTheme.colorScheme.background.luminance() > .5f
    return when (kind) {
        ServiceKind.WIREGUARD -> if (light) Color(0xFF88171A) else Color(0xFFCF6367)
        ServiceKind.DOCKER -> if (light) Color(0xFF1877C9) else Color(0xFF2496ED)
        ServiceKind.XUI -> if (light) Color(0xFF0C8F6C) else Color(0xFF30E0B0)
        ServiceKind.SCRIPTS -> MaterialTheme.colorScheme.primary
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ServicesScreen(onServer: (ServiceKind, String) -> Unit, onFiles: () -> Unit, onScriptsFiles:()->Unit=onFiles, onOperation:(String)->Unit={}, onHistory:(String)->Unit={}, onQueues:()->Unit={}, onBackups:()->Unit={}, viewModel: ServicesViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsState()
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(lifecycle, viewModel) { lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) { viewModel.observe() } }
    val listState = rememberLazyListState()
    val kind = state.selected
    if (kind == ServiceKind.SCRIPTS) {
        ScriptsScreen(onFiles = onScriptsFiles, onOperation=onOperation, onHistory=onHistory, onChooseService = { viewModel.select(null) })
        return
    }
    BackHandler(enabled = kind != null) { viewModel.select(null) }
    var menu by remember { mutableStateOf(false) }
    PanelScaffold(topBar = {
        PanelTopBar(title = {
            if (kind == null) Text("Сервисы", fontWeight = FontWeight.SemiBold)
            else TextButton(onClick = { menu = true }) { Text(kind.title, style = MaterialTheme.typography.titleLarge); Icon(Icons.Default.ExpandMore, "Выбрать сервис") }
            DropdownMenu(menu, { menu = false }) {
                ServiceKind.entries.forEach { service ->
                    DropdownMenuItem(text = { Text(service.title) }, leadingIcon = { Icon(serviceIcon(service), null) }, onClick = { menu = false; viewModel.select(service) })
                    if (service == ServiceKind.XUI) DropdownMenuItem(text = { Text("Резервные копии") }, leadingIcon = { Icon(Icons.Default.Backup, null) }, onClick = { menu = false; onBackups() })
                }
            }
        }, actions = {
            if (kind != null) {
                IconButton(onClick = viewModel::sort) { Icon(Icons.Default.Sort, "Сортировка") }
                IconButton(onClick = viewModel::refresh, enabled = !state.loading) { Icon(Icons.Default.Refresh, "Обновить") }
            }
        })
    }) { padding ->
        Refreshable(state.loading, viewModel::refresh, Modifier.fillMaxSize().padding(padding)) {
        LazyColumn(Modifier.fillMaxSize(), state = listState, contentPadding = PaddingValues(16.dp), verticalArrangement = refreshArrangement(12.dp)) {
            if (kind == null) {
                item { Text("Выберите, с чем работать", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.SemiBold) }
                item { Text("Управление сервисами на ваших серверах", color = MaterialTheme.colorScheme.onSurfaceVariant) }
                ServiceKind.entries.forEach { service ->
                    item { ActionRow(service.title, service.description, serviceIcon(service), { viewModel.select(service) }, iconColor = serviceColor(service)) }
                    if (service == ServiceKind.XUI) item { ActionRow("Резервные копии", "Архивы панели и серверов, восстановление и расписание", Icons.Default.Backup, onBackups) }
                }
                item { ActionRow("Очереди задач", "Выполнение и ожидание задач на серверах", Icons.Default.Queue, onQueues) }
            } else {
                item { Text(kind.description, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                item { PanelSearchField(state.search, viewModel::search, placeholder = "Найти сервер", modifier = Modifier.fillMaxWidth()) }
                item { LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    items(InstallationFilter.entries.filter { it != InstallationFilter.CLASSIC || kind == ServiceKind.WIREGUARD }) { filter ->
                        val count = if (filter == InstallationFilter.ALL) state.rows.size else filterServiceServers(state.rows, filter, "", null).size
                        PanelTab(state.filter == filter, onClick = { viewModel.filter(filter) }, label = { Text("${filter.title} · $count") })
                    }
                } }
                val groups = state.rows.mapNotNull { it.group?.takeIf(String::isNotBlank) }.distinct().sorted()
                if (groups.isNotEmpty()) item { LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    item { PanelTab(state.group == null, { viewModel.group(null) }, label = { Text("Все группы") }) }
                    items(groups) { group -> PanelTab(state.group == group, { viewModel.group(group) }, label = { Text(group) }) }
                } }
                state.error?.let { item { ErrorCard(it, viewModel::refresh) } }
                if (state.loading && state.rows.isEmpty()) item { LinearProgressIndicator(Modifier.fillMaxWidth()) }
                item { Text("${state.filtered.size} серверов · ${if (state.sortByName) "по имени" else "установленные сначала"}", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                if (!state.loading && state.filtered.isEmpty() && state.error == null) item { PanelCard { Text(if (state.rows.isEmpty()) "Добавьте сервер, чтобы начать работу" else "Нет серверов с выбранными фильтрами") } }
                items(state.filtered, key = { it.id }) { server ->
                    PanelSurfaceCard(onClick = { onServer(kind, server.id) }, modifier = Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                                Icon(serviceIcon(kind), null, Modifier.size(20.dp), tint = serviceColor(kind))
                                Column(Modifier.weight(1f)) {
                                    Text(server.name, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                                    Text(listOfNotNull(server.group, server.host.takeIf { it.isNotBlank() }).joinToString(" · "), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                }
                                Icon(Icons.Default.ChevronRight, "Открыть")
                            }
                            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                                StatusBadge(if (server.blocked) server.blockReason else if (server.classic) "Нужна миграция" else if (server.installed) "Установлен" else "Не установлен",
                                    if (server.blocked) StatusTone.BAD else if (server.classic) StatusTone.WARNING else if (server.installed) StatusTone.GOOD else StatusTone.NEUTRAL)
                                server.status.text("version")?.takeIf { it.isNotBlank() }?.let { Text(it, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                            }
                            if (server.installed && !server.blocked) {
                                val stats = server.status["stats"] as? kotlinx.serialization.json.JsonObject
                                val detail = when (kind) {
                                    ServiceKind.DOCKER -> "Контейнеры: ${stats?.text("running") ?: "—"} / ${stats?.text("total") ?: "—"}"
                                    ServiceKind.WIREGUARD -> "Профили: ${stats?.text("online") ?: "—"} онлайн / ${stats?.text("total") ?: "—"} всего"
                                    else -> if (serviceActive(server.status)) "Панель работает" else "Панель остановлена"
                                }
                                Text(detail, style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    }
                }
            }
        }
    }
    }
}
