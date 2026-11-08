package com.bot4vps.mobile.ui.control

import com.bot4vps.mobile.ui.components.*
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.bot4vps.mobile.data.model.*
import com.bot4vps.mobile.ui.theme.Background
import kotlinx.serialization.json.*
import androidx.compose.foundation.Image
import androidx.compose.ui.graphics.asImageBitmap
import android.graphics.BitmapFactory
import android.util.Base64
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import com.bot4vps.mobile.ui.servers.ServerCreateForm

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun NativeSectionScreen(section: String, onBack: (() -> Unit)? = null, onOperation: (String) -> Unit, onHistory: (() -> Unit)? = null, viewModel: NativeControlViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsState()
    var search by rememberSaveable { mutableStateOf("") }
    var filters by rememberSaveable { mutableStateOf(false) }
    var confirmClear by remember { mutableStateOf(false) }
    val snack = remember { SnackbarHostState() }
    LaunchedEffect(state.notice) { state.notice?.let { snack.showSnackbar(it); viewModel.consumeNotice() } }
    if (confirmClear) AlertDialog(onDismissRequest = { confirmClear = false },
        title = { Text("Очистить журнал событий?") },
        text = { Text("Все сохранённые события и уведомления будут удалены без возможности восстановления. История задач сохраняется.") },
        confirmButton = { TextButton(onClick = { confirmClear = false; viewModel.clearEvents() }, enabled = !state.busy && !state.loading) { Text("Очистить") } },
        dismissButton = { TextButton(onClick = { confirmClear = false }) { Text("Отмена") } })
    var selectedRecord by remember { mutableStateOf<Pair<JsonObject,String>?>(null) }
    var focused by remember { mutableStateOf(false) }
    LaunchedEffect(state.result, viewModel.initialRecordId) {
        if (section == "events" && !focused) {
            val event = (state.result as? JsonObject)?.objects("events")?.find { it.text("id") == viewModel.initialRecordId }
            if (event != null) { focused = true; viewModel.openRecord(event, "events") { row, kind -> selectedRecord = row to kind } }
        }
    }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(lifecycle,viewModel) { lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) { viewModel.execute(); viewModel.observe() } }
    val title = if (section == "events") "Журнал событий" else state.contract?.sections?.get(section) ?: "Управление"
    val views = PanelWorkflows.views(section)
    val insideProject = state.fields["project"]?.jsonPrimitive?.contentOrNull?.isNotEmpty() == true
    val actions = PanelWorkflows.actions(section, state.selectedView, insideProject)
    selectedRecord?.let { selected -> NativeRecordSheet(selected, viewModel, { selectedRecord = null }, onOperation) }
    PanelScaffold(topBar = { Column {
        PanelTopBar(title = { Text(title) }, navigationIcon = { onBack?.let { IconButton(onClick = it) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Назад") } } },
            actions = { IconButton(enabled=!state.busy && !state.loading, onClick={ viewModel.execute() }) { Icon(Icons.Default.Refresh, "Обновить") } })
        if (views.size > 1) LazyRow(contentPadding=PaddingValues(horizontal=16.dp), horizontalArrangement=Arrangement.spacedBy(6.dp)) {
            items(views) { view -> PanelTab(state.selectedView == view.id, {
                if (view.operation.startsWith("GET ")) viewModel.selectView(view)
                else { viewModel.prepareNext(view.operation); onOperation(view.operation) }
            }, { Text(view.title) }, enabled=!state.busy && !state.loading) }
        }
    } }, snackbarHost = { SnackbarHost(snack) }) { padding ->
        Refreshable(state.loading || state.busy, { viewModel.execute() }, Modifier.fillMaxSize().padding(padding)) {
        LazyColumn(Modifier.fillMaxSize(), contentPadding=PaddingValues(16.dp), verticalArrangement=refreshArrangement(10.dp)) {
            if (section == "events" && onHistory != null) item { ActionRow("История задач", "Выполнение и вывод задач", Icons.Default.History, onHistory) }
            if (section == "files") item { Text(if (state.selectedView == "keys") "SSH-ключи панели. Используемый ключ удалить нельзя." else if (state.selectedView == "scripts") "Скрипты для запуска на серверах" else "Локальная библиотека Compose. Развёртывание — в разделе Docker.", style=MaterialTheme.typography.bodySmall) }
            if (insideProject) item { Row { TextButton(onClick=viewModel::parentDirectory, enabled=!state.busy) { Text("← Назад") }; Text(state.fields["project"]?.jsonPrimitive?.content.orEmpty()+" / "+state.fields["directory"]?.jsonPrimitive?.content.orEmpty()) } }
            if (section == "audit") {
                item { TextButton(onClick={ filters=!filters }) { Text(if(filters) "Скрыть фильтры" else "Фильтры") } }
                if(filters) item { SearchableChoice("Кто выполнил",state.fields["actor_type"]?.jsonPrimitive?.contentOrNull?.let { type -> type+state.fields["actor_id"]?.jsonPrimitive?.contentOrNull?.let { ":$it" }.orEmpty() },state.choices["actor"].orEmpty(),viewModel::actor,allowEmpty=true) }
                if (filters) items(state.operation?.fields.orEmpty().filter { it.text("name") !in setOf("cursor", "limit", "line_context", "step", "actor_type", "actor_id", "action_prefix") }) { f -> val name=f.text("name")!!; NativeField(name,f,state.fields[name],f.flag("required"),{ viewModel.field(name,it) },state.choices) }
                if (filters) item { PanelButton(onClick=viewModel::applyFilters,enabled=!state.busy) { Text("Применить фильтры") } }
            }
            actions.forEach { action -> item { PanelSecondaryButton(onClick={
                if (section == "events" && action.id == "DELETE /api/events") confirmClear = true
                else { viewModel.prepareNext(action.id); onOperation(action.id) }
            },enabled=!state.busy && !state.loading,modifier=Modifier.fillMaxWidth()) { Text(PanelWorkflows.title(action.id,action.title)) } } }
            item { PanelSearchField(search,{ search=it },placeholder="Поиск в списке",modifier=Modifier.fillMaxWidth()) }
            if (state.loading || state.busy) item { LinearProgressIndicator(Modifier.fillMaxWidth()) }
            state.error?.let { item { ErrorCard(it, onRetry={ viewModel.execute() }) } }
            state.result?.let { result -> item { DomainDataView(result,section,state.contract?.labels.orEmpty(),search) { record,collection ->
                if (!viewModel.openDirectory(record)) viewModel.openRecord(record, collection) { row,kind -> selectedRecord=row to kind }
            } } }
            if(state.canPrevious) item { PanelSecondaryButton(onClick=viewModel::previousPage,enabled=!state.busy) { Text("Предыдущая страница") } }
            if ((state.result as? JsonObject)?.text("next_cursor") != null) item { PanelSecondaryButton(onClick=viewModel::nextPage, enabled=!state.busy) { Text("Следующая страница") } }
        }
    }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun NativeActionScreen(onBack: () -> Unit, onLogin: () -> Unit, onOperation: (String) -> Unit = {}, viewModel: NativeControlViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsState()
    val op = state.operation
    if (op?.path in setOf("/api/masterkey/view", "/api/masterkey/view/confirm", "/api/masterkey/view/resend")) {
        com.bot4vps.mobile.ui.settings.MasterKeyViewDialog(viewModel.client, viewModel.appLock, onBack)
        return
    }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(lifecycle,viewModel) { lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) { viewModel.observe() } }
    var confirm by remember { mutableStateOf(false) }
    var restoreConfirm by remember { mutableStateOf(false) }
    var uploadName by remember { mutableStateOf("") }
    var selectedRecord by remember { mutableStateOf<Pair<JsonObject,String>?>(null) }
    val pickFile = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri -> uri?.let { viewModel.selectUpload(uploadName, it) } }
    val saveFile = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/octet-stream")) { uri -> uri?.let { viewModel.execute(it) } }
    BackHandler { onBack() }
    selectedRecord?.let { selected -> NativeRecordSheet(selected, viewModel, { selectedRecord = null }, onOperation) }
    if (confirm && op != null) AlertDialog(
        onDismissRequest = { confirm = false }, title = { Text("Подтвердить действие") },
        text = { Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(op.title)
            state.fields["server_id"]?.let { id -> Text("Сервер: " + (state.choices["server_id"]?.find { it.first == id.jsonPrimitive.content }?.second ?: id.jsonPrimitive.content)) }
            if (op.destructive) Text("Проверьте выбранный объект и параметры: это действие изменит его состояние.")
            op.body?.let { schema -> NativeDataView(NativeForm.redact(schema, state.body), state.contract?.labels.orEmpty(), showNulls = true) }
        } },
        confirmButton = { TextButton(onClick = { confirm = false; viewModel.execute() }) { Text("Подтвердить") } },
        dismissButton = { TextButton(onClick = { confirm = false }) { Text("Отмена") } }
    )
    if (restoreConfirm) AlertDialog(
        onDismissRequest = { restoreConfirm = false }, title = { Text("Применить план восстановления?") },
        text = { Text("Файлы будут восстановлены по подготовленному плану. Проверьте состав и режим восстановления в результате ниже.") },
        confirmButton = { TextButton(onClick = { restoreConfirm = false; viewModel.applyRestore() }) { Text("Восстановить") } },
        dismissButton = { TextButton(onClick = { restoreConfirm = false }) { Text("Отмена") } }
    )
    PanelScaffold(topBar = {
        PanelTopBar(title = { Text(op?.let { PanelWorkflows.title(it.id, it.title) } ?: "Загрузка") }, navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Назад") } }, actions = {
            if (op?.method == "GET") IconButton(enabled = !state.busy, onClick = { viewModel.execute() }) { Icon(Icons.Default.Refresh, "Обновить") }
        })
    }) { padding ->
        LazyColumn(Modifier.fillMaxSize().padding(padding).imePadding(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            if (state.loading || state.busy) item { LinearProgressIndicator(Modifier.fillMaxWidth()) }
            state.error?.let { error -> item {
                ElevatedCard { Column(Modifier.padding(12.dp)) {
                    Text(error, color = MaterialTheme.colorScheme.error)
                    if(state.prefillFailed) TextButton(onClick=viewModel::retryPrefill) { Text("Прочитать текущие значения") }
                    if (error.contains("Сессия") || error.contains("авторизац")) TextButton(onClick = onLogin) { Text("Войти заново") }
                } }
            } }
            if (op != null && state.restoreOperationId == null && state.connection == null) {
                viewModel.serverId?.let { id -> item { Text("Сервер: " + (state.choices["server_id"]?.find { it.first == id }?.second ?: id), style = MaterialTheme.typography.titleMedium) } }
                items(op.fields.filter { (it.text("name") != "server_id" || viewModel.serverId == null) && it.text("name") !in state.lockedFields }, key = { it.text("name").orEmpty() }) { field ->
                    val name = field.text("name")!!
                    if (field.text("type") == "file") {
                        PanelSecondaryButton(onClick = { uploadName = name; pickFile.launch(arrayOf("*/*")) }, enabled = !state.busy, modifier = Modifier.fillMaxWidth()) {
                            Text("${field.text("title")}: ${state.uploads[name]?.filename ?: "Выбрать файл"}")
                        }
                    } else NativeField(name, field, state.fields[name], field.flag("required"), { viewModel.field(name, it) }, state.choices)
                }
                if (op.id == "POST /api/servers") item {
                    ServerCreateForm(state.body as? JsonObject ?: JsonObject(emptyMap()), state.choices,
                        !state.busy && !state.loading, viewModel::newServerField)
                } else viewModel.formSchema()?.let { schema -> item { NativeField("body", JsonObject(schema + ("title" to JsonPrimitive("Параметры"))), state.body, true, viewModel::body, state.choices) } }
                if(op.id == "POST /api/servers") item { PanelSecondaryButton(onClick=viewModel::testNewServer,enabled=!state.busy && !state.loading,modifier=Modifier.fillMaxWidth()) { Text("Проверить подключение") } }
                if(op.method != "GET" || op.download) item {
                    PanelButton(enabled = !state.busy && !state.loading && !state.prefillFailed && state.preparedRestoreId == null, modifier = Modifier.fillMaxWidth(), onClick = {
                        if (!state.loading && viewModel.validate()) {
                            when {
                                op.download -> {
                                    val name = (state.fields["name"] as? JsonPrimitive)?.contentOrNull
                                    saveFile.launch(when {
                                        op.path.contains("/qr/") -> "${name ?: "wireguard"}.png"
                                        op.path.contains("/config/") -> "${name ?: "wireguard"}.conf"
                                        op.path.startsWith("/api/backups/") -> "bot4vps-backup.tar.gz"
                                        op.path.endsWith("/export-zip") -> {
                                            val names = (state.body as? JsonObject)?.get("names") as? JsonArray
                                            if (names?.size == 1) "${names.first().jsonPrimitive.content}.conf" else "wireguard-profiles.zip"
                                        }
                                        op.path.contains("zip") || op.path == "/api/scripts/download" -> "bot4vps.zip"
                                        op.path.contains("db-export") -> "x-ui.db"
                                        name != null -> name
                                        else -> "bot4vps-export.bin"
                                    })
                                }
                                op.method == "GET" -> viewModel.execute()
                                PanelWorkflows.confirm(op) -> confirm = true
                                else -> viewModel.execute()
                            }
                        }
                    }) { Text(if(state.restoreOperationId != null && state.preparedRestoreId == null) "Проверить подготовку" else PanelWorkflows.button(op)) }
                }
            }
            state.connection?.let { pending -> item { PanelCard("Подключение к панели") {
                Text(pending.target)
                Text("Выход с экрана не отменяет запущенную операцию",style=MaterialTheme.typography.bodySmall)
                PanelSecondaryButton(onClick=viewModel::checkConnection) { Text("Проверить состояние") }
                if(state.targetReady) PanelButton(onClick={ viewModel.connectTarget(onLogin) }) { Text("Подключиться и войти") }
            } } }
            state.notice?.let { item { Text(it, color = MaterialTheme.colorScheme.primary) } }
            if (op?.path == "/api/files" && (state.fields["project"] as? JsonPrimitive)?.contentOrNull?.isNotEmpty() == true) item {
                TextButton(onClick = viewModel::parentDirectory, enabled = !state.busy && !state.loading) { Text("На уровень выше") }
            }
            if (state.preparedRestoreId != null) item { PanelButton(onClick = { restoreConfirm = true }, enabled = !state.busy, modifier = Modifier.fillMaxWidth()) { Text("Применить подготовленный план") } }
            if (state.restoreOperationId != null && state.preparedRestoreId == null && !state.busy) item { PanelSecondaryButton(onClick={ viewModel.execute() }) { Text("Проверить подготовку") } }
            state.result?.let { result -> item {
                Text(if(op?.method == "GET") "" else "Результат", style = MaterialTheme.typography.titleMedium)
                if(op?.method == "GET" && (op.path.endsWith("/ignored-stacks") || op.path.endsWith("/files"))) DomainDataView(result, if(op.path.endsWith("/ignored-stacks")) "files" else "project", state.contract?.labels.orEmpty(), "") { record,collection -> selectedRecord=record to collection }
                else NativeDataView(result, state.contract?.labels.orEmpty(), onRecord = { record, collection ->
                    if (!viewModel.openDirectory(record) && viewModel.recordActions(record,collection).isNotEmpty()) selectedRecord = record to collection
                })
            } }
            if (state.result != null) {
                items(viewModel.related(), key = { it.id }) { next ->
                    PanelSecondaryButton(onClick = { viewModel.prepareNext(next.id); onOperation(next.id) }, modifier = Modifier.fillMaxWidth()) { Text(next.title) }
                }
                if (op?.path == "/api/auth/recover/confirm") item { PanelButton(onClick = onLogin) { Text("Войти в приложение") } }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun NativeRecordSheet(selected: Pair<JsonObject, String>, viewModel: NativeControlViewModel, onDismiss: () -> Unit, onOperation: (String) -> Unit) {
    val state by viewModel.state.collectAsState()
    val (record, collection) = selected
    if (collection == "events") {
        AlertDialog(onDismissRequest = onDismiss, title = { Text("Событие") },
            text = { Column(Modifier.fillMaxWidth().heightIn(max = 440.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text(record.text("title") ?: "Событие", style = MaterialTheme.typography.titleMedium)
                Text(displayTime(record.text("timestamp")), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                SelectionContainer { Text(record.text("message").orEmpty()) }
                record["details"]?.let { NativeDataView(it, state.contract?.labels.orEmpty()) }
            } }, confirmButton = { TextButton(onClick = onDismiss) { Text("Закрыть") } })
        return
    }
    ModalBottomSheet(onDismissRequest = onDismiss) {
        LazyColumn(contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            item { Text(record.text("display_name") ?: record.text("name") ?: record.text("filename") ?: record.text("title") ?: "Выбранная запись", style = MaterialTheme.typography.titleMedium) }
            item { NativeDataView(record, state.contract?.labels.orEmpty()) }
            items(viewModel.recordActions(record, collection), key = { it.id }) { action ->
                PanelSecondaryButton(onClick = { viewModel.recordNext(action.id, record, collection); onDismiss(); onOperation(action.id) }, modifier = Modifier.fillMaxWidth()) { Text(PanelWorkflows.title(action.id,action.title)) }
            }
        }
    }
}

@Composable
fun NativeDataView(value: JsonElement?, labels: Map<String, String>, depth: Int = 0, collection: String = "", onRecord: ((JsonObject,String) -> Unit)? = null, showNulls: Boolean = false) {
    if (value == null || value == JsonNull) return
    when (value) {
        is JsonObject -> {
            PanelSurfaceCard(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
                Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    if (onRecord != null && (value.text("id") != null || value.text("name") != null || value.text("filename") != null || value.text("entry_key") != null || value.text("backup_id") != null)) TextButton(onClick = { onRecord(value,collection) }) { Text("Действия") }
                    value.forEach { (key, child) ->
                        if (child == JsonNull && !showNulls || key in setOf("schema_version", "security_revision")) return@forEach
                        if (child is JsonPrimitive) {
                            if (child.content.startsWith("data:image/png;base64,")) {
                                val bitmap = remember(child.content) { runCatching { val bytes = Base64.decode(child.content.substringAfter(','), Base64.DEFAULT); BitmapFactory.decodeByteArray(bytes,0,bytes.size) }.getOrNull() }
                                bitmap?.let { Image(it.asImageBitmap(), "QR-код", modifier = Modifier.fillMaxWidth().height(240.dp)) }
                                return@forEach
                            }
                            val text = if (child == JsonNull) "Очистить" else if (child.isString) child.content else when (child.booleanOrNull) { true -> "Да"; false -> "Нет"; else -> child.content }
                            SelectionContainer { Text("${labels[key] ?: key.replace('_', ' ')}: $text", style = MaterialTheme.typography.bodyMedium, fontFamily = if (key in setOf("content", "output", "stdout", "stderr")) FontFamily.Monospace else null) }
                        } else {
                            Text(labels[key] ?: key.replace('_', ' '), style = MaterialTheme.typography.labelLarge)
                            NativeDataView(child, labels, depth + 1, key, onRecord, showNulls)
                        }
                    }
                }
            }
        }
        is JsonArray -> {
            if (value.isEmpty()) Text("Нет записей", color = MaterialTheme.colorScheme.onSurfaceVariant)
            value.forEach { NativeDataView(it, labels, depth + 1, collection, onRecord, showNulls) }
        }
        is JsonPrimitive -> SelectionContainer { Text(value.content, fontFamily = FontFamily.Monospace) }
    }
}
