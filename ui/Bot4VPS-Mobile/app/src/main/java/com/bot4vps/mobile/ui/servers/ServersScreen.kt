package com.bot4vps.mobile.ui.servers

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import android.widget.Toast
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.repeatOnLifecycle
import com.bot4vps.mobile.data.model.*
import com.bot4vps.mobile.ui.components.*

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun ServersScreen(onOpenServer: (String) -> Unit, onCreate: () -> Unit = {}, onGroups: () -> Unit = {},
    viewModel: ServersViewModel = hiltViewModel()) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    val listState = rememberLazyListState()
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(lifecycle, viewModel) { lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) { viewModel.observe() } }
    var revealAll by rememberSaveable { mutableStateOf(false) }
    PanelScaffold(topBar = { PanelTopBar(title = { Text("Серверы", fontWeight = FontWeight.SemiBold) }, actions = {
        IconButton(onClick = onCreate) { Icon(Icons.Default.Add, "Добавить сервер") }
        IconButton(onClick = onGroups) { Icon(Icons.Default.Settings, "Настройки групп") }
        IconButton(onClick = viewModel::refresh) { Icon(Icons.Default.Refresh, "Обновить") }
    }) }) { padding ->
        Refreshable(state.isLoading, viewModel::refresh, Modifier.fillMaxSize().padding(padding)) {
        Column(Modifier.fillMaxSize()) {
            PanelSearchField(state.search, viewModel::search, placeholder = "Поиск серверов…",
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp))
            LazyRow(contentPadding = PaddingValues(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                item { PanelTab(state.selectedGroup == null, { viewModel.selectGroup(null) }, label = { Text("Все · ${state.servers.size}") }) }
                items(state.groups, key = { it }) { group -> PanelTab(state.selectedGroup == group, { viewModel.selectGroup(group) }, label = { Text("$group · ${state.servers.count { it.group == group }}") }) }
            }
            LazyRow(contentPadding = PaddingValues(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                items(ServerListSort.entries) { sort ->
                    PanelTab(state.sort == sort, { viewModel.sort(sort) }, label = {
                        Text(sort.title + if (state.sort == sort) if (state.descending) " ↓" else " ↑" else "")
                    })
                }
                if (state.sort == ServerListSort.NAME) item { IconButton(onClick = { revealAll = !revealAll }) { Icon(if (revealAll) Icons.Default.VisibilityOff else Icons.Default.Visibility, if (revealAll) "Скрыть все IP" else "Показать все IP") } }
            }
            LazyColumn(Modifier.weight(1f), state = listState, contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 4.dp, bottom = 16.dp), verticalArrangement = refreshArrangement(8.dp)) {
                state.error?.let { item(key = "error") { ErrorCard(it, viewModel::refresh) } }
                if (state.isLoading && state.servers.isEmpty()) item(key = "initial") { Box(Modifier.fillMaxWidth().height(80.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator() } }
                if (!state.isLoading && state.filtered.isEmpty() && state.error == null) item(key = "empty") { PanelCard { Text(if (state.servers.isEmpty()) "Добавьте первый сервер" else if(state.selectedGroup != null && state.search.isBlank()) "В этой группе пока нет серверов" else "Серверы не найдены") } }
                items(state.filtered, key = { it.id }) { server -> ServerListCard(server, revealAll, state.sort) { onOpenServer(server.id) } }
            }
        }
    }
    }
}

@Composable
fun ServerListCard(server: ServerSummary, revealAll: Boolean = false, sort: ServerListSort = ServerListSort.NAME, onClick: () -> Unit) {
    var revealed by rememberSaveable(server.id) { mutableStateOf(false) }
    val clipboard = LocalClipboardManager.current
    val context = LocalContext.current
    val address = server.hostIp?.takeIf(String::isNotBlank) ?: server.host?.takeIf(String::isNotBlank)
    val sshWarning = server.online == true && !server.sshError.isNullOrBlank()
    PanelSurfaceCard(onClick = onClick, modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(horizontal = 12.dp, vertical = 8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Row(Modifier.weight(1f), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text(server.name ?: server.id, Modifier.weight(1f, fill = false), style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    if (server.hasRunning) Icon(Icons.Default.PlayArrow, "Выполняется задача", Modifier.size(14.dp), tint = MaterialTheme.colorScheme.primary)
                }
                StatusBadge(when { sshWarning -> "В сети ⚠"; server.online == true -> "В сети"; server.online == false -> "Офлайн"; else -> "Неизвестно" },
                    when { sshWarning -> StatusTone.WARNING; server.online == true -> StatusTone.GOOD; server.online == false -> StatusTone.BAD; else -> StatusTone.NEUTRAL })
            }
            Row(Modifier.heightIn(min = 32.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(if(sort != ServerListSort.NAME) serverListDetail(server,sort) else if (address == null) "—" else if (revealAll || revealed) address else "••••••••",
                    modifier = Modifier.weight(1f), style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
                if (sort == ServerListSort.NAME && !revealAll) IconButton(onClick = { revealed = !revealed }, enabled = address != null) {
                    Icon(if (revealed) Icons.Default.VisibilityOff else Icons.Default.Visibility,
                        if (revealed) "Скрыть IP" else "Показать IP", Modifier.size(16.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                if(sort == ServerListSort.NAME) IconButton(onClick = { address?.let { clipboard.setText(AnnotatedString(it)); Toast.makeText(context, "IP скопирован", Toast.LENGTH_SHORT).show() } }, enabled = address != null) {
                    Icon(Icons.Default.ContentCopy, "Копировать IP", Modifier.size(16.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
    }
}
