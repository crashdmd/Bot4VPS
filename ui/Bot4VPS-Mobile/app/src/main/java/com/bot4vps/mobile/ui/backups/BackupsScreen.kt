package com.bot4vps.mobile.ui.backups

import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.*
import androidx.lifecycle.repeatOnLifecycle
import com.bot4vps.mobile.data.model.*
import com.bot4vps.mobile.ui.components.*
import com.bot4vps.mobile.ui.settings.*
import kotlinx.serialization.json.*

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun BackupsScreen(onBack: () -> Unit, onOperation: (String) -> Unit, viewModel: BackupsViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val lifecycle=LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(lifecycle,viewModel) { lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) { viewModel.observe() } }
    val snack=remember { SnackbarHostState() }
    LaunchedEffect(state.notice) { state.notice?.let { snack.showSnackbar(it) } }
    var create by remember { mutableStateOf(false) }
    var confirmApply by remember { mutableStateOf(false) }
    var confirmDelete by remember { mutableStateOf(false) }
    var cancel by remember { mutableStateOf<JsonObject?>(null) }
    var rename by remember { mutableStateOf(false) }
    val import=rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri -> uri?.let(viewModel::import) }
    val download=rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/octet-stream")) { uri -> uri?.let(viewModel::download) }
    fun back() { when(state.page) {
        "archive", "restore", "plan" -> viewModel.closeArchive()
        "settings" -> viewModel.page("archives")
        else -> onBack()
    } }
    BackHandler(enabled=!state.busy) { back() }
    if(create) CreateBackupDialog(state,{ create=false }) { label,encrypted,password -> create=false; viewModel.create(label,encrypted,password) }
    if(confirmApply) AlertDialog(onDismissRequest={ confirmApply=false }, title={ Text("Применить план восстановления?") },
        text={ Column(verticalArrangement=Arrangement.spacedBy(10.dp)) {
            Text("${state.archive?.name}\nЦель: ${state.target}")
            Text(if(state.restore.mode=="clean") "Файлы будут заменены; лишние файлы в пределах плана будут удалены." else "Файлы из архива будут добавлены или заменены. Остальные файлы сохранятся.")
            Text(if(state.restore.protective) "Перед изменениями будет создана защитная копия." else "Защитная копия отключена. Текущее состояние не будет сохранено.",color=if(state.restore.protective) MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.error)
            if(state.serverId==null) Text("Bot4VPS может перезапуститься. После восстановления может потребоваться повторный вход.")
        } },confirmButton={ TextButton(onClick={ confirmApply=false; viewModel.apply() },enabled=!state.busy && state.operation?.let(::backupPrepared)==true) { Text("Восстановить") } },
        dismissButton={ TextButton(onClick={ confirmApply=false }) { Text("Отмена") } })
    if(confirmDelete) AlertDialog(onDismissRequest={ confirmDelete=false },title={ Text("Удалить архив?") },text={ Text("${state.archive?.name}\nАрхив будет удалён из хранилища резервных копий.") },
        confirmButton={ TextButton(onClick={ confirmDelete=false; viewModel.delete() }) { Text("Удалить") } },dismissButton={ TextButton(onClick={ confirmDelete=false }) { Text("Отмена") } })
    cancel?.let { operation -> AlertDialog(onDismissRequest={ cancel=null },title={ Text("Отменить операцию?") },text={ Text("Отмена не откатывает изменения, которые операция уже успела внести. Панель остановит её на безопасном шаге.") },
        confirmButton={ TextButton(onClick={ cancel=null; viewModel.cancel(operation) }) { Text("Отменить операцию") } },dismissButton={ TextButton(onClick={ cancel=null }) { Text("Продолжить выполнение") } }) }
    if(rename) {
        var name by remember(state.archive?.key) { mutableStateOf(state.archive?.name.orEmpty()) }
        AlertDialog(onDismissRequest={ rename=false },title={ Text("Имя архива") },text={ PanelTextField(name,{ name=it },singleLine=true,modifier=Modifier.fillMaxWidth()) },
            confirmButton={ TextButton(onClick={ rename=false; viewModel.rename(name) },enabled=name.isNotBlank() && name.length<=255 && '/' !in name && '\\' !in name) { Text("Сохранить") } },dismissButton={ TextButton(onClick={ rename=false }) { Text("Отмена") } })
    }
    PanelScaffold(topBar={ PanelTopBar(title={ Text(when(state.page) { "settings" -> "Настройки копирования"; "restore" -> "Восстановление"; "plan" -> "План восстановления"; "archive" -> "Архив"; else -> "Резервные копии" }) },
        navigationIcon={ IconButton(onClick=::back,enabled=!state.busy) { Icon(Icons.AutoMirrored.Filled.ArrowBack,"Назад") } },
        actions={ IconButton(onClick=viewModel::refresh,enabled=!state.busy && !state.loading) { Icon(Icons.Default.Refresh,"Обновить") } }) },snackbarHost={ SnackbarHost(snack) }) { padding ->
        Refreshable(state.loading || state.busy,viewModel::refresh,Modifier.fillMaxSize().padding(padding)) {
        LazyColumn(Modifier.fillMaxSize().imePadding(),contentPadding=PaddingValues(16.dp),verticalArrangement=refreshArrangement(12.dp)) {
            if(state.loading || state.busy) item { LinearProgressIndicator(Modifier.fillMaxWidth()) }
            state.error?.let { item { ErrorCard(it,if(state.busy) null else viewModel::refresh) } }
            if(state.page in setOf("archives","operations","settings")) {
                item { SearchableChoice("Что копируем",state.serverId,state.servers,viewModel::select,allowEmpty=true,emptyLabel="Панель Bot4VPS",enabled=!state.busy && !state.loading) }
            } else item { Text(state.target,style=MaterialTheme.typography.titleSmall,color=MaterialTheme.colorScheme.primary) }
            when(state.page) {
                "archives", "operations" -> {
                    item { Row(horizontalArrangement=Arrangement.spacedBy(8.dp)) {
                        PanelTab(state.page=="archives",{ viewModel.page("archives") },{ Text("Архивы · ${state.archives.size}") },enabled=!state.busy)
                        PanelTab(state.page=="operations",{ viewModel.page("operations") },{ Text("Операции") },enabled=!state.busy)
                        IconButton(onClick={ viewModel.page("settings") },enabled=state.data!=null && !state.busy) { Icon(Icons.Default.Tune,"Настройки копирования") }
                    } }
                    if(state.page=="archives") {
                        item { SettingsCard("Резервное копирование", if(state.serverId==null) "Конфигурация, серверы, ключи и данные Bot4VPS. Архив хранится на хосте панели." else "Архив выбранных файлов и папок сервера хранится на хосте панели.") {
                            if(!state.configured) Text("Сначала выберите файлы и папки в настройках копирования.",color=MaterialTheme.colorScheme.onSurfaceVariant)
                            PanelButton(onClick={ create=true },enabled=state.data!=null && state.configured && !state.busy,modifier=Modifier.fillMaxWidth()) { Icon(Icons.Default.Add,null); Text("Создать копию") }
                            Row(horizontalArrangement=Arrangement.spacedBy(8.dp)) {
                                PanelSecondaryButton(onClick={ import.launch(arrayOf("*/*")) },enabled=state.data!=null && !state.busy,modifier=Modifier.weight(1f)) { Text("Импорт архива") }
                                PanelSecondaryButton(onClick={ viewModel.page("settings") },enabled=state.data!=null && !state.busy,modifier=Modifier.weight(1f)) { Text("Настроить") }
                            }
                            Text("Импорт добавляет архив в хранилище. Восстановление запускается отдельно после проверки плана.",style=MaterialTheme.typography.bodySmall,color=MaterialTheme.colorScheme.onSurfaceVariant)
                        } }
                        if(state.data!=null && state.archives.isEmpty()) item { PanelCard { Text("Копий для этой цели пока нет"); Text("Создайте новую копию или импортируйте архив с телефона.",style=MaterialTheme.typography.bodySmall) } }
                        items(state.archives,key={ it.key }) { a -> PanelSurfaceCard(onClick={ if(!state.busy) viewModel.open(a) },modifier=Modifier.fillMaxWidth()) {
                            Column(Modifier.padding(16.dp),verticalArrangement=Arrangement.spacedBy(6.dp)) {
                                Row(verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(10.dp)) { Icon(Icons.Default.Archive,null,tint=MaterialTheme.colorScheme.primary); Text(a.name,Modifier.weight(1f),style=MaterialTheme.typography.titleSmall); Icon(Icons.Default.ChevronRight,"Открыть архив") }
                                Text(a.row.text("display_created_at") ?: a.row.text("display_imported_at") ?: a.row.text("created_at") ?: a.row.text("imported_at") ?: "Дата неизвестна",style=MaterialTheme.typography.bodySmall,color=MaterialTheme.colorScheme.onSurfaceVariant)
                                Text(listOfNotNull(if(a.imported) "Импортирован" else "Резервная копия",a.row.text("format"),a.row.number("bytes")?.let(::backupSize)).joinToString(" · "),style=MaterialTheme.typography.labelMedium)
                            }
                        } }
                    } else {
                        item { Text("Создание, проверка и восстановление архивов. Операции продолжаются на панели после выхода с экрана.",style=MaterialTheme.typography.bodySmall,color=MaterialTheme.colorScheme.onSurfaceVariant) }
                        if(state.operations.isEmpty() && state.data!=null) item { Text("Операций пока нет") }
                        items(state.operations,key={ backupOperationId(it).orEmpty() }) { operation -> BackupOperationCard(operation,onCancel={ cancel=operation }) }
                    }
                }
                "settings" -> {
                    item { BackupSettingsEditor(state,viewModel) }
                    item { BackupPasswordCard(onOperation=onOperation,onChanged=viewModel::refresh) }
                }
                "archive" -> {
                    state.archive?.let { a ->
                        item { SettingsCard(a.name,if(a.imported) "Импортированный архив для выбранной цели" else "Сохранённая резервная копия") {
                            InfoRow("Размер",(state.preview?.number("bytes") ?: a.row.number("bytes"))?.let(::backupSize) ?: "—")
                            InfoRow("Формат",state.preview?.text("format") ?: a.row.text("format") ?: "—")
                            PanelButton(onClick=viewModel::restore,enabled=state.preview!=null && !state.busy,modifier=Modifier.fillMaxWidth()) { Text("Восстановить из архива") }
                            PanelSecondaryButton(onClick={ download.launch(a.name) },enabled=!state.busy,modifier=Modifier.fillMaxWidth()) { Text("Сохранить на телефон") }
                        } }
                        item { SettingsCategoryCard("Управление архивом","Переименование и удаление из хранилища") {
                            PanelSecondaryButton(onClick={ rename=true },enabled=!state.busy,modifier=Modifier.fillMaxWidth()) { Text("Переименовать") }
                            TextButton(onClick={ confirmDelete=true },enabled=!state.busy) { Text("Удалить архив",color=MaterialTheme.colorScheme.error) }
                        } }
                    }
                }
                "restore" -> restoreItems(state,viewModel)
                "plan" -> {
                    item { Text(state.archive?.name.orEmpty(),style=MaterialTheme.typography.titleSmall) }
                    state.operation?.let { op ->
                        item { BackupOperationCard(op,onCancel={ cancel=op }) }
                        if(backupPrepared(op)) {
                            item { BackupPlan(op) }
                            item { PanelButton(onClick={ confirmApply=true },enabled=!state.busy,modifier=Modifier.fillMaxWidth()) { Text("Применить подготовленный план") } }
                        } else if(!backupOperationActive(op)) item { Text("Подготовка не завершена. Исправьте причину и подготовьте план заново.") }
                        if(!backupOperationActive(op)) item { PanelSecondaryButton(onClick={ viewModel.page("restore") },enabled=!state.busy,modifier=Modifier.fillMaxWidth()) { Text("Изменить параметры") } }
                    }
                }
            }
        }
        }
    }
}

private fun LazyListScope.restoreItems(state: BackupsState, vm: BackupsViewModel) {
    val options=state.restore; val editable=!state.busy && state.readinessLoaded
    item { SettingsCard("Состав восстановления",state.archive?.name.orEmpty()) {
        Text("Сначала подготовьте план. Файлы изменятся только после отдельного подтверждения.",style=MaterialTheme.typography.bodySmall,color=MaterialTheme.colorScheme.onSurfaceVariant)
        if(state.requiresRoot && !state.needsInspection) PanelTextField(options.root,{ vm.options(options.copy(root=it)) },label={ Text("Каталог восстановления") },supportingText={ Text("Абсолютный путь на выбранной цели. Корень / недоступен.") },enabled=editable,singleLine=true,modifier=Modifier.fillMaxWidth())
        PanelTextField(options.password,{ vm.options(options.copy(password=it)) },label={ Text("Пароль архива") },supportingText={ Text("Оставьте пустым, чтобы использовать сохранённый пароль. Нужен только для зашифрованного архива.") },visualTransformation=PasswordVisualTransformation(),singleLine=true,enabled=editable,modifier=Modifier.fillMaxWidth())
        if(state.needsInspection) {
            Text("Архив зашифрован. Прочитаем его состав, чтобы определить каталог назначения.",style=MaterialTheme.typography.bodySmall)
            PanelSecondaryButton(onClick=vm::inspect,enabled=editable,modifier=Modifier.fillMaxWidth()) { Text("Проверить архив") }
        }
        ToggleSetting("Выбрать файлы и папки","Восстановить только отмеченные элементы вместо полного состава",options.partial,editable,{ vm.options(options.copy(partial=it)) })
        if(state.fullUnavailable) Text(state.policy ?: "Полное восстановление недоступно. Выберите разрешённые элементы.",color=MaterialTheme.colorScheme.error)
        if(options.partial) {
            Text("Выбрано: ${options.selected.size}",style=MaterialTheme.typography.labelMedium)
            if(!state.inventoryReady) PanelSecondaryButton(onClick=vm::inventory,enabled=editable && !state.needsInspection,modifier=Modifier.fillMaxWidth()) { Text("Прочитать состав архива") }
        }
    } }
    if(options.partial && state.inventoryReady) {
        item { Text(state.parents.lastOrNull() ?: "Состав архива",style=MaterialTheme.typography.titleSmall) }
        if(state.parents.isNotEmpty()) item { TextButton(onClick={ vm.directory(null) },enabled=editable) { Text("← На уровень выше") } }
        items(state.nodes,key={ it.text("path").orEmpty() }) { node ->
            val path=node.text("path").orEmpty()
            PanelSurfaceCard(Modifier.fillMaxWidth()) { Row(Modifier.padding(10.dp),verticalAlignment=Alignment.CenterVertically) {
                Checkbox(path in options.selected,{ selected -> vm.options(options.copy(selected=if(selected) options.selected+path else options.selected-path)) },enabled=editable && node.flag("selectable") && (path in options.selected || options.selected.size<512))
                Column(Modifier.weight(1f)) { Text(node.text("name") ?: path,style=MaterialTheme.typography.bodyMedium); if(node.flag("blocked")) Text("Исключён политикой архива",style=MaterialTheme.typography.bodySmall,color=MaterialTheme.colorScheme.onSurfaceVariant) }
                if(node.flag("has_children")) IconButton(onClick={ vm.directory(path) },enabled=editable) { Icon(Icons.Default.FolderOpen,"Открыть папку") }
            } }
        }
        if(state.cursor!=null) item { PanelSecondaryButton(onClick=vm::moreNodes,enabled=editable,modifier=Modifier.fillMaxWidth()) { Text("Показать ещё") } }
        if(state.nodes.isEmpty()) item { Text("В этой папке нет элементов") }
    }
    item { SettingsCard("Режим восстановления","Выбранная цель: ${state.target}") {
        Row(horizontalArrangement=Arrangement.spacedBy(8.dp)) {
            PanelTab(options.mode=="merge",{ vm.options(options.copy(mode="merge")) },{ Text("Объединить") },enabled=editable)
            PanelTab(options.mode=="clean",{ vm.options(options.copy(mode="clean")) },{ Text("Очистить лишнее") },enabled=editable)
        }
        Text(if(options.mode=="merge") "Добавляет файлы из архива и заменяет совпадающие. Остальные файлы сохраняет." else "В пределах состава восстановления заменяет файлы и удаляет те, которых нет в архиве. Список удалений появится в плане.",style=MaterialTheme.typography.bodySmall,color=MaterialTheme.colorScheme.onSurfaceVariant)
        ToggleSetting("Защитная копия","Сохранить текущее состояние перед изменениями",options.protective,editable,{ vm.options(options.copy(protective=it)) })
        PanelButton(onClick=vm::prepare,enabled=editable && !state.needsInspection && (!state.fullUnavailable || options.partial) && (!options.partial || options.selected.isNotEmpty()),modifier=Modifier.fillMaxWidth()) { Text("Подготовить план") }
    } }
}

@Composable
private fun BackupSettingsEditor(state: BackupsState, vm: BackupsViewModel) {
    val original=state.settings
    val server=state.serverId!=null
    var paths by remember(original,state.serverId) { mutableStateOf(original?.objects("sources")?.joinToString("\n") { it.text("path").orEmpty() }.orEmpty()) }
    val automatic=original?.get("automatic") as? JsonObject
    var enabled by remember(original,state.serverId) { mutableStateOf(automatic?.flag("enabled")==true) }
    var time by remember(original,state.serverId) { mutableStateOf(automatic?.text("daily_time") ?: "03:00") }
    var keep by remember(original,state.serverId) { mutableStateOf(automatic?.text("keep_last") ?: "7") }
    var encrypt by remember(original,state.serverId) { mutableStateOf(original?.flag("encrypt")==true) }
    var currentPassword by remember { mutableStateOf("") }
    var notifications by remember(original,state.serverId) { mutableStateOf(original?.get("notifications") as? JsonObject ?: buildJsonObject {
        put("backup",buildJsonObject { put("enabled",false); put("success",false); put("error",true) })
        put("restore",buildJsonObject { put("enabled",true); put("success",false); put("error",true) })
    }) }
    var validation by remember { mutableStateOf<String?>(null) }
    val editable=state.data!=null && !state.loading && !state.busy
    SettingsCard("Копирование ${state.target}","Расписание и защита архивов относятся только к этой цели.") {
        if(server) {
            PanelTextField(paths,{ paths=it },label={ Text("Файлы и папки") },supportingText={ Text("По одному абсолютному пути на строке, например /etc и /home. Существующие исключения сохраняются.") },minLines=3,maxLines=6,enabled=editable,modifier=Modifier.fillMaxWidth())
        } else Text("Состав копии панели определяется Bot4VPS: конфигурация, данные и ключи доступа.",style=MaterialTheme.typography.bodySmall,color=MaterialTheme.colorScheme.onSurfaceVariant)
        HorizontalDivider()
        ToggleSetting("Ежедневная копия","Автоматическое создание по времени панели",enabled,editable,{ enabled=it })
        if(enabled) Row(horizontalArrangement=Arrangement.spacedBy(12.dp)) {
            PanelTextField(time,{ time=it },label={ Text("Время, ЧЧ:ММ") },singleLine=true,enabled=editable,modifier=Modifier.weight(1f))
            PanelTextField(keep,{ keep=it },label={ Text("Хранить копий") },singleLine=true,keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Number),enabled=editable,modifier=Modifier.weight(1f))
        }
        Text("Лимит действует на автоматические копии. Старые копии сверх лимита удаляются; ручные архивы сохраняются.",style=MaterialTheme.typography.bodySmall,color=MaterialTheme.colorScheme.onSurfaceVariant)
        HorizontalDivider()
        ToggleSetting("Шифровать архивы","Использовать сохранённый пароль для ручных и автоматических копий этой цели",encrypt,editable,{ encrypt=it })
        if(encrypt && state.passwordStatus?.flag("configured")!=true) Text("Задайте пароль в блоке ниже перед сохранением.",color=MaterialTheme.colorScheme.error)
        if(original?.flag("encrypt")==true && !encrypt && state.passwordStatus?.flag("configured")==true) PanelTextField(currentPassword,{ currentPassword=it },label={ Text("Текущий пароль архивов") },supportingText={ Text("Подтвердите отключение защиты для этой цели") },singleLine=true,visualTransformation=PasswordVisualTransformation(),modifier=Modifier.fillMaxWidth())
        SettingsCategoryCard("Оповещения","Какие результаты копирования и восстановления записывать как уведомления") {
            listOf("backup" to "Резервное копирование","restore" to "Восстановление").forEach { (kind,title) ->
                val category=notifications[kind] as? JsonObject ?: JsonObject(emptyMap())
                fun change(key: String, value: Boolean) { notifications=JsonObject(notifications+(kind to JsonObject(category+(key to JsonPrimitive(value))))) }
                ToggleSetting(title,"Создавать оповещения о результатах для этой цели",category.flag("enabled"),editable,{ change("enabled",it) })
                if(category.flag("enabled")) {
                    ToggleSetting("Успешное завершение","Сообщать, когда операция завершилась успешно",category.flag("success"),editable,{ change("success",it) })
                    ToggleSetting("Ошибки","Сообщать о неудачном завершении",category.flag("error"),editable,{ change("error",it) })
                }
                if(kind=="backup") HorizontalDivider()
            }
            Text("Доставка в Telegram и на телефон дополнительно зависит от настроек уведомлений соответствующего канала.",style=MaterialTheme.typography.bodySmall,color=MaterialTheme.colorScheme.onSurfaceVariant)
        }
        validation?.let { Text(it,color=MaterialTheme.colorScheme.error) }
        PanelButton(onClick={
            runCatching { backupSettingsDraft(JsonObject(original.orEmpty()+("notifications" to notifications)),server,paths.lines(),enabled,time,keep.toIntOrNull() ?: 0,encrypt) }
                .onSuccess { validation=null; vm.saveSettings(it,currentPassword); currentPassword="" }
                .onFailure { validation=it.message }
        },enabled=editable,modifier=Modifier.fillMaxWidth()) { Text("Сохранить настройки") }
    }
}

@Composable
private fun CreateBackupDialog(state: BackupsState, onDismiss: () -> Unit, onCreate: (String,Boolean,String) -> Unit) {
    var label by remember { mutableStateOf("") }
    var encrypt by remember { mutableStateOf(state.settings?.flag("encrypt")==true) }
    var password by remember { mutableStateOf("") }
    val stored=state.passwordStatus?.flag("configured")==true && state.passwordStatus.flag("masterkey_available")
    AlertDialog(onDismissRequest=onDismiss,title={ Text("Создать резервную копию") },text={ Column(Modifier.verticalScroll(rememberScrollState()),verticalArrangement=Arrangement.spacedBy(12.dp)) {
        Text("Цель: ${state.target}",style=MaterialTheme.typography.titleSmall)
        PanelTextField(label,{ label=it },label={ Text("Описание, необязательно") },singleLine=true,modifier=Modifier.fillMaxWidth())
        ToggleSetting("Зашифровать архив","Защитить содержимое паролем",encrypt,true,{ encrypt=it })
        if(encrypt) PanelTextField(password,{ password=it },label={ Text("Пароль архива") },supportingText={ Text(if(stored) "Пустое поле — использовать сохранённый пароль. Введённый пароль действует только для этой копии." else "Задайте пароль для этой копии; он не сохраняется в настройках.") },visualTransformation=PasswordVisualTransformation(),singleLine=true,modifier=Modifier.fillMaxWidth())
        else Text("Архив содержит данные выбранной цели без шифрования.",style=MaterialTheme.typography.bodySmall,color=MaterialTheme.colorScheme.onSurfaceVariant)
    } },confirmButton={ TextButton(onClick={ onCreate(label,encrypt,password) },enabled=label.length<=200 && (!encrypt || password.length<=256 && (stored || password.isNotEmpty()))) { Text("Создать") } },dismissButton={ TextButton(onClick=onDismiss) { Text("Отмена") } })
}

@Composable
private fun BackupOperationCard(op: JsonObject, onCancel: () -> Unit) {
    val title=when(op.text("type")) { "create" -> "Создание копии"; "restore" -> if(op.text("stage")=="prepared") "План подготовлен" else "Восстановление"; "verify" -> "Проверка архива"; "import" -> "Импорт архива"; "migrate" -> "Перенос хранилища"; "retention" -> "Удаление старых копий"; else -> "Операция" }
    PanelCard(title) {
        Text(auditResultLabel(op.text("status").orEmpty()),color=if(op.text("status")=="failed") MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary)
        op.text("started_at")?.let { Text(it,style=MaterialTheme.typography.bodySmall,color=MaterialTheme.colorScheme.onSurfaceVariant) }
        val progress=op["progress"] as? JsonObject
        if(backupOperationActive(op)) {
            progress?.number("percent")?.let { LinearProgressIndicator(progress={ (it/100).toFloat().coerceIn(0f,1f) },modifier=Modifier.fillMaxWidth()) } ?: LinearProgressIndicator(Modifier.fillMaxWidth())
            val files=progress?.text("processed_files") ?: "0"
            Text("Файлов: $files · ${progress?.number("processed_bytes")?.let(::backupSize) ?: "—"}",style=MaterialTheme.typography.bodySmall)
            if((op["cancellation"] as? JsonObject)?.flag("requested")==true) Text("Ожидается безопасная остановка",style=MaterialTheme.typography.bodySmall)
            else if((op["cancellation"] as? JsonObject)?.flag("allowed")==true) TextButton(onClick=onCancel) { Text("Отменить операцию") }
        }
        backupError(op)?.let { Text(it,color=MaterialTheme.colorScheme.error) }
        if(op.text("type")=="restore" && !backupOperationActive(op) && op.text("status")!="completed" && (op["restore"] as? JsonObject)?.flag("mutation_started")==true) Text("Восстановление завершилось не полностью: данные уже изменялись. Проверьте цель; при необходимости используйте защитную копию.",color=MaterialTheme.colorScheme.error,style=MaterialTheme.typography.bodySmall)
        op.objects("warnings").forEach { Text(it.text("message") ?: "Операция завершилась с предупреждением",style=MaterialTheme.typography.bodySmall,color=MaterialTheme.colorScheme.onSurfaceVariant) }
        (op["restore"] as? JsonObject)?.text("protective_backup_id")?.let { Text("Защитная копия: $it",style=MaterialTheme.typography.bodySmall) }
    }
}

@Composable
private fun BackupPlan(op: JsonObject) {
    val restore=op["restore"] as? JsonObject
    val plan=restore?.get("plan") as? JsonObject ?: return
    val counts=plan["counts"] as? JsonObject
    SettingsCard("Изменения по плану",if(plan.text("mode")=="clean") "Лишние файлы внутри состава будут удалены" else "Остальные файлы сохраняются") {
        listOf("add" to "Будут добавлены","replace" to "Будут заменены","delete" to "Будут удалены").forEach { (key,title) ->
            if(plan[key] != null && plan[key] != JsonNull) {
                val paths=(plan[key] as? JsonArray).orEmpty().mapNotNull { (it as? JsonPrimitive)?.contentOrNull }
                Text("$title: ${counts?.text(key) ?: paths.size}",style=MaterialTheme.typography.titleSmall)
                Column(Modifier.fillMaxWidth().heightIn(max=180.dp).verticalScroll(rememberScrollState()),verticalArrangement=Arrangement.spacedBy(4.dp)) {
                    paths.forEach { Text(it,style=MaterialTheme.typography.bodySmall,color=MaterialTheme.colorScheme.onSurfaceVariant) }
                }
                if((plan["truncated"] as? JsonObject)?.flag(key)==true) Text("Показана часть списка. Общее количество указано выше.",style=MaterialTheme.typography.bodySmall)
            }
        }
        (restore["selection"] as? JsonObject)?.let { selection ->
            selection.text("target_root")?.let { InfoRow("Каталог назначения",it) }
            Text(if(selection.flag("protective_backup")) "Перед применением создаётся защитная копия" else "Без защитной копии",style=MaterialTheme.typography.bodySmall)
        }
    }
}

private fun backupSize(bytes: Double): String = when {
    bytes>=1073741824 -> "%.1f ГБ".format(bytes/1073741824)
    bytes>=1048576 -> "%.1f МБ".format(bytes/1048576)
    bytes>=1024 -> "%.1f КБ".format(bytes/1024)
    else -> "${bytes.toLong()} Б"
}
