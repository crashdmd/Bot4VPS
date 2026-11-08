package com.bot4vps.mobile.ui.services

import android.content.Intent
import android.net.Uri
import android.widget.Toast
import androidx.compose.foundation.layout.*
import androidx.compose.ui.platform.LocalContext
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import com.bot4vps.mobile.data.model.*
import com.bot4vps.mobile.ui.components.*
import com.bot4vps.mobile.ui.control.NativeField
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.coroutineScope
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.serialization.json.*

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ServiceDetailScreen(onBack: () -> Unit, onOperation: (String) -> Unit, onAdvanced: () -> Unit, onHistory: (String?) -> Unit,
    viewModel: ServiceDetailViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val listState = rememberLazyListState()
    val kind = viewModel.kind
    val detail = state.detail
    val data = detail?.state ?: JsonObject(emptyMap())
    val installed = data.flag("installed") && !data.flag("needs_migration")
    val blocked = detail?.server?.blocked == true
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(viewModel, lifecycle) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
            viewModel.refresh()
            coroutineScope {
                launch { viewModel.observe() }
                while (true) { viewModel.poll(); delay(2000) }
            }
        }
    }
    fun operation(id: String, values: Map<String, JsonElement> = emptyMap()) { viewModel.handoff(id, values); onOperation(id) }
    XuiSiteDialog(state, viewModel)
    state.editor?.let { editor -> ServiceEditorSheet(editor, state.busy, state.error, viewModel::dismissEditor, viewModel::submit, detail?.server?.name.orEmpty()) }
    PanelScaffold(topBar = {
        PanelTopBar(title = { Text(kind.title, fontWeight = FontWeight.SemiBold) }, navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Назад") } }, actions = {
            IconButton(onClick = viewModel::refresh, enabled = !state.loading && !state.busy) { Icon(Icons.Default.Refresh, "Обновить") }
            if (kind != ServiceKind.XUI) IconButton(onClick = onAdvanced) { Icon(Icons.Default.MoreVert, "Дополнительные действия") }
        })
    }) { padding ->
        Refreshable(state.loading, viewModel::refresh, Modifier.fillMaxSize().padding(padding)) {
        LazyColumn(Modifier.fillMaxSize(), state = listState, contentPadding = PaddingValues(16.dp), verticalArrangement = refreshArrangement(12.dp)) {
            item { PanelCard {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Icon(serviceIcon(kind), null, Modifier.size(24.dp), tint = serviceColor(kind))
                    Column(Modifier.weight(1f)) {
                        Text(detail?.server?.name ?: "Загрузка сервера…", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
                        detail?.server?.host?.let { Text(it, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                    }
                }
                if (detail != null) StatusBadge(if (blocked) detail.server.blockReason else if (data.flag("needs_migration")) "Классический конфиг" else if (installed) "Установлен" else "Не установлен",
                    if (blocked) StatusTone.BAD else if (installed) StatusTone.GOOD else StatusTone.NEUTRAL)
                if (installed && !blocked) InfoRow("Сервис", if (serviceActive(data)) "Работает" else "Остановлен")
                data.text("version")?.let { InfoRow("Версия", it) }
            } }
            if (state.loading && detail == null) item { LinearProgressIndicator(Modifier.fillMaxWidth()) }
            if (state.editor == null) state.error?.let { item { ErrorCard(it, viewModel::refresh) } }
            state.notice?.let { item { Text(it, color = MaterialTheme.colorScheme.primary, style = MaterialTheme.typography.bodyMedium) } }
            state.task?.let { task -> item { PanelCard("Выполнение") {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) { Text(task.name ?: "Задача"); StatusBadge(taskStatusLabel(task.status), if (task.status == "failed") StatusTone.BAD else StatusTone.NEUTRAL) }
                task.outputLines.lastOrNull()?.let { Text(it, maxLines = 3, style = MaterialTheme.typography.bodySmall) }
                TextButton(onClick = { onHistory(task.id) }) { Text("Открыть вывод задачи") }
            } } }
            if (blocked) item { ErrorCard("${detail?.server?.blockReason}. Управление станет доступно после восстановления соединения.") }
            else if (detail != null && !installed) {
                item { ActionRow(if (data.flag("needs_migration")) "Перенести WireGuard в Bot4VPS" else "Установить ${kind.title}",
                    if (data.flag("needs_migration")) "Подготовить существующий конфиг к управлению" else "Настроить сервис на этом сервере", Icons.Default.Add,
                    { viewModel.action(if (data.flag("needs_migration")) "migrate" else "install", if (data.flag("needs_migration")) "Миграция WireGuard" else "Установка ${kind.title}") }) }
            } else if (installed && detail != null) {
                val stats = data["stats"] as? JsonObject ?: JsonObject(emptyMap())
                item { Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    when (kind) {
                        ServiceKind.DOCKER -> { StatTile("Запущено / всего", "${stats.text("running") ?: "—"} / ${stats.text("total") ?: "—"}", Modifier.weight(1f)); StatTile("Образы", stats.text("images") ?: "—", Modifier.weight(1f)); StatTile("Тома", stats.text("volumes") ?: "—", Modifier.weight(1f)) }
                        ServiceKind.WIREGUARD -> { StatTile("Онлайн / всего", "${stats.text("online") ?: "—"} / ${stats.text("total") ?: "—"}", Modifier.weight(1f)); StatTile("Трафик", displayBytes(stats.number("rx_bytes")?.let { it + (stats.number("tx_bytes") ?: 0.0) }), Modifier.weight(1f)) }
                        else -> { StatTile("Порт панели", data.text("port") ?: "—", Modifier.weight(1f)); StatTile("Автозапуск", if (data.flag("enabled")) "Включён" else "Выключен", Modifier.weight(1f)) }
                    }
                } }
                val tabs = when (kind) { ServiceKind.DOCKER -> listOf("containers" to "Контейнеры", "images" to "Образы", "compose" to "Compose", "settings" to "Настройки"); ServiceKind.WIREGUARD -> listOf("profiles" to "Профили", "settings" to "Настройки"); else -> listOf("overview" to "Панель", "settings" to "Настройки") }
                item { LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) { items(tabs) { (id, title) -> PanelTab(state.tab == id, { viewModel.tab(id) }, label = { Text(title) }) } } }
                when {
                    kind == ServiceKind.WIREGUARD && state.tab == "profiles" -> {
                        item { PanelSearchField(state.search, viewModel::search, placeholder = "Имя или IP профиля", modifier = Modifier.fillMaxWidth()) }
                        item { PanelSecondaryButton(onClick = { viewModel.edit("POST /api/services/wireguard/{server_id}/profiles", "Добавить профиль") }, modifier = Modifier.fillMaxWidth()) { Icon(Icons.Default.Add, null); Text("Добавить профиль") } }
                        val profiles = data.objects("profiles").filter { state.search.isBlank() || it.text("name").orEmpty().contains(state.search, true) || it["allowed_ips"].toString().contains(state.search, true) }
                        if (profiles.isEmpty()) item { PanelCard { Text("Профилей нет. Добавьте профиль для подключения к VPN.") } }
                        items(profiles, key = { it.text("name").orEmpty() }) { profile -> WireguardProfileCard(profile, viewModel, ::operation) }
                    }
                    kind == ServiceKind.DOCKER && state.tab == "containers" -> {
                        item { PanelSearchField(state.search, viewModel::search, placeholder = "Контейнер или образ", modifier = Modifier.fillMaxWidth()) }
                        item { LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) { items(listOf("all" to "Все", "running" to "Запущены", "stopped" to "Остановлены")) { (id, title) -> PanelTab(state.recordFilter == id, { viewModel.filter(id) }, label = { Text(title) }) } } }
                        item { PanelSecondaryButton(onClick = { viewModel.action("container_run", "Создать контейнер", locked = emptySet()) }, modifier = Modifier.fillMaxWidth()) { Icon(Icons.Default.Add, null); Text("Создать контейнер") } }
                        val containers = data.objects("containers").filter { record ->
                            val running = record.text("state") == "running" || record.text("status").orEmpty().startsWith("Up")
                            (state.recordFilter == "all" || running == (state.recordFilter == "running")) && (state.search.isBlank() || listOf(record.text("name"), record.text("image")).any { it.orEmpty().contains(state.search, true) })
                        }
                        if (containers.isEmpty()) item { PanelCard { Text("Нет контейнеров с выбранными фильтрами") } }
                        items(containers, key = { it.text("id") ?: it.text("name").orEmpty() }) { record -> DockerContainerCard(record, viewModel, ::operation) }
                    }
                    kind == ServiceKind.DOCKER && state.tab == "images" -> {
                        item { ActionRow("Загрузить образ", "Docker Hub или другой реестр", Icons.Default.Download, { viewModel.action("image_pull", "Загрузить образ", locked = emptySet()) }) }
                        if (detail.images.isEmpty()) item { PanelCard { Text("На сервере нет образов") } }
                        items(detail.images, key = { (it.text("id") ?: "") + ":" + it.text("repository") + ":" + it.text("tag") }) { image ->
                            val name = "${image.text("repository") ?: "<none>"}:${image.text("tag") ?: "latest"}"
                            PanelCard(name) { InfoRow("Размер", image.text("size") ?: "—"); TextButton(onClick = { viewModel.action("image_rm", "Удалить образ $name", mapOf("image" to JsonPrimitive(image.text("id") ?: name))) }) { Text("Удалить образ", color = MaterialTheme.colorScheme.error) } }
                        }
                    }
                    kind == ServiceKind.DOCKER && state.tab == "compose" -> {
                        val projects = detail.stacks.objects("rows")
                        item { PanelSearchField(state.search, viewModel::search, placeholder = "Найти проект", modifier = Modifier.fillMaxWidth()) }
                        if (detail.stacks["server_accessible"] == JsonPrimitive(false)) item { ErrorCard("Не удалось прочитать проекты на сервере. Доступны файлы библиотеки; операции развёртывания требуют соединения.") }
                        val filtered = projects.filter { state.search.isBlank() || it.text("name").orEmpty().contains(state.search, true) || it.text("working_dir").orEmpty().contains(state.search, true) }
                        if (filtered.isEmpty()) item { PanelCard { Text("Нет проектов с выбранными фильтрами") } }
                        items(filtered, key = { (it.text("source") ?: "") + ":" + (it.text("key") ?: it.text("name").orEmpty()) }) { project ->
                            ComposeProjectCard(project, detail.stacks["server_accessible"] != JsonPrimitive(false), viewModel, ::operation)
                        }
                    }
                    kind == ServiceKind.XUI && state.tab == "overview" -> {
                        item { XuiOverview(data, viewModel, ::operation) }
                    }
                    else -> {
                        item { ServiceSettings(data, kind, viewModel, ::operation) }
                    }
                }
                if (kind != ServiceKind.XUI) item { ActionRow("Дополнительные действия", "Расширенные операции ${kind.title}", Icons.Default.Tune, onAdvanced) }
            }
        }
    }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ServiceEditorSheet(editor: ServiceEditor, busy: Boolean, error: String?, onDismiss: () -> Unit, onSubmit: (JsonObject) -> Unit, server: String) {
    fun generated() = buildString { val random = java.security.SecureRandom(); val alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"; repeat(20) { append(alphabet[random.nextInt(alphabet.length)]) } }
    var values by remember(editor) { mutableStateOf(if (editor.xuiAction == "change_password") JsonObject(editor.initial + ("password" to JsonPrimitive(generated()))) else if (editor.xuiAction == "change_path") JsonObject(editor.initial + ("path" to JsonPrimitive(generated()))) else editor.initial) }
    var confirmSite by remember(editor) { mutableStateOf(false) }
    if (confirmSite) AlertDialog(onDismissRequest = { confirmSite = false }, title = { Text("Установить сайт-заглушку?") }, text = { Text("Для ${values.text("domain").orEmpty()} будет создан локальный HTTPS-сайт. Настройки Reality останутся без изменений.") }, confirmButton = { TextButton(onClick = { confirmSite = false; onSubmit(values) }, enabled = !busy) { Text("Установить") } }, dismissButton = { TextButton(onClick = { confirmSite = false }) { Text("Отмена") } })
    ModalBottomSheet(onDismissRequest = { if (!busy) onDismiss() }) {
        Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp).padding(bottom = 24.dp).imePadding(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(editor.title, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
            Text(server, color = MaterialTheme.colorScheme.onSurfaceVariant)
            editor.description?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
            editor.schema.properties().filterKeys { !(it == "key" && "/enqueue/compose_" in editor.operation.path) }.forEach { (name, schema) ->
                if (name in editor.locked) InfoRow(schema.text("title") ?: name, if (name == "source") { if (values[name] == JsonPrimitive("server")) "Сервер" else "Библиотека" } else values[name]?.jsonPrimitive?.content.orEmpty())
                else NativeField(name, schema, values[name], name in editor.schema.required(), { next ->
                    if (!busy) values = JsonObject(values.toMutableMap().apply { if (next == null) remove(name) else put(name, next) })
                }, choices = editor.choices)
            }
            if (editor.xuiAction in setOf("change_password", "change_path")) PanelSecondaryButton(onClick = { values = JsonObject(values + ((if (editor.xuiAction == "change_password") "password" else "path") to JsonPrimitive(generated()))) }, enabled = !busy) { Text(if (editor.xuiAction == "change_password") "Сгенерировать пароль" else "Сгенерировать путь") }
            if (editor.operation.destructive) Text("Действие изменит состояние выбранного объекта.", color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
            error?.let { ErrorCard(it) }
            if (busy) LinearProgressIndicator(Modifier.fillMaxWidth())
            PanelButton(onClick = { if (editor.xuiAction == "fakesite_install" && NativeForm.validate(editor.schema, values) == null && xuiFormError("fakesite_install", values) == null) confirmSite = true else onSubmit(values) }, enabled = !busy, modifier = Modifier.fillMaxWidth()) { Text(when(editor.xuiAction) { "cert_issue_domain", "cert_issue_ip" -> "Выпустить"; "cert_renew" -> "Продлить"; "cert_remove" -> "Отозвать и удалить"; "fakesite_install" -> "Установить"; "fakesite_remove" -> "Удалить заглушку"; else -> if (editor.schema.properties().isEmpty() || editor.operation.destructive) "Подтвердить" else "Применить" }) }
        }
    }
}

@Composable
private fun WireguardProfileCard(profile: JsonObject, vm: ServiceDetailViewModel, operation: (String, Map<String, JsonElement>) -> Unit) {
    val name = profile.text("name").orEmpty()
    val target = mapOf("name" to JsonPrimitive(name))
    val exportable = profile["managed"] != JsonPrimitive(false)
    var menu by remember { mutableStateOf(false) }
    PanelCard {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            Text(name, style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
            Box {
                IconButton(onClick = { menu = true }) { Icon(Icons.Default.MoreVert, "Действия профиля") }
                DropdownMenu(menu, { menu = false }) {
                    DropdownMenuItem(text = { Text("Переименовать") }, onClick = { menu = false; vm.edit("POST /api/services/wireguard/{server_id}/profiles/{name}/rename", "Переименовать $name", target) })
                    DropdownMenuItem(text = { Text("Перевыпустить ключи") }, onClick = { menu = false; vm.edit("POST /api/services/wireguard/{server_id}/profiles/{name}/reissue", "Перевыпустить $name", target) })
                    DropdownMenuItem(text = { Text("Удалить", color = MaterialTheme.colorScheme.error) }, onClick = { menu = false; vm.edit("DELETE /api/services/wireguard/{server_id}/profiles/{name}", "Удалить профиль $name", target) })
                }
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            StatusBadge(if (!profile.flag("enabled")) "Выключен" else if (profile.flag("connected")) "Онлайн" else "Офлайн", if (profile.flag("connected")) StatusTone.GOOD else StatusTone.NEUTRAL)
            if (profile["managed"] == JsonPrimitive(false)) StatusBadge("Импортирован", StatusTone.WARNING)
        }
        InfoRow("Адрес", (profile["allowed_ips"] as? JsonArray)?.joinToString { it.jsonPrimitive.content } ?: "—")
        Text("↓ ${displayBytes(profile.number("rx_bytes"))}   ↑ ${displayBytes(profile.number("tx_bytes"))}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            TextButton(onClick = { operation("GET /api/services/wireguard/{server_id}/qr/{name}", target) }, enabled = exportable) { Text("QR-код") }
            TextButton(onClick = { operation("GET /api/services/wireguard/{server_id}/config/{name}", target) }, enabled = exportable) { Text("Конфиг") }
            TextButton(onClick = { vm.edit("POST /api/services/wireguard/{server_id}/profiles/{name}/toggle", if (profile.flag("enabled")) "Выключить $name" else "Включить $name", target + ("enabled" to JsonPrimitive(!profile.flag("enabled"))), setOf("enabled")) }) { Text(if (profile.flag("enabled")) "Выключить" else "Включить") }
        }
    }
}

@Composable
private fun DockerContainerCard(record: JsonObject, vm: ServiceDetailViewModel, operation: (String, Map<String, JsonElement>) -> Unit) {
    val name = record.text("name") ?: record.text("id").orEmpty()
    val running = record.text("state") == "running" || record.text("status").orEmpty().startsWith("Up")
    val target = mapOf("name" to JsonPrimitive(name))
    var menu by remember { mutableStateOf(false) }
    PanelCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(name, Modifier.weight(1f), style = MaterialTheme.typography.titleMedium)
            Box { IconButton(onClick = { menu = true }) { Icon(Icons.Default.MoreVert, "Действия контейнера") }
                DropdownMenu(menu, { menu = false }) {
                    DropdownMenuItem(text = { Text("Перезапустить") }, onClick = { menu = false; vm.action("container_restart", "Перезапустить $name", target) })
                    DropdownMenuItem(text = { Text("Удалить", color = MaterialTheme.colorScheme.error) }, onClick = { menu = false; vm.action("container_rm", "Удалить $name", target) })
                }
            }
        }
        StatusBadge(if (running) "Запущен" else "Остановлен", if (running) StatusTone.GOOD else StatusTone.NEUTRAL)
        InfoRow("Образ", record.text("image") ?: "—")
        InfoRow("Порты", record.text("ports") ?: "—")
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            PanelSecondaryButton(onClick = { vm.action(if (running) "container_stop" else "container_start", "${if (running) "Остановить" else "Запустить"} $name", target) }) { Text(if (running) "Остановить" else "Запустить") }
            TextButton(onClick = { operation("GET /api/services/docker/{server_id}/logs/{name}", target) }) { Text("Логи") }
        }
    }
}

@Composable
private fun ComposeProjectCard(project: JsonObject, accessible: Boolean, vm: ServiceDetailViewModel, operation: (String, Map<String, JsonElement>) -> Unit) {
    val name = project.text("name").orEmpty()
    val source = project.text("source") ?: "library"
    val target = buildMap<String, JsonElement> {
        put("stack", JsonPrimitive(name)); put("source", JsonPrimitive(source))
        project.text("key")?.takeIf(String::isNotBlank)?.let { put("key", JsonPrimitive(it)) }
    }
    val status = project.text("status")
    val conflict = status == "conflict"
    val context = listOfNotNull(name, project.text("working_dir")).joinToString(" · ")
    PanelCard(name) {
        StatusBadge(when (status) { "running" -> "Запущен"; "stopped" -> "Остановлен"; "conflict" -> "Конфликт имён"; else -> "В библиотеке" },
            if (conflict) StatusTone.WARNING else if (status == "running") StatusTone.GOOD else StatusTone.NEUTRAL)
        if(source == "server") TextButton(onClick={ operation("POST /api/services/docker/{server_id}/ignored-stacks",target) }) { Text("Скрыть из списка") }
        if(source == "library") TextButton(onClick={ operation("DELETE /api/services/docker/{server_id}/stacks/{name}",mapOf("name" to JsonPrimitive(name))) }) { Text("Удалить из библиотеки") }
        project.text("working_dir")?.let { InfoRow("Каталог", it) }
        if (source == "server") InfoRow("Контейнеры", "${project.text("containers_running") ?: "0"} / ${project.text("containers_total") ?: "0"}")
        if (project["lib_match"] == JsonPrimitive(false)) Text("Файлы сервера отличаются от библиотеки", color = MaterialTheme.colorScheme.tertiary)
        if (conflict) Text("На сервере несколько проектов с этим именем. Выберите конкретное развёртывание по каталогу.", style = MaterialTheme.typography.bodySmall)
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            TextButton(onClick = { vm.action(if (status == "running") "compose_restart" else "compose_up", "${if (status == "running") "Перезапустить" else "Запустить"} $context", target) }, enabled = accessible && !conflict) { Text(if (status == "running") "Перезапустить" else if (source == "library") "Установить" else "Запустить") }
            if (source == "server") TextButton(onClick = { vm.action("compose_down", "Остановить проект $context", target) }, enabled = accessible) { Text("Остановить") }
            TextButton(onClick = { operation("GET /api/services/docker/{server_id}/stacks/{name}/files", target + ("name" to JsonPrimitive(name)) + ("remote" to JsonPrimitive(source == "server"))) }, enabled = source == "library" || accessible) { Text("Файлы") }
        }
    }
}

@Composable
private fun XuiOverview(data: JsonObject, vm: ServiceDetailViewModel, operation: (String, Map<String, JsonElement>) -> Unit) {
    val clipboard = LocalClipboardManager.current
    val context = LocalContext.current
    var openPanel by remember { mutableStateOf(false) }
    val url = data.text("panel_url")?.takeIf { it.startsWith("https://") || it.startsWith("http://") }
    if (openPanel && url != null) AlertDialog(onDismissRequest = { openPanel = false }, title = { Text("Перейти в панель 3x-ui?") }, text = { Text(url) }, confirmButton = { TextButton(onClick = { openPanel = false; runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) }.onFailure { Toast.makeText(context, "Не удалось открыть браузер", Toast.LENGTH_SHORT).show() } }) { Text("Открыть в браузере") } }, dismissButton = { TextButton(onClick = { openPanel = false }) { Text("Отмена") } })
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        PanelCard("Доступ к панели") {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                if (url != null) {
                    TextButton(onClick = { openPanel = true }, modifier = Modifier.weight(1f), contentPadding = PaddingValues(0.dp)) {
                        Text(url, modifier = Modifier.weight(1f))
                        Icon(Icons.Default.OpenInNew, "Открыть панель", Modifier.padding(start = 6.dp).size(18.dp))
                    }
                    IconButton(onClick = { clipboard.setText(AnnotatedString(url)); Toast.makeText(context, "Адрес скопирован", Toast.LENGTH_SHORT).show() }) {
                        Icon(Icons.Default.ContentCopy, "Копировать адрес", Modifier.size(18.dp))
                    }
                } else InfoRow("Адрес", "—")
            }
        }
        ActionRow(if (serviceActive(data)) "Остановить панель" else "Запустить панель", "Управление сервисом x-ui", Icons.Default.PowerSettingsNew,
            { vm.action("unit_action", "Управление 3x-ui", mapOf("action" to JsonPrimitive(if (serviceActive(data)) "stop" else "start")), quick = true) })
        ActionRow("Перезапустить", "Перезапуск панели 3x-ui", Icons.Default.RestartAlt, { vm.action("unit_action", "Перезапустить 3x-ui", mapOf("action" to JsonPrimitive("restart")), quick = true) })
        ActionRow("Обновить 3x-ui", "Установить новую версию", Icons.Default.SystemUpdateAlt, { vm.action("update", "Обновление 3x-ui", locked = emptySet()) })
        ActionRow("Экспорт базы", "Сохранить резервную копию .db", Icons.Default.Download, { operation("GET /api/services/3x-ui/{server_id}/db-export", emptyMap()) })
        ActionRow("Импорт базы", "Восстановить из .db или .dump", Icons.Default.Upload, { operation("POST /api/services/3x-ui/{server_id}/db-import", emptyMap()) })
    }
}

@Composable
private fun ServiceSettings(data: JsonObject, kind: ServiceKind, vm: ServiceDetailViewModel, operation: (String, Map<String, JsonElement>) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        if (kind == ServiceKind.WIREGUARD) {
            PanelCard("Конфигурация WireGuard") {
                InfoRow("Endpoint", data.text("endpoint") ?: "—"); InfoRow("Порт", data.text("port") ?: "—"); InfoRow("Адрес VPN", data.text("address") ?: "—"); InfoRow("DNS", data.text("dns") ?: "—")
                TextButton(onClick = { vm.edit("POST /api/services/wireguard/{server_id}/config", "Настройки WireGuard", data.filterKeys { it in setOf("endpoint", "port", "address", "dns") }) }) { Text("Изменить настройки") }
            }
        }
        if (kind == ServiceKind.XUI) XuiManagement(data, vm)
        if (kind == ServiceKind.DOCKER) {
            ActionRow(if (serviceActive(data)) "Остановить Docker" else "Запустить Docker", "Управление демоном на сервере", Icons.Default.PowerSettingsNew, { vm.action(if (serviceActive(data)) "daemon_stop" else "daemon_start", "Управление Docker") })
            ActionRow("Очистить образы", "Удалить неиспользуемые образы", Icons.Default.CleaningServices, { vm.action("image_prune", "Очистка образов") })
        }
        ActionRow("Синхронизировать", "Обновить состояние с сервера", Icons.Default.Sync, { vm.edit("POST /api/services/${kind.id}/{server_id}/sync", "Синхронизация ${kind.title}") })
        ActionRow("Удалить ${kind.title}", "Удалить сервис с этого сервера", Icons.Default.DeleteOutline, { vm.action("remove", "Удалить ${kind.title}") }, danger = true)
        Text("Последняя синхронизация: ${displayTime(data.text("synced_at"))}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

fun taskStatusLabel(status: String): String = when (status) { "queued" -> "В очереди"; "running" -> "Выполняется"; "success", "completed" -> "Завершена"; "success_warn" -> "Завершена с замечаниями"; "failed" -> "Ошибка"; "cancelled" -> "Отменена"; else -> status }
