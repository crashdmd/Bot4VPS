package com.bot4vps.mobile.ui.servers

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.bot4vps.mobile.data.api.*
import com.bot4vps.mobile.data.model.*
import com.bot4vps.mobile.data.repository.checkedObject
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import kotlinx.serialization.json.*
import javax.inject.Inject

enum class ServerSettingPage(val title: String) {
    HOME("Настройки сервера"), GENERAL("Основное"), CONNECTION("Подключение"), SYSTEM("Система"),
    SSH("Доступ по SSH"), FIREWALL("Сетевой экран"), FAIL2BAN("Защита от перебора"), PACKAGES("Пакеты")
}
data class SettingAction(val operation: NativeOperation, val title: String, val hint: String, val verb: String,
    val body: JsonObject = JsonObject(emptyMap()), val error: String? = null,
    val decision: ServerFirewallDecision? = null, val selectedRules: Set<Int> = emptySet(), val retryBlocked: Boolean = false, val showDialog: Boolean = true, val authMode: String = "password", val pathFields: JsonObject = JsonObject(emptyMap()), val needsRootPassword: Boolean = false)
data class SettingList(val suffix: String, val title: String, val rows: List<JsonObject> = emptyList(),
    val loading: Boolean = true, val error: String? = null, val fields: JsonObject = JsonObject(emptyMap()), val data: JsonObject = JsonObject(emptyMap()))
data class SettingEditor(val kind: String, val filename: String, val content: String = "", val original: String = "",
    val create: Boolean = false, val loading: Boolean = false, val error: String? = null) {
    val dirty get() = content != original || create && filename.isNotBlank()
    val standard get() = kind == "jail" && filename in setOf("jail.conf", "jail.local")
}
data class ServerSettingsState(
    val server: JsonObject? = null, val overview: JsonObject? = null, val draft: ServerSettingsDraft = ServerSettingsDraft(),
    val page: ServerSettingPage = ServerSettingPage.HOME, val groups: List<Pair<String, String>> = emptyList(),
    val keys: List<Pair<String, String>> = emptyList(), val keysError: String? = null, val error: String? = null,
    val refreshing: Boolean = true, val busy: Boolean = false, val saving: Boolean = false, val notice: String? = null,
    val action: SettingAction? = null, val list: SettingList? = null, val editor: SettingEditor? = null, val output: String? = null, val selectedPackages: Set<String> = emptySet()
) {
    val generalDirty get() = server?.let { draft.generalPatch(it).isNotEmpty() } == true
    val connectionDirty get() = server?.let { draft.connectionPatch(it).isNotEmpty() } == true ||
        server != null && draft.port != (server.text("port") ?: "22")
    val dirty get() = generalDirty || connectionDirty
    fun section(key: String) = overview?.get(key) as? JsonObject ?: JsonObject(emptyMap())
    val canAdmin get() = section("ssh_access").flag("sudo_capable")
    val sshReady get() = section("diagnostics").flag("ssh_ok")
}

@HiltViewModel
class ServerSettingsViewModel @Inject constructor(saved: SavedStateHandle, private val panel: NativePanelClient,
    private val contracts: ContractRepository) : ViewModel() {
    private val serverId: String = checkNotNull(saved["serverId"])
    private val base = "/api/servers/${encodeSegment(serverId)}"
    private val setup = "$base/quick-setup"
    private val _ui = MutableStateFlow(ServerSettingsState(page = if (saved.get<String>("page") == "connection") ServerSettingPage.CONNECTION else ServerSettingPage.HOME))
    val ui = _ui.asStateFlow()
    private var request: Job? = null
    private var listRequest: Job? = null
    init { refresh() }

    fun page(value: ServerSettingPage) { if (!_ui.value.busy) _ui.update { it.copy(page = value) } }
    fun edit(change: (ServerSettingsDraft) -> ServerSettingsDraft) { if (!_ui.value.busy) _ui.update { it.copy(draft = change(it.draft)) } }
    fun resetGeneral() { _ui.update { old -> old.server?.let { val fresh = ServerSettingsDraft.from(it); old.copy(draft = old.draft.copy(name = fresh.name, group = fresh.group, sslEnabled = fresh.sslEnabled, sslHost = fresh.sslHost)) } ?: old } }
    fun resetConnection() { _ui.update { old -> old.server?.let { val fresh = ServerSettingsDraft.from(it); old.copy(draft = old.draft.copy(host = fresh.host, port = fresh.port, user = fresh.user, authType = fresh.authType, keyPath = fresh.keyPath, password = "")) } ?: old } }
    fun clearNotice() { _ui.update { it.copy(notice = null) } }
    fun closeOutput() { _ui.update { it.copy(output = null) } }

    /** Settings do not subscribe to SSE: entering text must never trigger a reload. */
    fun refresh() {
        if (request?.isActive == true || _ui.value.busy) return
        request = viewModelScope.launch {
            _ui.update { it.copy(refreshing = true) }
            try {
                val server = panel.checkedObject("GET", base)["server"] as? JsonObject ?: error("Нет данных сервера")
                _ui.update { old ->
                    val fresh = ServerSettingsDraft.from(server)
                    val draft = fresh.copy(
                        name = if (old.generalDirty) old.draft.name else fresh.name,
                        group = if (old.generalDirty) old.draft.group else fresh.group,
                        sslEnabled = if (old.generalDirty) old.draft.sslEnabled else fresh.sslEnabled,
                        sslHost = if (old.generalDirty) old.draft.sslHost else fresh.sslHost,
                        host = if (old.connectionDirty) old.draft.host else fresh.host,
                        port = if (old.connectionDirty) old.draft.port else fresh.port,
                        user = if (old.connectionDirty) old.draft.user else fresh.user,
                        authType = if (old.connectionDirty) old.draft.authType else fresh.authType,
                        keyPath = if (old.connectionDirty) old.draft.keyPath else fresh.keyPath,
                        password = old.draft.password
                    )
                    old.copy(server = server, draft = draft)
                }
                supervisorScope {
                    launch {
                        try {
                            val data = panel.checkedObject("GET", setup, query = mapOf("updates" to listOf("false")))
                            _ui.update { old ->
                                // An overview without update checking contains an empty system status.
                                val system = old.overview?.get("system")
                                old.copy(overview = if (system != null && (system as? JsonObject)?.text("last_check") != null) JsonObject(data + ("system" to system)) else data, error = null)
                            }
                        } catch (e: CancellationException) { throw e }
                        catch (e: Exception) { _ui.update { it.copy(error = errorText(e)) } }
                    }
                    launch {
                        try {
                            val groups = panel.checkedObject("GET", "/api/groups").objects("groups").mapNotNull { row -> row.text("name")?.let { it to it } }
                            _ui.update { it.copy(groups = groups) }
                        } catch (e: CancellationException) { throw e }
                        catch (_: Exception) { /* The current group remains selectable. */ }
                    }
                    launch {
                        try {
                            val keys = panel.checkedObject("GET", "/api/keys").objects("keys").mapNotNull { row -> row.text("path")?.let { it to (row.text("name") ?: it.substringAfterLast('/')) } }
                            _ui.update { it.copy(keys = keys, keysError = null) }
                        } catch (e: CancellationException) { throw e }
                        catch (e: Exception) { _ui.update { it.copy(keysError = errorText(e)) } }
                    }
                }
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) { _ui.update { it.copy(error = errorText(e)) } }
            finally { _ui.update { it.copy(refreshing = false) } }
        }
    }
    fun saveGeneral() = save(false)
    fun saveConnection() = save(true)
    private fun save(connection: Boolean) {
        val state = _ui.value
        if (state.busy || state.refreshing) return
        val saved = state.server ?: return
        val error = if (connection) state.draft.connectionError() else state.draft.generalError()
        if (error != null) { _ui.update { it.copy(notice = error) }; return }
        val patch = if (connection) state.draft.connectionPatch(saved) else state.draft.generalPatch(saved)
        if (patch.isEmpty()) return
        viewModelScope.launch {
            _ui.update { it.copy(busy = true, saving = true) }
            try {
                val result = panel.checkedObject("PATCH", base, body = patch)
                val server = result["server"] as? JsonObject ?: JsonObject(saved + patch.filterKeys { it != "password" })
                _ui.update { old -> old.copy(server = server, draft = old.draft.copy(password = if (connection) "" else old.draft.password), notice = "Изменения сохранены") }
                if (connection) resetConnection() else resetGeneral()
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) { _ui.update { it.copy(notice = errorText(e)) } }
            finally { _ui.update { it.copy(busy = false, saving = false) } }
        }
    }
    fun testConnection() {
        val state = _ui.value
        if (state.busy || state.refreshing) return
        state.draft.connectionError()?.let { error -> _ui.update { it.copy(notice = error) }; return }
        val d = state.draft
        val body = buildJsonObject {
            put("host", d.host.trim()); put("port", d.port.toInt()); put("user", d.user.trim()); put("auth_type", d.authType)
            if (d.password.isNotEmpty()) put("password", d.password)
            if (d.authType == "key") put("key_path", d.keyPath)
        }
        viewModelScope.launch {
            _ui.update { it.copy(busy = true) }
            try {
                val result = panel.request("POST", "$base/test-draft", body = body) as? JsonObject ?: error("Неожиданный ответ")
                _ui.update { it.copy(notice = if (result.flag("ok")) "Подключение работает" else result.text("message") ?: result.text("detail") ?: result.text("error") ?: "Подключение не удалось") }
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) { _ui.update { it.copy(notice = errorText(e)) } }
            finally { _ui.update { it.copy(busy = false) } }
        }
    }
    fun action(suffix: String, title: String, hint: String = "", verb: String = "Применить", values: JsonObject = JsonObject(emptyMap()), showDialog: Boolean = true, method: String = "POST", fields: JsonObject = JsonObject(emptyMap())) {
        if (_ui.value.busy || _ui.value.refreshing) return
        viewModelScope.launch {
            val op = contracts.load().operations.find { it.id == "$method /api/servers/{server_id}/quick-setup/$suffix" } ?: return@launch
            val initial = op.body?.let(NativeForm::initial) as? JsonObject ?: JsonObject(emptyMap())
            _ui.update { it.copy(action = SettingAction(op, title, hint, verb, JsonObject(initial + values), showDialog = showDialog, authMode = if (it.section("ssh_access").text("password_auth")?.contains("запрещ", true) == true) "key" else "password", pathFields = fields, needsRootPassword = it.list?.data?.flag("is_root") == true && it.list?.data?.flag("is_current_root") != true)) }
            if (!showDialog) submitAction()
        }
    }
    fun actionField(key: String, value: JsonElement?) { if (!_ui.value.busy) _ui.update { old -> old.copy(action = old.action?.let { it.copy(body = JsonObject(it.body.toMutableMap().apply { if (value == null) remove(key) else put(key, value) }), error = null) }) } }
    fun switchAuth(value: String) { if (!_ui.value.busy) _ui.update { old -> old.copy(action = old.action?.let { it.copy(authMode = value, body = if (value == "password") JsonObject(it.body - "key_path") else it.body, error = null) }) } }
    fun closeAction() { if (!_ui.value.busy) _ui.update { it.copy(action = null) } }
    fun selectRule(index: Int, selected: Boolean) { if (!_ui.value.busy) _ui.update { old -> old.copy(action = old.action?.let { it.copy(selectedRules = if (selected) it.selectedRules + index else it.selectedRules - index) }) } }
    fun submitAction() {
        val state = _ui.value; val action = state.action ?: return
        if (state.busy || state.refreshing || action.retryBlocked) return
        val requestBody = action.decision?.body(action.body, action.selectedRules) ?: action.body
        val error = if (action.operation.path.endsWith("/ssh/users/switch") && action.authMode == "key" && requestBody.text("key_path").isNullOrBlank()) "Выберите SSH-ключ" else action.operation.body?.let { NativeForm.validate(it, requestBody) }
        if (error != null) { _ui.update { it.copy(action = action.copy(error = error)) }; return }
        viewModelScope.launch {
            _ui.update { it.copy(busy = true) }
            try {
                var path = action.operation.path.replace("{server_id}", encodeSegment(serverId))
                action.pathFields.forEach { (key, value) -> path = path.replace("{$key}", encodeSegment(value.jsonPrimitive.content)) }
                require(!path.contains('{')) { "Не выбран объект операции" }
                val result = panel.request(action.operation.method, path, body = requestBody.takeIf { action.operation.body != null }) as? JsonObject ?: error("Неожиданный ответ")
                if (!result.flag("ok")) {
                    val message = result.text("message")?.takeIf(String::isNotBlank) ?: result.text("error") ?: result.text("detail") ?: "Изменение не применено"
                    val decision = ServerFirewallDecision.from(result)
                    val data = result["data"] as? JsonObject
                    val rollback = data?.get("rollback") as? JsonObject
                    val blocked = data?.text("decision_required") == "skip_failed_rules" && rollback?.flag("verified") != true || data?.flag("changed") == true && (rollback?.flag("verified") != true) && (rollback != null || data?.text("phase") == "rollback")
                    _ui.update { old ->
                        old.copy(action = if (!action.showDialog) null else action.copy(error = if (decision == null) message else null,
                            decision = decision, selectedRules = decision?.rules?.indices?.toSet().orEmpty(), retryBlocked = blocked),
                            notice = if (!action.showDialog) message else old.notice)
                    }
                } else {
                    _ui.update { old ->
                        var overview = old.overview ?: JsonObject(emptyMap())
                        listOf("system", "diagnostics", "ssh_access", "firewall", "fail2ban", "packages").forEach { key -> if (result[key] is JsonObject) overview = JsonObject(overview + (key to result.getValue(key))) }
                        old.copy(action = null, list = null, editor = if (action.operation.path.endsWith("/configuration/content")) null else old.editor, overview = overview, selectedPackages = emptySet(),
                            notice = result.text("message")?.takeIf(String::isNotBlank) ?: "Готово", output = result.text("output")?.takeIf(String::isNotBlank))
                    }
                    _ui.update { it.copy(busy = false) }
                    refresh()
                }
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) { _ui.update { it.copy(action = if (action.showDialog) it.action?.copy(error = errorText(e)) else null, notice = if (!action.showDialog) errorText(e) else it.notice) } }
            finally { _ui.update { it.copy(busy = false) } }
        }
    }
    fun selectPackage(name: String, selected: Boolean) { if (!_ui.value.busy) _ui.update { it.copy(selectedPackages = if (selected) it.selectedPackages + name else it.selectedPackages - name) } }
    fun list(suffix: String, title: String, fields: JsonObject = JsonObject(emptyMap())) {
        if (_ui.value.busy) return
        listRequest?.cancel()
        _ui.update { it.copy(list = SettingList(suffix, title, fields = fields)) }
        listRequest = viewModelScope.launch {
            try {
                var path = "$setup/$suffix"
                fields.forEach { (key, value) -> path = path.replace("{$key}", encodeSegment(value.jsonPrimitive.content)) }
                val result = panel.request("GET", path) as? JsonObject ?: error("Неожиданный ответ")
                if (result["ok"] == JsonPrimitive(false)) error(result.text("message")?.takeIf(String::isNotBlank) ?: result.text("error") ?: "Не удалось получить список")
                val data = result["data"] as? JsonObject ?: result
                val rows = listOf("users", "bans", "entries", "jails", "rules", "keys", "filters", "files").firstNotNullOfOrNull { data[it] as? JsonArray }
                _ui.update { it.copy(list = SettingList(suffix, title, rows.orEmpty().mapNotNull { row -> row as? JsonObject ?: (row as? JsonPrimitive)?.let { buildJsonObject { put("name", it.content) } } }, loading = false, fields = fields, data = data)) }
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) { _ui.update { it.copy(list = it.list?.copy(loading = false, error = errorText(e))) } }
        }
    }
    fun editor(kind: String = "jail", filename: String = "", create: Boolean = false) {
        closeList()
        _ui.update { it.copy(editor = SettingEditor(kind, filename, create = create, loading = !create)) }
        if (create) return
        listRequest = viewModelScope.launch {
            try {
                val result = panel.request("GET", "$setup/fail2ban/configuration/content", query = mapOf("kind" to listOf(kind), "filename" to listOf(filename))) as? JsonObject ?: error("Неожиданный ответ")
                require(result.flag("ok")) { result.text("message") ?: result.text("error") ?: "Файл недоступен" }
                val data = result["data"] as? JsonObject ?: error("Нет содержимого файла")
                val content = data.text("content") ?: error("Нет содержимого файла")
                _ui.update { it.copy(editor = SettingEditor(kind, filename, content, content)) }
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) { _ui.update { it.copy(editor = it.editor?.copy(loading = false, error = errorText(e))) } }
        }
    }
    fun editFile(change: (SettingEditor) -> SettingEditor) { if (!_ui.value.busy) _ui.update { it.copy(editor = it.editor?.let { editor -> change(editor).copy(error = null) }) } }
    fun closeEditor() { if (!_ui.value.busy) { listRequest?.cancel(); _ui.update { it.copy(editor = null) } } }
    fun saveFile() {
        val file = _ui.value.editor ?: return
        if (file.loading || file.error != null || !file.dirty) return
        if (file.kind !in setOf("jail", "filter") || !Regex("^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\\.(?:conf|local)$").matches(file.filename)) {
            _ui.update { it.copy(editor = file.copy(error = "Укажите имя файла с расширением .conf или .local")) }; return
        }
        action("fail2ban/configuration/content", if (file.create) "Создать файл?" else "Сохранить конфигурацию?",
            "${file.kind} / ${file.filename}. Перед применением настройки будут проверены; при ошибке предыдущий файл восстанавливается.",
            "Сохранить", buildJsonObject { put("kind", file.kind); put("filename", file.filename); put("content", file.content); put("create_only", file.create) }, method = "PUT")
    }
    fun closeList() { listRequest?.cancel(); _ui.update { it.copy(list = null) } }
}
