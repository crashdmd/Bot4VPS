package com.bot4vps.mobile.ui.settings

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.background
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import com.bot4vps.mobile.BuildConfig
import com.bot4vps.mobile.data.api.*
import com.bot4vps.mobile.data.local.PreferencesManager
import com.bot4vps.mobile.data.local.AppLockManager
import com.bot4vps.mobile.data.local.MobileUpdateManager
import com.bot4vps.mobile.data.model.*
import com.bot4vps.mobile.data.repository.checkedObject
import com.bot4vps.mobile.ui.components.*
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.first
import kotlinx.serialization.json.*
import javax.inject.Inject

val settingsCategories = linkedMapOf("common" to "Параметры", "web" to "Безопасность", "telegram" to "Telegram", "notify" to "Уведомления", "data" to "Данные", "updates" to "Обновления", "about" to "О программе")

@HiltViewModel
class PanelSettingsViewModel @Inject constructor(saved: SavedStateHandle, val client: NativePanelClient,
    val prefs: PreferencesManager, private val workflow: NativeWorkflow, private val mobile: MobileAccessClient, val appLock: AppLockManager, val mobileUpdates: MobileUpdateManager) : ViewModel() {
    var category by mutableStateOf(when (saved.get<String>("section")) { "security" -> "web"; "telegram" -> "telegram"; "update" -> "updates"; "notifications" -> "notify"; else -> "common" }); private set
    val data = mutableStateMapOf<String, JsonObject>()
    var loading by mutableStateOf(false); private set
    var busy by mutableStateOf(false); private set
    var error by mutableStateOf<String?>(null); private set
    var notice by mutableStateOf<String?>(null); private set
    var mobileConnection by mutableStateOf(false); private set
    private var request: Job? = null
    init { refresh() }
    fun select(value: String) { if (busy || value == category) return; category = value; error = null; notice = null; refresh() }
    fun refresh() {
        request?.cancel()
        val selected = category
        val paths = when (selected) {
            "common" -> listOf("/api/settings/timezone")
            "web" -> listOf("/api/auth/account", "/api/auth/totp", "/api/masterkey/status", "/api/settings/web", "/api/settings/web/tls")
            "telegram" -> listOf("/api/telegram/status")
            "data" -> listOf("/api/settings/history")
            "about" -> listOf("/api/ping")
            else -> emptyList()
        }
        if (paths.isEmpty()) { loading = false; return }
        loading = true
        error = null
        request = viewModelScope.launch {
            prefs.baseUrl.first()?.let { mobileConnection = mobile.isPaired(PanelUrl.endpoint(it, "/api/me")) }
            try { coroutineScope { paths.map { path -> async {
                try { path to client.checkedObject("GET", path) }
                catch (e: CancellationException) { throw e }
                catch (e: Exception) { error = errorText(e); null }
            } }.awaitAll().filterNotNull().forEach { (path, value) -> data[path] = value } } }
            finally { if (category == selected) loading = false }
        }
    }
    fun prepare(id: String, values: Map<String, JsonElement> = emptyMap()) { if (values.isNotEmpty()) workflow.put(id, JsonObject(values)) }
    fun theme(value: String) {
        viewModelScope.launch {
            prefs.setTheme(value)
            try { client.checkedObject("POST", "/api/settings/theme", buildJsonObject { put("theme", value) }) }
            catch (e: CancellationException) { throw e }
            catch (_: Exception) { notice = "Тема сохранена на устройстве" }
        }
    }
    fun save(path: String, body: JsonObject, message: String = "Сохранено", method: String = "POST") {
        if (busy) return
        busy = true; error = null; notice = null
        viewModelScope.launch {
            try { val result = client.checkedObject(method, path, body); data[path] = JsonObject(data[path].orEmpty() + result); notice = message }
            catch (e: CancellationException) { throw e }
            catch (e: Exception) { error = errorText(e) }
            finally { busy = false }
        }
    }
    fun telegram(enabled: Boolean) {
        if (busy) return
        val path = "/api/telegram/status"
        val old = data[path] ?: return
        busy = true; error = null; notice = null
        data[path] = JsonObject(old + ("enabled" to JsonPrimitive(enabled)))
        viewModelScope.launch {
            try {
                val response = client.checkedObject("POST", if (enabled) "/api/telegram/start" else "/api/telegram/stop")
                data[path] = JsonObject(data[path].orEmpty() + response + ("enabled" to JsonPrimitive(enabled)))
                notice = if (enabled) "Бот включён" else "Бот выключен"
                refresh()
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) { data[path] = old; error = errorText(e) }
            finally { busy = false }
        }
    }
}

@Composable
fun SettingRow(title: String, description: String = "", control: @Composable () -> Unit = {}) {
    Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Medium)
            if (description.isNotEmpty()) Text(description, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        control()
    }
}

@Composable
fun ThemeChoices(theme: String, onTheme: (String) -> Unit) {
    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        listOf("light" to "Светлая", "dark" to "Тёмная", "glass" to "Синяя").forEach { (id, label) ->
            PanelTab(theme == id, { onTheme(id) }, { Text(label) })
        }
    }
}

@Composable
fun SettingsCard(title: String, description: String = "", content: @Composable ColumnScope.() -> Unit) {
    val icon = when (title) {
        "Оформление" -> Icons.Default.Palette
        "Часовой пояс" -> Icons.Default.Schedule
        "Учётная запись" -> Icons.Default.Security
        "Веб-панель" -> Icons.Default.Https
        "Мастер-ключ" -> Icons.Default.Key
        "Двухфакторная защита" -> Icons.Default.VerifiedUser
        "Пароль резервных копий" -> Icons.Default.Lock
        "Защита приложения" -> Icons.Default.Fingerprint
        "Панель Bot4VPS", "Приложение Bot4VPS Mobile" -> Icons.Default.SystemUpdate
        "Резервное копирование" -> Icons.Default.Backup
        "Telegram" -> Icons.Default.Send
        "Лимиты хранения" -> Icons.Default.Storage
        "Очистка журналов" -> Icons.Default.DeleteOutline
        else -> Icons.Default.Info
    }
    PanelCard {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Box(Modifier.size(38.dp).background(MaterialTheme.colorScheme.primary.copy(alpha = .12f), RoundedCornerShape(12.dp)), contentAlignment = Alignment.Center) { Icon(icon, null, Modifier.size(21.dp), tint = MaterialTheme.colorScheme.primary) }
            Text(title, modifier = Modifier.weight(1f), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
        }
        if (description.isNotBlank()) Text(description, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        content()
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PanelSettingsScreen(onBack: () -> Unit, onOperation: (String) -> Unit, onLogin: () -> Unit,
    viewModel: PanelSettingsViewModel = hiltViewModel()) {
    val theme by viewModel.prefs.theme.collectAsState(initial = "dark")
    val pendingConnection by viewModel.prefs.pendingConnection.collectAsState(initial=null)
    val connection=remember(pendingConnection) { pendingConnection?.let { runCatching { Json.decodeFromString<PanelConnection>(it) }.getOrNull() } }
    val notifications: NotificationsViewModel? = if(viewModel.category == "telegram") hiltViewModel() else null
    val notificationState = notifications?.state?.collectAsStateWithLifecycle()?.value
    val aboutUpdates: UpdatesViewModel? = if (viewModel.category == "about") hiltViewModel() else null
    val panelUpdates: UpdatesViewModel? = if (viewModel.category == "updates") hiltViewModel() else null
    aboutUpdates?.let { UpdateDialogs(it) }
    val snack = remember { SnackbarHostState() }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(lifecycle, viewModel) { lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) { viewModel.refresh(); awaitCancellation() } }
    LaunchedEffect(lifecycle, aboutUpdates) {
        aboutUpdates?.let { updates -> lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) { updates.observe() } }
    }
    LaunchedEffect(notifications) { notifications?.refresh() }
    var tlsModes by remember { mutableStateOf(false) }
    var masterKeyView by remember { mutableStateOf(false) }
    if (masterKeyView) MasterKeyViewDialog(viewModel.client, viewModel.appLock) { masterKeyView = false }
    var clear by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(viewModel.error, viewModel.notice) { (viewModel.error ?: viewModel.notice)?.let { snack.showSnackbar(it) } }
    fun open(id: String, values: Map<String, JsonElement> = emptyMap()) { viewModel.prepare(id, values); onOperation(id) }
    clear?.let { kind -> AlertDialog(onDismissRequest = { clear = null }, title = { Text("Очистить ${if (kind == "tasks") "историю задач" else "журнал событий"}?") },
        text = { Text("Сохранённые записи и логи будут удалены без возможности восстановления.") },
        confirmButton = { TextButton(onClick = { clear = null; viewModel.save(if (kind == "tasks") "/api/tasks/history" else "/api/events", buildJsonObject { }, "Записи удалены", "DELETE") }) { Text("Очистить") } },
        dismissButton = { TextButton(onClick = { clear = null }) { Text("Отмена") } }) }
    if (tlsModes) ModalBottomSheet(onDismissRequest = { tlsModes = false }) {
        Column(Modifier.padding(16.dp)) {
            Text("Защищённое подключение HTTPS", style = MaterialTheme.typography.titleMedium)
            listOf("self-signed" to "Самоподписанный сертификат", "letsencrypt" to "Let's Encrypt", "custom" to "Готовый сертификат на сервере", "upload" to "Загрузить сертификат", "proxy" to "Обратный прокси").forEach { (mode, title) ->
                TextButton(onClick = { tlsModes = false; open("POST /api/settings/web/tls/$mode") }, modifier = Modifier.fillMaxWidth()) { Text(title, Modifier.fillMaxWidth()) }
            }
        }
    }
    PanelScaffold(topBar = { Column {
        PanelTopBar(title = { Text("Настройки") }, navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Назад") } },
            actions = { IconButton(onClick = { when {
                panelUpdates != null -> panelUpdates.refresh()
                notifications != null -> notifications.refresh()
                else -> viewModel.refresh()
            } }, enabled = !viewModel.busy && notificationState?.loading != true && notificationState?.saving != true && panelUpdates?.busy != true && panelUpdates?.active != true) { Icon(Icons.Default.Refresh, "Обновить") } })
        LazyRow(contentPadding = PaddingValues(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            items(settingsCategories.toList()) { (id, name) -> PanelTab(viewModel.category == id, { viewModel.select(id) }, { Text(name) }, enabled = !viewModel.busy) }
        }
    } }, snackbarHost = { SnackbarHost(snack) }) { padding ->
        if (viewModel.category == "updates") {
            panelUpdates?.let { UpdatesContent(Modifier.fillMaxSize().padding(padding), onLogin = onLogin,
                mobileUpdates = viewModel.mobileUpdates, viewModel = it) }
        } else if(viewModel.category == "notify") {
            PhoneNotificationsContent(Modifier.fillMaxSize().padding(padding), prefs = viewModel.prefs)
        } else Refreshable(viewModel.loading, viewModel::refresh, Modifier.fillMaxSize().padding(padding)) {
        LazyColumn(Modifier.fillMaxSize().imePadding(), contentPadding = PaddingValues(16.dp), verticalArrangement = refreshArrangement(12.dp)) {
            if (viewModel.loading) item { LinearProgressIndicator(Modifier.fillMaxWidth()) }
            when (viewModel.category) {
                "common" -> {
                    item { SettingsCard("Оформление", "Выберите удобную тему интерфейса. Изменение применяется сразу на этом телефоне.") { ThemeChoices(theme, viewModel::theme) } }
                    item { SettingsCard("Часовой пояс", "Определяет время журналов и расписаний на хосте Bot4VPS. Часовой пояс телефона не меняется.") {
                        val tz = viewModel.data["/api/settings/timezone"]
                        val zones = (tz?.get("options") as? JsonArray).orEmpty().flatMap { group ->
                            ((group as? JsonObject)?.get("zones") as? JsonArray).orEmpty().mapNotNull { value -> (value as? JsonObject)?.let { row -> row.text("value")?.let { it to (row.text("label") ?: it) } } }
                        }
                        if (tz == null) Text("Не удалось прочитать часовой пояс") else SearchableChoice("Часовой пояс", tz.text("timezone"), zones,
                            { zone -> zone?.let { viewModel.save("/api/settings/timezone", buildJsonObject { put("timezone", it) }) } }, enabled = !viewModel.busy, searchHint = "Найти город или часовой пояс")
                    } }
                }
                "web" -> {
                    item { AppLockSettingsCard(viewModel.appLock) }
                    connection?.let { pending -> item { SettingsCard("Изменение подключения") { Text(pending.target); TextButton(onClick={ open(pending.operation) }) { Text("Продолжить проверку подключения") } } } }
                    item { SettingsCard("Учётная запись", "Вход в веб-панель и приложение по логину и паролю. Доступ привязанного устройства через API управляется отдельно.") {
                        val account = viewModel.data["/api/auth/account"]
                        SettingRow("Вход по паролю", if (account?.flag("auth_enabled") == true) "При входе требуется логин и пароль" else "Вход в панель без пароля") {
                            Switch(account?.flag("auth_enabled") == true, { enabled -> open(if (enabled) "POST /api/auth/account" else "POST /api/auth/disable", if (enabled) mapOf("auth_enabled" to JsonPrimitive(true)) else emptyMap()) }, enabled = account != null)
                        }
                        HorizontalDivider()
                        SettingRow("Логин", account?.text("username") ?: "Не задан") { PanelSecondaryButton(onClick = { open("POST /api/auth/account") }) { Text("Изменить") } }
                        SettingRow("Пароль", "Текущий пароль не отображается") { PanelSecondaryButton(onClick = { open("POST /api/auth/password") }) { Text("Изменить") } }
                    } }
                    item { SettingsCard("Двухфакторная защита", "Дополнительный одноразовый код при входе в панель и приложение. Привязка телефона через API не отменяет защиту учётной записи.") {
                        val totp = viewModel.data["/api/auth/totp"]
                        SettingRow("Двухфакторная защита", "Код из приложения при входе") { Switch(totp?.flag("enabled") == true,
                            { enabled -> open(if (enabled) "POST /api/auth/totp/setup" else "POST /api/auth/totp/disable") }, enabled = totp != null) }
                    } }
                    item { SettingsCard("Веб-панель", "Порт и HTTPS веб-интерфейса на хосте Bot4VPS. У отдельного мобильного API собственные порт и HTTPS.") {
                        if (viewModel.mobileConnection) Text("Приложение подключено через отдельный API. Изменение веб-порта не меняет адрес приложения.", style = MaterialTheme.typography.bodySmall)
                        val web = viewModel.data["/api/settings/web"]
                        SettingRow("Порт веб-панели", web?.text("port") ?: "—") { PanelSecondaryButton(onClick = { open("POST /api/settings/web/port") }, enabled = web?.flag("changeable") == true && web.flag("busy") != true) { Text("Изменить") } }
                        val tls = viewModel.data["/api/settings/web/tls"]
                        HorizontalDivider()
                        SettingRow("HTTPS", tlsModeLabel((tls?.get("config") as? JsonObject)?.text("mode"))) { Switch((tls?.get("unit") as? JsonObject)?.flag("ssl") == true || (tls?.get("unit") as? JsonObject)?.flag("proxy") == true, { enabled -> if (enabled) tlsModes = true else open("POST /api/settings/web/tls/off") }, enabled = tls?.flag("changeable") == true && !tls.flag("busy")) }
                        if ((tls?.get("config") as? JsonObject)?.text("mode") in setOf("self-signed", "letsencrypt", "custom")) PanelSecondaryButton(onClick = { open("POST /api/settings/web/tls/renew") }) { Text("Обновить сертификат") }
                    } }
                    item { SettingsCard("Мастер-ключ", "Защищает сохранённые пароли, токены и другие секреты панели. Сохраните копию ключа отдельно от сервиса.") {
                        val key = viewModel.data["/api/masterkey/status"]
                        Text(when (key?.text("state")) { "ok" -> "Ключ доступен"; "missing_no_data" -> "Зашифрованных данных пока нет. Ключ создастся при первом сохранении секрета"; "missing_with_data" -> "Ключ отсутствует. Нужно восстановить доступ к секретам"; "mismatch" -> "Ключ не подходит к сохранённым секретам"; else -> key?.text("message") ?: "Состояние ключа недоступно" })
                        if(key?.text("state") == "ok") PanelSecondaryButton(onClick = { masterKeyView = true }, enabled=(key["channels"] as? JsonObject)?.flag("any") == true) { Text("Получить копию ключа") }
                        if(key?.text("state")=="ok" && (key["channels"] as? JsonObject)?.flag("any")!=true) Text("Для получения копии ключа настройте канал подтверждения в панели.",style=MaterialTheme.typography.bodySmall,color=MaterialTheme.colorScheme.onSurfaceVariant)
                        if(key?.text("state") in setOf("missing_with_data","mismatch")) PanelSecondaryButton(onClick = { open("POST /api/masterkey/restore") }) { Text("Восстановить ключ") }
                        if (key?.text("state") in setOf("missing_with_data","mismatch")) {
                            Text("Новый ключ не расшифрует старые секреты. Это действие потребуется подтвердить.",style=MaterialTheme.typography.bodySmall,color=MaterialTheme.colorScheme.error)
                            PanelSecondaryButton(onClick = { open("POST /api/masterkey/new") }) { Text("Создать новый ключ") }
                        }
                        if ((key?.get("plaintext") as? JsonObject)?.flag("found") == true && key.text("state") in setOf("ok","missing_no_data")) PanelSecondaryButton(onClick = { open("POST /api/masterkey/encrypt-secrets") }) { Text("Зашифровать сохранённые секреты") }
                    } }
                }
                "telegram" -> {
                item { SettingsCard("Telegram", "Подключение бота и получатель сообщений. Настройки доставки уведомлений находятся ниже.") {
                    val telegram = viewModel.data["/api/telegram/status"]
                    val status = telegram?.get("status") as? JsonObject
                    SettingRow("Бот включён", status?.text("error") ?: if (status?.text("state") == "running") "Бот работает" else "Бот остановлен") {
                        Switch(telegram?.flag("enabled") == true, viewModel::telegram, enabled = telegram != null && !viewModel.busy)
                    }
                    HorizontalDivider()
                    InfoRow("Токен бота", if (telegram?.flag("token_set") == true) "Настроен" else "Не задан")
                    InfoRow("Получатель", telegram?.text("user_id") ?: "Не задан")
                    PanelSecondaryButton(onClick = { open("POST /api/telegram/settings") }, enabled=telegram!=null && !viewModel.busy, modifier=Modifier.fillMaxWidth()) { Text("Настроить подключение") }
                    PanelSecondaryButton(onClick = { open("POST /api/telegram/health") }, enabled=telegram!=null && !viewModel.busy, modifier=Modifier.fillMaxWidth()) { Text("Проверить доставку сообщения") }
                    if (telegram?.flag("enabled") == true && status?.text("state") != "running") PanelSecondaryButton(onClick = { open("POST /api/telegram/start") }) { Text("Запустить бота") }
                } }
                notificationState?.let { telegramDeliveryItems(it, notifications!!) }
                }
                "data" -> {
                    item { SettingsCard("Лимиты хранения", "Ограничивают размер журналов на панели. Удаление старых записей происходит автоматически при превышении лимита.") {
                        val limits = viewModel.data["/api/settings/history"]
                        var tasks by rememberSaveable(limits?.text("tasks")) { mutableStateOf(limits?.text("tasks").orEmpty()) }
                        var events by rememberSaveable(limits?.text("events")) { mutableStateOf(limits?.text("events").orEmpty()) }
                        PanelTextField(tasks, { tasks = it }, label = { Text("История задач, записей") }, keyboardOptions=androidx.compose.foundation.text.KeyboardOptions(keyboardType=androidx.compose.ui.text.input.KeyboardType.Number), singleLine = true, enabled = limits != null && !viewModel.busy, modifier = Modifier.fillMaxWidth())
                        PanelTextField(events, { events = it }, label = { Text("Журнал событий, записей") }, keyboardOptions=androidx.compose.foundation.text.KeyboardOptions(keyboardType=androidx.compose.ui.text.input.KeyboardType.Number), singleLine = true, enabled = limits != null && !viewModel.busy, modifier = Modifier.fillMaxWidth())
                        Text("От 1 до 10000 записей. Старые записи сверх лимита удаляются.", style = MaterialTheme.typography.bodySmall)
                        PanelButton(enabled = tasks.toIntOrNull()?.let { it in 1..10000 } == true && events.toIntOrNull()?.let { it in 1..10000 } == true && !viewModel.busy,
                            onClick = { viewModel.save("/api/settings/history", buildJsonObject { put("tasks", tasks.toInt()); put("events", events.toInt()) }) }, modifier=Modifier.fillMaxWidth()) { Text("Сохранить лимиты") }
                    } }
                    item { BackupPasswordCard(onOperation={ open(it) }) }
                    item { SettingsCard("Очистка журналов", "Удаление потребует подтверждения. Серверы, настройки и выполняющиеся задачи сохраняются.") {
                        SettingRow("История задач", "Завершённые задачи и сохранённые логи") { TextButton(onClick = { clear = "tasks" }) { Text("Очистить") } }
                        HorizontalDivider()
                        SettingRow("Журнал событий", "Все события и уведомления") { TextButton(onClick = { clear = "events" }) { Text("Очистить") } }
                    } }
                }
                "about" -> {
                    item { PanelAboutCard(viewModel.data["/api/ping"]?.text("version"),
                        { aboutUpdates?.currentNotes() }, aboutUpdates?.busy == false) }
                    aboutUpdates?.error?.let { item { ErrorCard(it, { aboutUpdates.currentNotes() }) } }
                    aboutUpdates?.let { updates -> if (updates.progress != null) item { UpdateProgress(updates, onLogin) } }
                }
            }
        }
    }
    }
}

fun tlsModeLabel(mode: String?): String = when(mode) {
    "off" -> "Выключен"; "self-signed" -> "Самоподписанный сертификат"; "letsencrypt" -> "Сертификат Let’s Encrypt"
    "custom" -> "Готовый сертификат"; "proxy" -> "HTTPS через обратный прокси"; else -> "Состояние загружается"
}
