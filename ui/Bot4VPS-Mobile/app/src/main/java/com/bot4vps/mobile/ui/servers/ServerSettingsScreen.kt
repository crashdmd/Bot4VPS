package com.bot4vps.mobile.ui.servers

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.*
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import com.bot4vps.mobile.data.model.*
import com.bot4vps.mobile.ui.components.*
import com.bot4vps.mobile.ui.theme.Background
import kotlinx.coroutines.awaitCancellation
import kotlinx.serialization.json.*

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ServerSettingsScreen(onBack: () -> Unit, viewModel: ServerSettingsViewModel = hiltViewModel()) {
    val state by viewModel.ui.collectAsState()
    val page = state.page.takeUnless { it == ServerSettingPage.HOME } ?: ServerSettingPage.GENERAL
    val snackbar = remember { SnackbarHostState() }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    var discard by remember { mutableStateOf(false) }
    var showOutput by remember { mutableStateOf(false) }
    val scroll = rememberLazyListState()
    LaunchedEffect(lifecycle, viewModel) { lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) { viewModel.refresh(); awaitCancellation() } }
    LaunchedEffect(state.notice) { state.notice?.let { snackbar.showSnackbar(it); viewModel.clearNotice() } }
    LaunchedEffect(state.page) { scroll.scrollToItem(0) }
    fun leave() {
        if (state.busy) return
        if (state.dirty) discard = true else onBack()
    }
    BackHandler(enabled = state.action == null && state.list == null && state.editor == null && !showOutput) { leave() }
    if (discard) AlertDialog(onDismissRequest = { discard = false }, title = { Text("Отменить изменения?") },
        text = { Text("В настройках есть несохранённые изменения.") },
        confirmButton = { TextButton(onClick = {
            discard = false
            viewModel.resetGeneral()
            viewModel.resetConnection()
            onBack()
        }) { Text("Отменить изменения") } }, dismissButton = { TextButton(onClick = { discard = false }) { Text("Продолжить редактирование") } })
    state.action?.takeIf { it.showDialog }?.let { action -> SettingActionDialog(action, state, viewModel) }
    state.list?.let { list -> SettingListSheet(list, state, viewModel) }
    state.editor?.let { SettingEditorSheet(it, state, viewModel) }
    if (showOutput) ModalBottomSheet(onDismissRequest = { showOutput = false }) {
        Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(20.dp)) {
            Text("Вывод операции", style = MaterialTheme.typography.titleLarge)
            SelectionContainer { Text(state.output.orEmpty(), Modifier.padding(vertical = 16.dp), fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.bodySmall) }
        }
    }
    PanelScaffold(snackbarHost = { SnackbarHost(snackbar) }, topBar = {
        Column {
            PanelTopBar(title = { Column {
                Text("Настройки сервера", maxLines = 1, overflow = TextOverflow.Ellipsis)
                state.server?.let { Text(listOfNotNull(it.text("name"), it.text("host")).joinToString(" · "), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis) }
            } }, navigationIcon = { IconButton(enabled = !state.busy, onClick = ::leave) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Назад") } }, actions = {
                IconButton(enabled = !state.refreshing && !state.busy, onClick = viewModel::refresh) { Icon(Icons.Default.Refresh, "Обновить состояние") }
            })
            LazyRow(contentPadding = PaddingValues(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                items(ServerSettingPage.entries.filter { it != ServerSettingPage.HOME }) { section ->
                    PanelTab(page == section, { viewModel.page(section) }, enabled = !state.busy, label = { Text(section.title) })
                }
            }
        }
    }, bottomBar = {
        val editable = page in listOf(ServerSettingPage.GENERAL, ServerSettingPage.CONNECTION, ServerSettingPage.PACKAGES)
        if (editable && state.server != null) Surface(tonalElevation = 2.dp) {
            PanelButton(modifier = Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 12.dp),
                enabled = !state.busy && !state.refreshing && when (page) {
                    ServerSettingPage.GENERAL -> state.generalDirty
                    ServerSettingPage.CONNECTION -> state.connectionDirty
                    else -> state.canAdmin && state.selectedPackages.isNotEmpty()
                }, onClick = {
                    when (page) {
                        ServerSettingPage.GENERAL -> viewModel.saveGeneral()
                        ServerSettingPage.CONNECTION -> viewModel.saveConnection()
                        else -> viewModel.action("packages/install", "Установить пакеты?", "Выбранные пакеты будут установлены на этом сервере.", "Установить", buildJsonObject { put("packages", JsonArray(state.selectedPackages.map(::JsonPrimitive))) })
                    }
                }) {
                if (state.saving) { CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp); Spacer(Modifier.width(10.dp)) }
                Text(if (page == ServerSettingPage.PACKAGES) "Установить выбранные (${state.selectedPackages.size})" else "Сохранить изменения")
            }
        }
    }) { padding ->
        LazyColumn(state = scroll, modifier = Modifier.fillMaxSize().padding(padding).imePadding(),
            contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            if (state.server == null) {
                item { Box(Modifier.fillMaxWidth().height(160.dp), contentAlignment = Alignment.Center) { if (state.refreshing) CircularProgressIndicator() else Text(state.error ?: "Сервер недоступен", color = MaterialTheme.colorScheme.error) } }
            } else {
                when (page) {
                    ServerSettingPage.HOME -> Unit
                    ServerSettingPage.GENERAL -> {
                        item { Text("Как сервер отображается в приложении", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                        item { PanelTextField(state.draft.name, { value -> viewModel.edit { it.copy(name = value) } }, label = { Text("Имя сервера") }, singleLine = true, enabled = !state.busy, modifier = Modifier.fillMaxWidth()) }
                        item { SettingsChoice("Группа", state.draft.group, (state.groups + (state.draft.group to state.draft.group)).filter { it.first.isNotBlank() }.distinctBy { it.first }, !state.busy) { value -> viewModel.edit { it.copy(group = value) } } }
                        item { PanelCard {
                            SettingsSwitch("Проверять SSL-сертификат", "Показывать срок действия и предупреждать об истечении", state.draft.sslEnabled, !state.busy) { value -> viewModel.edit { it.copy(sslEnabled = value) } }
                            if (state.draft.sslEnabled) PanelTextField(state.draft.sslHost, { value -> viewModel.edit { it.copy(sslHost = value) } }, label = { Text("Домен сертификата") }, placeholder = { Text(state.draft.host) }, supportingText = { Text("Пустое поле — проверять адрес сервера") }, singleLine = true, enabled = !state.busy, modifier = Modifier.fillMaxWidth(), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri))
                        } }
                    }
                    ServerSettingPage.CONNECTION -> {
                        item { Text("Адрес и учётные данные, которые приложение использует для подключения.", color = MaterialTheme.colorScheme.onSurfaceVariant) }
                        item { PanelTextField(state.draft.host, { value -> viewModel.edit { it.copy(host = value) } }, label = { Text("IP-адрес или имя хоста") }, singleLine = true, enabled = !state.busy, modifier = Modifier.fillMaxWidth(), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri)) }
                        item { Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                            PanelTextField(state.draft.port, { value -> viewModel.edit { it.copy(port = value) } }, label = { Text("SSH-порт") }, singleLine = true, enabled = !state.busy, modifier = Modifier.weight(.4f), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number))
                            PanelTextField(state.draft.user, { value -> viewModel.edit { it.copy(user = value) } }, label = { Text("Пользователь") }, singleLine = true, enabled = !state.busy, modifier = Modifier.weight(.6f))
                        } }
                        item { PanelCard("Способ входа") {
                            listOf("password" to "Пароль", "key" to "SSH-ключ").forEach { (value, label) ->
                                Row(Modifier.fillMaxWidth().clickable(enabled = !state.busy) { viewModel.edit { it.copy(authType = value) } }, verticalAlignment = Alignment.CenterVertically) {
                                    RadioButton(selected = state.draft.authType == value, enabled = !state.busy, onClick = { viewModel.edit { it.copy(authType = value) } }); Text(label)
                                }
                            }
                            if (state.draft.authType == "key") {
                                SettingsChoice("SSH-ключ", state.draft.keyPath, (state.keys + listOfNotNull(state.draft.keyPath.takeIf(String::isNotBlank)?.let { it to it.substringAfterLast('/') })).distinctBy { it.first }, !state.busy) { value -> viewModel.edit { it.copy(keyPath = value) } }
                                state.keysError?.let { Text("Не удалось загрузить ключи: $it", color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
                            }
                            SecretSetting(state.draft.password, !state.busy,
                                if (state.draft.authType == "key") "Пароль для sudo" else "Пароль",
                                "Оставьте пустым, чтобы сохранить текущий пароль") { value -> viewModel.edit { it.copy(password = value) } }
                        } }
                        item { PanelSecondaryButton(onClick = viewModel::testConnection, enabled = !state.busy && !state.refreshing, modifier = Modifier.fillMaxWidth()) { if (state.busy && !state.saving) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp) else Icon(Icons.Default.NetworkCheck, null, Modifier.size(18.dp)); Spacer(Modifier.width(8.dp)); Text("Проверить подключение") } }
                        item { Text("Изменение порта здесь меняет адрес подключения. Чтобы изменить порт на самом сервере, откройте «Доступ по SSH».", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                    }
                    ServerSettingPage.SYSTEM -> {
                        val d = state.section("diagnostics"); val sys = state.section("system")
                        item { PanelCard("Сведения о системе") {
                            InfoRow("ОС", listOfNotNull(d.text("os"), d.text("os_version")?.takeIf { it != "—" }).joinToString(" ").ifBlank { "Нет данных" })
                            InfoRow("Процессор", d.text("cpu_model") ?: "Нет данных")
                            InfoRow("Ядра", d.text("cpu_cores") ?: "—"); InfoRow("Память", d.text("ram") ?: "—")
                            InfoRow("Диск", d.text("disk") ?: "—"); InfoRow("Время работы", d.text("uptime") ?: "—")
                            InfoRow("Ядро ОС", d.text("kernel") ?: "—"); InfoRow("Архитектура", d.text("arch") ?: "—")
                            d.text("ssh_error")?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
                        } }
                        item { PanelCard("Обновления") {
                            Text(sys.text("updates_summary")?.takeIf { it.isNotBlank() && it != "—" } ?: "Проверка ещё не выполнялась")
                            sys.text("last_check")?.let { Text("Последняя проверка: ${displayTime(it)}", color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall) }
                            PanelButton(enabled = state.canAdmin && !state.busy && !state.refreshing, onClick = { viewModel.action("system/check-updates", "Проверить обновления", "Получить список доступных обновлений пакетов.", "Проверить", showDialog = false) }) { Text("Проверить обновления") }
                            if (sys.flag("updates_available")) PanelSecondaryButton(enabled = state.canAdmin && !state.busy && !state.refreshing, onClick = { viewModel.action("system/upgrade", "Обновить систему?", "Пакеты сервера будут обновлены. Это может занять несколько минут.", "Обновить") }) { Text("Установить обновления") }
                        } }
                        item { SettingsEntry("Перезагрузить сервер", "Активные подключения будут прерваны", Icons.Default.RestartAlt, danger = true, enabled = state.canAdmin && !state.busy && !state.refreshing) { viewModel.action("system/reboot", "Перезагрузить сервер?", "Активные подключения будут прерваны. Сервер на некоторое время станет недоступен.", "Перезагрузить") } }
                    }
                    ServerSettingPage.SSH -> {
                        val ssh = state.section("ssh_access")
                        val enabled = state.sshReady && !state.busy && !state.refreshing
                        item { PanelCard("Текущее подключение") {
                            InfoRow("Пользователь", ssh.text("user") ?: "—"); InfoRow("Способ входа", if (ssh.text("auth_type") == "key") "SSH-ключ" else "Пароль")
                            InfoRow("Порт", ssh.text("port") ?: "—")
                            ssh.text("error")?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
                        } }
                        item { SettingsGroup("Учётные записи") {
                            SettingsEntry("Пользователи", "Список, права и ключи доступа", Icons.Default.People, enabled = enabled) { viewModel.list("ssh/users", "Пользователи") }
                            if (state.canAdmin) SettingsEntry("Создать пользователя", "Новая учётная запись на сервере", Icons.Default.PersonAdd, enabled = enabled) { viewModel.action("ssh/users", "Создать пользователя", "Новый пользователь будет создан без переключения текущего подключения.", "Создать", buildJsonObject { put("sudo", false) }) }
                            SettingsEntry("Переключить пользователя", "Изменить учётную запись подключения", Icons.Default.SwitchAccount, enabled = enabled) { viewModel.action("ssh/users/switch", "Переключить пользователя", "Введите учётные данные целевого пользователя. Текущий пароль автоматически не подставляется.", "Переключить") }
                            SettingsEntry("SSH-ключи", "Ключи текущего пользователя", Icons.Default.Key, enabled = enabled) { viewModel.list("ssh/users/{username}/keys", "SSH-ключи", buildJsonObject { put("username", ssh.text("user") ?: state.server?.text("user") ?: "root") }) }
                            SettingsEntry("Сменить пароль", "Пароль текущего пользователя на сервере", Icons.Default.Password, enabled = enabled) { viewModel.action("ssh/password", "Сменить пароль", "Пароль будет изменён на сервере и в сохранённом подключении.", "Изменить") }
                        } }
                        if (state.canAdmin) item { SettingsGroup("Способы доступа") {
                            SettingsEntry("Изменить SSH-порт", "Текущий порт: ${ssh.text("port") ?: "—"}", Icons.Default.SettingsEthernet, enabled = enabled) { viewModel.action("ssh/port", "Изменить SSH-порт", "Изменить порт SSH на сервере и проверить новый доступ.", "Изменить", buildJsonObject { put("port", (ssh["port"] as? JsonPrimitive)?.intOrNull ?: 22) }) }
                            SettingsEntry("Вход root", ssh.text("root_login") ?: "Состояние неизвестно", Icons.Default.AdminPanelSettings, enabled = enabled) { viewModel.action("ssh/root-login", "Вход root", "Изменение применяется после проверки запасного доступа.", values = buildJsonObject { put("enabled", ssh.text("root_login")?.contains("разреш", true) == true) }) }
                            SettingsEntry("Вход по паролю", ssh.text("password_auth") ?: "Состояние неизвестно", Icons.Default.LockOpen, enabled = enabled) { viewModel.action("ssh/password-auth", "Вход по паролю", "Перед отключением должен быть подтверждён доступ по SSH-ключу.", values = buildJsonObject { put("enabled", ssh.text("password_auth")?.contains("разреш", true) == true) }) }
                        } }
                        item { PanelCard("Ключ сервера") {
                            Text(ssh.text("host_key_type") ?: "Ключ ещё не закреплён", style = MaterialTheme.typography.bodyMedium)
                            ssh.text("host_key_fingerprint")?.let { SelectionContainer { Text(it, fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.bodySmall) } }
                            if (ssh.flag("host_key_mismatch")) {
                                Text("Сервер предъявил другой ключ. Подключение заблокировано.", color = MaterialTheme.colorScheme.error)
                                PanelSecondaryButton(enabled = !state.busy && !state.refreshing, onClick = { viewModel.action("ssh/hostkey/accept", "Принять новый ключ?", "Подтвердите, что сервер переустановлен или его ключ был изменён вами.", "Принять ключ") }) { Text("Принять новый ключ") }
                            }
                        } }
                    }
                    ServerSettingPage.FIREWALL -> {
                        val fw = state.section("firewall"); val enabled = state.canAdmin && !state.busy && !state.refreshing
                        val candidates = fw.objects("backends")
                        item { PanelCard("Состояние") {
                            Text(fw.text("label") ?: "Состояние ещё не получено", style = MaterialTheme.typography.titleMedium)
                            fw.text("error")?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
                            if (candidates.count { it.flag("active") } > 1) Text("Работает несколько сетевых экранов. При изменениях проверяется каждый из них.", color = MaterialTheme.colorScheme.error)
                            if (fw.flag("active")) {
                                PanelSecondaryButton(enabled = enabled, onClick = { viewModel.list("firewall/rules", "Правила сетевого экрана") }) { Text("Показать правила") }
                                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                    PanelButton(enabled = enabled, onClick = { viewModel.action("firewall/open", "Открыть порт", "Разрешить входящие подключения к порту.", "Открыть") }) { Text("Открыть порт") }
                                    PanelSecondaryButton(enabled = enabled, onClick = { viewModel.action("firewall/close", "Закрыть порт", "Запретить входящие подключения к порту.", "Закрыть") }) { Text("Закрыть порт") }
                                }
                            }
                        } }
                        item { SettingsGroup("Сетевые экраны") {
                            listOf("ufw" to "UFW", "firewalld" to "firewalld", "nftables" to "nftables").forEach { (id, title) ->
                                val candidate = candidates.find { it.text("backend") == id }
                                val active = candidate?.flag("active") == true
                                val installed = candidate?.flag("installed") == true
                                val suffix = if (!installed) "firewall/install" else if (candidates.any { it.flag("active") }) "firewall/switch" else "firewall/enable"
                                val target = if (suffix == "firewall/switch") "target" else "backend"
                                SettingsEntry(title, if (active) "Активен" else if (installed) "Установлен · включить" else if (state.overview == null || fw.text("error") != null) "Нет данных" else "Не установлен · установить", Icons.Default.Security, enabled = enabled && !active && candidates.count { it.flag("active") } < 2) {
                                    viewModel.action(suffix, if (!installed) "Установить $title?" else "Включить $title?",
                                        "Доступ по SSH будет проверен. При переключении приложение предложит решить, какие правила перенести.",
                                        if (!installed) "Установить" else "Включить", buildJsonObject { put(target, id); if (suffix == "firewall/switch") put("confirm", true); if (suffix == "firewall/install") put("confirm_switch", candidates.any { it.flag("active") }) })
                                }
                                if (installed) TextButton(enabled = enabled, onClick = { viewModel.action("firewall/remove", "Удалить $title?", "Пакет будет удалён, его настройки сохранены.", "Удалить", buildJsonObject { put("backend", id) }) }, modifier = Modifier.padding(start = 52.dp)) { Text("Удалить $title", color = MaterialTheme.colorScheme.error) }
                            }
                        } }
                        val chains = candidates.firstOrNull { it.text("backend") == "nftables" }?.get("chain_selection") as? JsonObject
                        if (chains?.flag("required") == true) item { PanelCard("Входящая цепочка nftables") {
                            Text("Выберите существующую цепочку перед включением nftables.", style = MaterialTheme.typography.bodySmall)
                            chains.objects("candidates").forEach { chain ->
                                TextButton(enabled = enabled, onClick = { viewModel.action("firewall/nftables/chain", "Выбрать цепочку?", "${chain.text("family")} / ${chain.text("table")} / ${chain.text("chain")}", "Выбрать", JsonObject(chain.filterKeys { it in setOf("family", "table", "chain") })) }) { Text("${chain.text("family")} / ${chain.text("table")} / ${chain.text("chain")}") }
                            }
                        } }
                        if (fw.flag("active")) item { SettingsEntry("Отключить сетевой экран", "Фильтрация входящего трафика прекратится", Icons.Default.PauseCircle, danger = true, enabled = enabled) { viewModel.action("firewall/disable", "Отключить сетевой экран?", "Входящий трафик больше не будет фильтроваться этим сетевым экраном.", "Отключить") } }
                    }
                    ServerSettingPage.FAIL2BAN -> {
                        val fb = state.section("fail2ban"); val enabled = state.canAdmin && !state.busy && !state.refreshing
                        val installed = fb.flag("installed")
                        item { PanelCard("Fail2ban") {
                            Text(fb.text("label") ?: "Состояние ещё не получено", style = MaterialTheme.typography.titleMedium)
                            Text("Блокирует адреса, с которых подбирают пароли.", color = MaterialTheme.colorScheme.onSurfaceVariant)
                            fb.text("error")?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
                            if (installed) { InfoRow("Заблокированные IP", fb.text("banned_count") ?: "—"); InfoRow("Правила защиты", fb.text("jail_count") ?: "—") }
                            else if (state.overview != null && fb.text("error") == null) PanelButton(enabled = enabled, onClick = { viewModel.action("fail2ban/install", "Установить Fail2ban?", "Установка сервиса сама по себе не включает правила защиты.", "Установить") }) { Text("Установить") }
                        } }
                        if (installed) {
                            item { PanelCard("Параметры защиты") {
                                InfoRow("Время блокировки", fb.text("ban_time") ?: "—"); InfoRow("Период попыток", fb.text("find_time") ?: "—"); InfoRow("Попыток до блокировки", fb.text("max_retry") ?: "—")
                                PanelSecondaryButton(enabled = enabled, onClick = { viewModel.action("fail2ban/settings", "Параметры защиты", "Например: 1h — час, 10m — десять минут. Настройки применяются после проверки конфигурации.", values = JsonObject(fb.filterKeys { it in setOf("ban_time", "find_time", "max_retry") }.filterValues { it != JsonNull })) }) { Text("Изменить параметры") }
                            } }
                            item { SettingsGroup("Правила и адреса") {
                                SettingsEntry("Защищать SSH", if (fb.flag("ssh_jail_enabled")) "Включено" else "Выключено", Icons.Default.Lock, enabled = enabled) { viewModel.action("fail2ban/settings", "Защита SSH", "Включение правила защищает SSH от перебора паролей.", values = buildJsonObject { put("ssh_jail_enabled", !fb.flag("ssh_jail_enabled")) }) }
                                SettingsEntry("Заблокированные IP", "Просмотр и снятие блокировки", Icons.Default.Block, enabled = enabled) { viewModel.list("fail2ban/banned", "Заблокированные IP") }
                                SettingsEntry("Исключения", "Адреса, которые не нужно блокировать", Icons.Default.VerifiedUser, enabled = enabled) { viewModel.list("fail2ban/whitelist", "Исключения") }
                                SettingsEntry("Правила защиты", "Какие службы защищает Fail2ban", Icons.Default.Rule, enabled = enabled) { viewModel.list("fail2ban/jails", "Правила защиты") }
                                SettingsEntry("Фильтры событий", "Какие записи считаются нарушениями", Icons.Default.FilterAlt, enabled = enabled) { viewModel.list("fail2ban/filters", "Фильтры событий") }
                                SettingsEntry("Файлы конфигурации", "Просмотр и редактирование файлов", Icons.Default.Description, enabled = enabled) { viewModel.list("fail2ban/configuration", "Файлы конфигурации") }
                            } }
                            item { SettingsGroup("Управление сервисом") {
                                SettingsEntry(if (fb.flag("running")) "Остановить" else "Запустить", "Fail2ban на этом сервере", Icons.Default.PowerSettingsNew, enabled = enabled) { val suffix = if (fb.flag("running")) "stop" else "start"; viewModel.action("fail2ban/$suffix", if (suffix == "stop") "Остановить Fail2ban?" else "Запустить Fail2ban?", verb = if (suffix == "stop") "Остановить" else "Запустить") }
                                SettingsEntry("Перезапустить", "Перечитать настройки и правила", Icons.Default.RestartAlt, enabled = enabled) { viewModel.action("fail2ban/restart", "Перезапустить Fail2ban?", verb = "Перезапустить") }
                                SettingsEntry("Удалить Fail2ban", "Защита от перебора будет отключена", Icons.Default.DeleteOutline, danger = true, enabled = enabled) { viewModel.action("fail2ban/uninstall", "Удалить Fail2ban?", "Сервис будет удалён с этого сервера.", "Удалить") }
                            } }
                        }
                    }
                    ServerSettingPage.PACKAGES -> {
                        val packages = state.section("packages")
                        item { Text("Выберите программы для установки", color = MaterialTheme.colorScheme.onSurfaceVariant) }
                        packages.text("error")?.let { item { Text(it, color = MaterialTheme.colorScheme.error) } }
                        val rows = packages.objects("items")
                        if (rows.isEmpty()) item { Text(if (state.refreshing) "Получаем список пакетов…" else "Список пакетов недоступен", color = MaterialTheme.colorScheme.onSurfaceVariant) }
                        val titles = mapOf("utils" to "Утилиты", "net" to "Сеть", "diag" to "Диагностика", "services" to "Сервисы")
                        rows.groupBy { it.text("category") ?: "utils" }.forEach { (category, packageRows) ->
                            item(key = "category-$category") { Text(titles[category] ?: "Другие пакеты", style = MaterialTheme.typography.titleSmall) }
                            items(packageRows, key = { "package-${it.text("name")}" }) { pkg ->
                                val name = pkg.text("name").orEmpty(); val installed = pkg.flag("installed")
                                ListItem(headlineContent = { Text(name) }, supportingContent = { Text(if (installed) "Установлен" else "Доступен для установки") },
                                    leadingContent = { Checkbox(checked = !installed && name in state.selectedPackages, enabled = !installed && state.canAdmin && !state.busy, onCheckedChange = { viewModel.selectPackage(name, it) }) })
                            }
                        }
                    }
                }
                if (!state.canAdmin && state.overview != null && page in listOf(ServerSettingPage.SYSTEM, ServerSettingPage.FIREWALL, ServerSettingPage.FAIL2BAN, ServerSettingPage.PACKAGES)) item { Text("Для изменения этих настроек нужен пользователь с правами sudo.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                state.error?.let { item { Text("Не удалось обновить состояние: $it", color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) } }
                if (state.output != null) item { TextButton(onClick = { showOutput = true }) { Text("Подробности последней операции") } }
            }
        }
    }
}

@Composable
private fun SettingsGroup(title: String, content: @Composable ColumnScope.() -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(title, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary, modifier = Modifier.padding(start = 8.dp, bottom = 4.dp))
        PanelSurfaceCard(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)) { Column(content = content) }
    }
}
@Composable
private fun SettingsEntry(title: String, subtitle: String, icon: ImageVector, danger: Boolean = false, enabled: Boolean = true, onClick: () -> Unit) {
    val tint = if (danger) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant
    ListItem(modifier = Modifier.clickable(enabled = enabled, onClick = onClick),
        headlineContent = { Text(title, color = if (danger) tint else MaterialTheme.colorScheme.onSurface.copy(alpha = if (enabled) 1f else .55f)) },
        supportingContent = { Text(subtitle, maxLines = 2, overflow = TextOverflow.Ellipsis) },
        leadingContent = { Icon(icon, null, tint = tint.copy(alpha = if (enabled) 1f else .45f)) },
        trailingContent = { Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null, tint = tint) })
}
@Composable
private fun SettingsChoice(label: String, value: String, options: List<Pair<String, String>>, enabled: Boolean, onSelect: (String) -> Unit) {
    SearchableChoice(label, value.takeIf(String::isNotBlank), options, { it?.let(onSelect) },
        emptyLabel = "Выбрать", enabled = enabled, searchHint = when (label) { "Группа" -> "Найти группу"; "SSH-ключ" -> "Найти ключ"; else -> "Найти вариант" })
}
@Composable
private fun SettingsSwitch(title: String, hint: String, checked: Boolean, enabled: Boolean, onChecked: (Boolean) -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(title, style = MaterialTheme.typography.titleSmall)
            if (hint.isNotBlank()) Text(hint, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Switch(checked = checked, enabled = enabled, onCheckedChange = onChecked)
    }
}
@Composable
private fun SecretSetting(value: String, enabled: Boolean, label: String, hint: String, onChange: (String) -> Unit) {
    var visible by rememberSaveable { mutableStateOf(false) }
    PanelTextField(value, onChange, label = { Text(label) }, supportingText = if (hint.isBlank()) null else { { Text(hint) } }, modifier = Modifier.fillMaxWidth(), enabled = enabled, singleLine = true,
        visualTransformation = if (visible) VisualTransformation.None else PasswordVisualTransformation(),
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password), trailingIcon = {
            IconButton(onClick = { visible = !visible }) { Icon(if (visible) Icons.Default.VisibilityOff else Icons.Default.Visibility, if (visible) "Скрыть пароль" else "Показать пароль") }
        })
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SettingActionDialog(action: SettingAction, state: ServerSettingsState, viewModel: ServerSettingsViewModel) {
    AlertDialog(onDismissRequest = viewModel::closeAction, title = { Text(action.decision?.title ?: action.title) },
        text = { Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            if (action.decision == null && action.hint.isNotBlank()) Text(action.hint)
            action.decision?.let { decision ->
                Text(decision.explanation)
                decision.rules.forEachIndexed { index, rule ->
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(checked = index in action.selectedRules, enabled = !state.busy, onCheckedChange = { viewModel.selectRule(index, it) })
                        Text(firewallRuleLabel(rule), style = MaterialTheme.typography.bodySmall)
                    }
                }
                if (decision.omitted.isNotEmpty()) Text("Не будут перенесены:\n" + decision.omitted.joinToString("\n"), style = MaterialTheme.typography.bodySmall)
            }
            val suffix = action.operation.path.substringAfter("quick-setup/")
            val hidden = when (suffix) {
                "packages/install" -> setOf("packages")
                "fail2ban/settings" -> if ("ssh_jail_enabled" in action.body) setOf("ban_time", "find_time", "max_retry") else setOf("ssh_jail_enabled")
                "firewall/install", "firewall/switch", "firewall/enable", "firewall/remove", "firewall/nftables/chain", "fail2ban/configuration/content" -> action.operation.body?.properties()?.keys.orEmpty()
                else -> if (action.error == null) setOf("acknowledge_firewall_conflict") else emptySet()
            } + setOf("continuation", "selected_rules", "fingerprint") + if (action.needsRootPassword) emptySet() else setOf("root_password")
            if (suffix == "packages/install") Text((action.body["packages"] as? JsonArray).orEmpty().joinToString { it.jsonPrimitive.content })
            val switchAuth = action.authMode
            if (suffix == "ssh/users/switch") {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    listOf("password" to "Пароль", "key" to "SSH-ключ").forEach { (value, label) ->
                        RadioButton(selected = switchAuth == value, enabled = !state.busy, onClick = { viewModel.switchAuth(value) })
                        Text(label)
                    }
                }
            }
            action.operation.body?.properties()?.filterKeys { action.decision == null && it !in hidden && !(suffix == "ssh/users/switch" && it == "key_path" && switchAuth == "password") }?.forEach { (key, schema) ->
                val titles = mapOf("ban_time" to "Время блокировки", "find_time" to "Период попыток", "max_retry" to "Попыток до блокировки", "sudo" to "Разрешить sudo", "enabled" to "Разрешить вход", "remove_config" to "Удалить конфигурацию", "ssh_jail_enabled" to "Защищать SSH")
                val field = JsonObject(schema + ("nullable" to JsonPrimitive(false)) + ("title" to JsonPrimitive(titles[key] ?: schema.text("title") ?: key)))
                if (schema.flag("secret")) SecretSetting(action.body.text(key).orEmpty(), !state.busy, if (suffix == "ssh/users/switch" && switchAuth == "key") "Пароль для sudo" else schema.text("title") ?: "Пароль", "") { value -> viewModel.actionField(key, value.takeIf(String::isNotEmpty)?.let(::JsonPrimitive)) }
                else when {
                    key == "key_path" -> SettingsChoice("SSH-ключ", action.body.text(key).orEmpty(), state.keys, !state.busy) { viewModel.actionField(key, JsonPrimitive(it)) }
                    schema.text("type") == "boolean" -> SettingsSwitch(field.text("title").orEmpty(), "", action.body.flag(key), !state.busy) { viewModel.actionField(key, JsonPrimitive(it)) }
                    schema["enum"] is JsonArray -> {
                        val labels = mapOf("tcp" to "TCP", "udp" to "UDP", "any" to "TCP и UDP")
                        SettingsChoice(field.text("title").orEmpty(), action.body.text(key).orEmpty(), (schema["enum"] as JsonArray).map { it.jsonPrimitive.content.let { v -> v to (labels[v] ?: v) } }, !state.busy) { viewModel.actionField(key, JsonPrimitive(it)) }
                    }
                    else -> PanelTextField(action.body.text(key).orEmpty(), { value ->
                        val next = if (schema.text("type") == "integer") value.toIntOrNull()?.let(::JsonPrimitive) ?: JsonPrimitive(value) else JsonPrimitive(value)
                        viewModel.actionField(key, if (value.isBlank() && key !in action.operation.body!!.required()) null else next)
                    }, label = { Text(field.text("title").orEmpty()) }, singleLine = !schema.flag("multiline"), minLines = if (schema.flag("multiline")) 3 else 1, maxLines = if (schema.flag("multiline")) 6 else 1, enabled = !state.busy, modifier = Modifier.fillMaxWidth(), keyboardOptions = KeyboardOptions(keyboardType = if (schema.text("type") == "integer") KeyboardType.Number else KeyboardType.Text))
                }
            }
            action.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        } }, confirmButton = { TextButton(onClick = viewModel::submitAction, enabled = !state.busy && !action.retryBlocked) {
            if (state.busy) { CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp); Spacer(Modifier.width(8.dp)) }
            Text(if (action.decision != null) "Продолжить" else action.verb)
        } }, dismissButton = { TextButton(onClick = viewModel::closeAction, enabled = !state.busy) { Text("Отмена") } })
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SettingListSheet(list: SettingList, state: ServerSettingsState, viewModel: ServerSettingsViewModel) {
    ModalBottomSheet(onDismissRequest = viewModel::closeList) {
        Column(Modifier.fillMaxWidth().padding(horizontal = 20.dp).padding(bottom = 24.dp)) {
            Text(list.title, style = MaterialTheme.typography.titleLarge, modifier = Modifier.padding(bottom = 16.dp))
            if (list.loading) CircularProgressIndicator(Modifier.size(24.dp))
            list.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            LazyColumn(Modifier.heightIn(max = 440.dp)) {
                if (!list.loading && list.error == null && list.rows.isEmpty()) item { Text("Список пуст", Modifier.padding(vertical = 16.dp), color = MaterialTheme.colorScheme.onSurfaceVariant) }
                items(list.rows) { row ->
                    val name = row.text("username") ?: row.text("ip") ?: row.text("name") ?: row.text("filename") ?: row.text("type") ?: row.text("port") ?: "Правило"
                    Column(Modifier.fillMaxWidth().padding(vertical = 12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Text(name, style = MaterialTheme.typography.titleSmall)
                        val labels = mapOf("jail" to "Правило", "protocol" to "Протокол", "proto" to "Протокол", "action" to "Действие", "source" to "Источник", "backend" to "Сетевой экран", "sudo" to "Sudo", "fingerprint" to "Отпечаток", "filename" to "Файл", "port" to "Порт")
                        labels.forEach { (key, title) -> row.text(key)?.takeIf { it != name }?.let { Text("$title: ${if (it == "true") "Да" else if (it == "false") "Нет" else it}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) } }
                        if (list.suffix == "ssh/users") {
                            Text(if (row.flag("current")) "Текущее подключение" else if (!row.flag("login_capable")) "Вход по SSH отключён" else if (row.flag("sudo_capable")) "Администратор" else "Обычный пользователь", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        if (list.suffix == "ssh/users") Row {
                            TextButton(enabled = state.sshReady && row.flag("login_capable") && !row.flag("current"), onClick = { viewModel.closeList(); viewModel.action("ssh/users/switch", "Переключить пользователя", "Введите пароль или выберите ключ этого пользователя.", "Переключить", buildJsonObject { put("username", name) }) }) { Text("Подключиться") }
                            TextButton(enabled = state.sshReady, onClick = { viewModel.list("ssh/users/{username}/keys", "Ключи: $name", buildJsonObject { put("username", name) }) }) { Text("Ключи") }
                        }
                        if (list.suffix == "fail2ban/banned" && row.text("jail") != null) TextButton(onClick = { viewModel.closeList(); viewModel.action("fail2ban/unban", "Снять блокировку", verb = "Разблокировать", values = buildJsonObject { put("jail", row.text("jail")!!); put("ip", name) }) }) { Text("Разблокировать") }
                        if (list.suffix == "fail2ban/whitelist" && row.flag("managed")) TextButton(onClick = { viewModel.action("fail2ban/whitelist", "Удалить исключение?", name, "Удалить", buildJsonObject { put("ip", name) }, method = "DELETE") }) { Text("Удалить исключение") }
                        if (list.suffix == "fail2ban/jails" && row.flag("toggleable")) TextButton(onClick = { viewModel.action("fail2ban/jails/{jail}/enabled", "Изменить правило?", name, values = buildJsonObject { put("enabled", !row.flag("enabled")) }, fields = buildJsonObject { put("jail", name) }) }) { Text(if (row.flag("enabled")) "Выключить" else "Включить") }
                        if (list.suffix.endsWith("/keys") && row.text("fingerprint") != null) {
                            val fingerprint = row.text("fingerprint")!!
                            if (row.flag("route_uses_key")) Text("Используется для подключения", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.primary)
                            Row {
                                if (list.data.flag("is_current_user") && row.flag("local_match") && !row.flag("route_uses_key")) TextButton(onClick = { viewModel.action("ssh/users/{username}/keys/select", "Выбрать ключ?", fingerprint, "Выбрать", buildJsonObject { put("fingerprint", fingerprint) }, fields = list.fields) }) { Text("Выбрать") }
                                TextButton(onClick = { viewModel.action("ssh/users/{username}/keys", "Удалить ключ?", "${list.fields.text("username")} · $fingerprint", "Удалить", buildJsonObject { put("fingerprint", fingerprint) }, method = "DELETE", fields = list.fields) }) { Text("Удалить", color = MaterialTheme.colorScheme.error) }
                            }
                        }
                        if (list.suffix == "fail2ban/configuration") Row {
                            TextButton(onClick = { viewModel.editor(row.text("kind") ?: "jail", name) }) { Text("Открыть") }
                            if (!row.flag("standard")) TextButton(onClick = { viewModel.action("fail2ban/configuration/content", "Удалить файл?", name, "Удалить", buildJsonObject { put("kind", row.text("kind") ?: "jail"); put("filename", name) }, method = "DELETE") }) { Text("Удалить", color = MaterialTheme.colorScheme.error) }
                        }
                        if (list.suffix == "ssh/users" && state.canAdmin && name != "root") {
                            TextButton(onClick = { viewModel.action("ssh/users/{username}/sudo", if (row.flag("sudo_capable")) "Отозвать права sudo?" else "Разрешить sudo?", name,
                                method = if (row.flag("sudo_capable")) "DELETE" else "POST", fields = buildJsonObject { put("username", name) }) }) { Text(if (row.flag("sudo_capable")) "Отозвать sudo" else "Разрешить sudo") }
                        }
                        if (list.suffix == "ssh/users" && (state.canAdmin || row.flag("current"))) TextButton(onClick = { viewModel.action("ssh/users/{username}/password", "Сменить пароль пользователя", name, "Изменить", fields = buildJsonObject { put("username", name) }) }) { Text("Сменить пароль") }
                        if (list.suffix == "ssh/users" && state.canAdmin && row.flag("can_delete")) TextButton(onClick = { viewModel.action("ssh/users/{username}", "Удалить пользователя?", name, "Удалить", method = "DELETE", fields = buildJsonObject { put("username", name) }) }) { Text("Удалить пользователя", color = MaterialTheme.colorScheme.error) }
                        HorizontalDivider()
                    }
                }
            }
            if (list.suffix.endsWith("/keys") && !list.loading && list.error == null) {
                TextButton(onClick = { viewModel.action("ssh/users/{username}/keys", "Создать SSH-ключ?", "Ключ будет создан в хранилище панели и добавлен пользователю ${list.fields.text("username")}.", "Создать", fields = list.fields) }) { Text("Создать ключ") }
                if (list.data.flag("is_current_user")) TextButton(onClick = { viewModel.action("ssh/key", "Добавить публичный ключ", "Публичный ключ будет добавлен текущему пользователю сервера.", "Добавить") }) { Text("Добавить готовый ключ") }
            }
            if (list.suffix == "fail2ban/configuration") TextButton(onClick = { viewModel.editor(create = true) }) { Text("Создать файл") }
            if (list.suffix == "fail2ban/whitelist") TextButton(onClick = { viewModel.closeList(); viewModel.action("fail2ban/whitelist", "Добавить исключение", "Этот IP-адрес Fail2ban не будет блокировать.", "Добавить") }) { Text("Добавить IP-адрес") }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SettingEditorSheet(file: SettingEditor, state: ServerSettingsState, viewModel: ServerSettingsViewModel) {
    var discardFile by remember { mutableStateOf(false) }
    fun close() { if (file.dirty && !state.busy) discardFile = true else viewModel.closeEditor() }
    if (discardFile) AlertDialog(onDismissRequest = { discardFile = false }, title = { Text("Отменить изменения файла?") },
        text = { Text("Несохранённый текст будет потерян.") }, confirmButton = { TextButton(onClick = { discardFile = false; viewModel.closeEditor() }) { Text("Отменить изменения") } },
        dismissButton = { TextButton(onClick = { discardFile = false }) { Text("Продолжить редактирование") } })
    ModalBottomSheet(onDismissRequest = ::close) {
        Column(Modifier.fillMaxWidth().imePadding().verticalScroll(rememberScrollState()).padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(if (file.create) "Новый файл конфигурации" else file.filename, style = MaterialTheme.typography.titleLarge)
            if (file.create) {
                SettingsChoice("Тип конфигурации", file.kind, listOf("jail" to "Правила защиты", "filter" to "Фильтры"), !state.busy) { value -> viewModel.editFile { it.copy(kind = value) } }
                PanelTextField(file.filename, { value -> viewModel.editFile { it.copy(filename = value) } }, label = { Text("Имя файла") }, placeholder = { Text("custom.local") }, singleLine = true, enabled = !state.busy, modifier = Modifier.fillMaxWidth())
            }
            if (file.standard) Text("Стандартный файл Fail2ban. Перед применением изменения будут проверены.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (file.loading) CircularProgressIndicator(Modifier.size(24.dp))
            if (!file.loading) PanelTextField(file.content, { value -> viewModel.editFile { it.copy(content = value) } }, enabled = !state.busy && (file.error == null || file.create), modifier = Modifier.fillMaxWidth(),
                minLines = 8, maxLines = 16, textStyle = LocalTextStyle.current.copy(fontFamily = FontFamily.Monospace), label = { Text("Содержимое") })
            file.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            PanelButton(enabled = !file.loading && !state.busy && file.dirty, onClick = viewModel::saveFile, modifier = Modifier.fillMaxWidth()) { Text("Сохранить файл") }
            TextButton(enabled = !state.busy, onClick = ::close) { Text("Закрыть") }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ServerSettingsPickerScreen(onBack: () -> Unit, onServer: (String) -> Unit, viewModel: ServersViewModel = hiltViewModel()) {
    val state by viewModel.uiState.collectAsState()
    PanelScaffold(topBar = { PanelTopBar(title = { Text("Настройки сервера") }, navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Назад") } }) }) { padding ->
        LazyColumn(Modifier.fillMaxSize().padding(padding), contentPadding = PaddingValues(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            item { PanelSearchField(state.search, viewModel::search, placeholder = "Найти сервер", modifier = Modifier.fillMaxWidth()) }
            if (state.isLoading) item { CircularProgressIndicator() }
            state.error?.let { item { Text(it, color = MaterialTheme.colorScheme.error); TextButton(onClick = viewModel::refresh) { Text("Повторить") } } }
            if (!state.isLoading && state.filtered.isEmpty()) item { Text("Серверы не найдены") }
            items(state.filtered, key = { it.id }) { server -> SettingsEntry(server.name ?: server.host ?: server.id, server.host.orEmpty(), Icons.Default.Dns) { onServer(server.id) } }
        }
    }
}
