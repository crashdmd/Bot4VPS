package com.bot4vps.mobile.ui.servers

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import android.widget.Toast
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.repeatOnLifecycle
import com.bot4vps.mobile.data.model.*
import com.bot4vps.mobile.ui.components.*
import com.bot4vps.mobile.ui.services.serviceIcon
import com.bot4vps.mobile.ui.services.serviceColor
import com.bot4vps.mobile.ui.services.taskStatusLabel
import kotlinx.coroutines.delay
import kotlinx.serialization.json.*

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun ServerDetailScreen(serverId: String, onBack: () -> Unit, onTerminal: () -> Unit = {}, onMetrics: () -> Unit = {},
    onEdit: () -> Unit = {}, onAcceptHostKey: () -> Unit = {}, onSection: (String) -> Unit = {},
    onService: (ServiceKind) -> Unit = {}, onScripts: () -> Unit = {}, onHistory: (String?) -> Unit = {}, viewModel: ServerDetailViewModel = hiltViewModel()) {
    val state by viewModel.ui.collectAsStateWithLifecycle()
    val server = state.server
    val clipboard = LocalClipboardManager.current
    val context = LocalContext.current
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(lifecycle, viewModel) { lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) { while (true) { delay(5000); viewModel.poll() } } }
    var menu by remember { mutableStateOf(false) }
    var reboot by remember { mutableStateOf(false) }
    var commandOpen by rememberSaveable { mutableStateOf(false) }
    if (reboot) AlertDialog(onDismissRequest = { reboot = false }, title = { Text("Перезагрузить сервер?") }, text = { Text(server?.name ?: serverId) },
        confirmButton = { TextButton(onClick = { reboot = false; viewModel.reboot() }) { Text("Перезагрузить") } }, dismissButton = { TextButton(onClick = { reboot = false }) { Text("Отмена") } })
    PanelScaffold(topBar = { PanelTopBar(title = { Text(server?.name ?: "Сервер", fontWeight = FontWeight.SemiBold) },
        navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Назад") } }, actions = {
            IconButton(onClick = viewModel::load, enabled = !state.isLoading) { Icon(Icons.Default.Refresh, "Обновить") }
            Box { IconButton(onClick = { menu = true }) { Icon(Icons.Default.MoreVert, "Действия сервера") }
                DropdownMenu(menu, { menu = false }) {
                    DropdownMenuItem(text = { Text("Изменить сервер") }, onClick = { menu = false; onEdit() })
                    DropdownMenuItem(text = { Text("Проверить подключение") }, enabled = !state.busy, onClick = { menu = false; viewModel.probe() })
                    DropdownMenuItem(text = { Text("Выполнить команду") }, enabled = !state.busy && !state.blocked, onClick = { menu = false; commandOpen = true })
                    DropdownMenuItem(text = { Text("Перезагрузить", color = MaterialTheme.colorScheme.error) }, enabled = !state.busy && !state.blocked, onClick = { menu = false; reboot = true })
                }
            }
        }) }) { padding ->
        Refreshable(state.isLoading, viewModel::load, Modifier.fillMaxSize().padding(padding)) {
        LazyColumn(Modifier.fillMaxSize().imePadding(), contentPadding = PaddingValues(16.dp), verticalArrangement = refreshArrangement(12.dp)) {
            if (state.isLoading && server == null) item { LinearProgressIndicator(Modifier.fillMaxWidth()) }
            state.error?.let { item { ErrorCard(it, viewModel::load) } }
            if (server != null) {
                item {
                    val address = state.monitor.text("host_ip") ?: server.host ?: "—"
                    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(address, Modifier.weight(1f, fill = false), maxLines = 1, overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis, style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            IconButton(onClick = { clipboard.setText(AnnotatedString(address)); Toast.makeText(context, "IP скопирован", Toast.LENGTH_SHORT).show() }, enabled = address != "—") { Icon(Icons.Default.ContentCopy, "Копировать IP", Modifier.size(18.dp)) }
                            Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                            StatusBadge(when (state.online) { true -> "В сети"; false -> "Офлайн"; null -> "Сеть —" }, when (state.online) { true -> StatusTone.GOOD; false -> StatusTone.BAD; null -> StatusTone.NEUTRAL })
                            val ssh = state.probe?.info?.ssh ?: state.metrics?.ok
                            StatusBadge(when { state.keyExists == false -> "Нет ключа"; ssh == true -> "SSH"; state.portOk == false || ssh == false -> "SSH ×"; else -> "SSH —" }, when { ssh == true -> StatusTone.GOOD; state.blocked || ssh == false -> StatusTone.BAD; else -> StatusTone.NEUTRAL })
                        }
                        }
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            TextButton(onClick = { reboot = true }, enabled = !state.busy && !state.blocked) { Icon(Icons.Default.RestartAlt, null, Modifier.size(18.dp)); Text("Перезагрузить") }
                            TextButton(onClick = onTerminal, enabled = !state.blocked) { Icon(Icons.Default.Terminal, null, Modifier.size(18.dp)); Text("Терминал") }
                        }
                        state.availability.text("ssh_error")?.takeIf(String::isNotBlank)?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error) }
                    }
                }
                if (state.keyExists == false) item { ErrorCard("SSH-ключ не найден: ${server.keyPath.orEmpty()}. Выберите ключ в настройках сервера.") }
                if (state.probe?.hostKeyMismatch == true) item { PanelCard("Ключ сервера изменился") {
                    Text("Проверьте отпечаток ключа перед принятием нового.", color = MaterialTheme.colorScheme.error)
                    PanelSecondaryButton(onClick = onAcceptHostKey) { Text("Проверить и принять ключ") }
                } }
                item { StatTile("CPU", state.metrics?.cpu?.let { "%.1f%%".format(it) } ?: "—", Modifier.fillMaxWidth(), state.metrics?.cpu, state.metrics?.load?.let { "Load: $it" } ?: "—") }
                item { StatTile("Память", state.metrics?.ramPct?.let { "%.1f%%".format(it) } ?: "—", Modifier.fillMaxWidth(), state.metrics?.ramPct, state.metrics?.ram ?: "—") }
                item { StatTile("Диск", state.metrics?.diskPct?.let { "%.1f%%".format(it) } ?: "—", Modifier.fillMaxWidth(), state.metrics?.diskPct, state.metrics?.disk ?: "—") }
                item { PanelCard("Мониторинг") {
                    InfoRow("Load", state.metrics?.load ?: "—")
                    InfoRow("Время работы", state.metrics?.uptime ?: "—")
                    Text(if (state.metrics == null) "Загрузка показателей…" else if (state.metrics?.ok != true) state.metrics?.error ?: "Показатели недоступны" else "CPU, память и диск", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    TextButton(onClick = onMetrics) { Icon(Icons.Default.ShowChart, null, Modifier.size(18.dp)); Text("Открыть графики") }
                } }
                item { PanelCard("Информация о системе") {
                    val system = state.monitor["system"] as? JsonObject
                    val probe = state.probe?.info
                    InfoRow("Имя хоста", probe?.hostname ?: system?.text("hostname") ?: "—")
                    InfoRow("ОС", listOfNotNull(probe?.os ?: system?.text("os"), probe?.osVersion ?: system?.text("os_version")).joinToString(" "))
                    InfoRow("Ядро", probe?.kernel ?: system?.text("kernel") ?: "—")
                    InfoRow("Архитектура", probe?.arch ?: system?.text("arch") ?: "—")
                    InfoRow("SSH", "${server.user ?: "—"}@${server.host ?: "—"}:${server.port ?: 22}")
                    InfoRow("Авторизация", if (server.authType == "key") "SSH-ключ" else "Пароль")
                    server.keyPath?.takeIf(String::isNotBlank)?.let { InfoRow("Ключ", it) }
                    if (server.certificateCheck == true) {
                        InfoRow("Домен SSL", server.sslHost ?: state.monitor.text("ssl_host") ?: "—")
                        val cert = state.monitor["certificate"] as? JsonObject
                        val days = cert?.number("days_left")?.toInt()
                        InfoRow("Срок SSL", days?.let { if (it < 0) "Истёк" else "$it дн." } ?: "Нет данных")
                    }
                    TextButton(onClick = onEdit) { Text("Изменить подключение") }
                } }
                item { PanelCard("Действия с сервером") {
                    PanelActionLink("Настройки сервера", "Подключение, доступ, защита и система", Icons.Default.Tune, { onSection("quick_setup") })
                    ServiceKind.entries.filter { it != ServiceKind.SCRIPTS }.forEach { kind ->
                        val service = state.services[kind]
                        val error = state.serviceErrors[kind]
                        val subtitle = when { error != null -> "Не удалось получить состояние: $error"; service == null -> "Загрузка состояния…";
                            service.blocked -> service.blockReason; service.classic -> "Классический конфиг · нужна миграция";
                            service.installed -> (if (serviceActive(service.status)) "Работает" else "Остановлен") + service.status.text("version")?.let { " · $it" }.orEmpty(); else -> "Не установлен · настроить" }
                        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                        PanelActionLink(kind.title, subtitle, serviceIcon(kind), { onService(kind) }, iconColor = serviceColor(kind))
                    }
                    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                    PanelActionLink("Резервные копии", "Архивы, восстановление и расписание этого сервера", Icons.Default.Backup, { onSection("backups") })
                    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                    PanelActionLink("Скрипты", "Запустить сценарий на этом сервере", Icons.Default.Code, onScripts, enabled = !state.blocked)
                } }
                item { PanelCard("Задачи сервера") {
                    state.runningTask?.let { task ->
                        Text(task.name ?: "Активная задача", style = MaterialTheme.typography.titleSmall)
                        StatusBadge(taskStatusLabel(task.status))
                        TextButton(onClick = { onHistory(task.id) }) { Text("Открыть вывод") }
                    }
                    if (state.runningTask == null) Text("Сейчас ничего не выполняется", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    if (state.queue.isNotEmpty()) {
                        Text("В очереди: ${state.queue.size}")
                        state.queue.take(3).forEach { task -> TextButton(onClick = { onHistory(task.id) }) { Text(task.name ?: task.id) } }
                    }
                    if (state.queueState.flag("paused")) StatusBadge("Очередь приостановлена", StatusTone.WARNING)
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        TextButton(onClick = { onHistory(null) }) { Text("История сервера") }
                        TextButton(onClick = { onSection("queues") }) { Text("Управлять очередью") }
                    }
                } }
                item { PanelCard("Недавние события") {
                    if (state.eventsError != null) Text(state.eventsError ?: "", color = MaterialTheme.colorScheme.error)
                    else if (state.events.isEmpty()) Text("Недавних событий нет", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    state.events.forEach { event ->
                        Text(event.text("title") ?: event.text("message") ?: "Событие", style = MaterialTheme.typography.bodyMedium)
                        Text(displayTime(event.text("timestamp") ?: event.text("created_at")), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                } }
            }
            if (commandOpen) item { PanelCard("Выполнить команду") {
                PanelTextField(state.command, viewModel::onCommandChange, label = { Text("Команда") }, singleLine = true, modifier = Modifier.fillMaxWidth(),
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send), keyboardActions = KeyboardActions(onSend = { viewModel.exec() }))
                Row { PanelButton(onClick = viewModel::exec, enabled = !state.busy && !state.blocked) { Text("Выполнить") }; TextButton(onClick = { commandOpen = false }) { Text("Закрыть") } }
                state.execOutput?.let { SelectionContainer { Text(it, fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.bodySmall) } }
            } }
            state.actionMessage?.let { item { Text(it, style = MaterialTheme.typography.bodyMedium) } }
        }
    }
    }
}
