package com.bot4vps.mobile.ui.control

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.bot4vps.mobile.data.api.*
import com.bot4vps.mobile.data.model.*
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import kotlinx.serialization.json.*
import android.net.Uri
import javax.inject.Inject
import com.bot4vps.mobile.data.local.PreferencesManager
import com.bot4vps.mobile.data.local.AppLockManager
import com.bot4vps.mobile.data.repository.AuthRepository
import com.bot4vps.mobile.data.repository.checkedObject
import kotlinx.serialization.encodeToString

data class NativeControlState(
    val contract: NativeContract? = null, val operation: NativeOperation? = null,
    val fields: Map<String, JsonElement> = emptyMap(), val body: JsonElement? = null,
    val uploads: Map<String, Upload> = emptyMap(), val choices: Map<String, List<Pair<String, String>>> = emptyMap(),
    val result: JsonElement? = null, val busy: Boolean = false, val loading: Boolean = true,
    val error: String? = null, val notice: String? = null, val preparedRestoreId: String? = null,
    val selectedView: String = "", val lockedFields: Set<String> = emptySet(), val restoreOperationId: String? = null, val prefillFailed: Boolean = false, val canPrevious: Boolean=false, val connection: PanelConnection? = null, val targetReady: Boolean = false, val connectionFinished: Boolean = false
)

@HiltViewModel
class NativeControlViewModel @Inject constructor(
    savedState: SavedStateHandle, private val contracts: ContractRepository, val client: NativePanelClient,
    private val workflow: NativeWorkflow, private val realtime: RealtimeHub, private val prefs: PreferencesManager, private val auth: AuthRepository, val appLock: AppLockManager
) : ViewModel() {
    private val _state = MutableStateFlow(NativeControlState())
    val state = _state.asStateFlow()
    private val operationId: String? = savedState["operationId"]
    private val initialView:String?=savedState["view"]
    val initialRecordId: String? = savedState.get<String>("recordId")?.takeIf { it.isNotBlank() }
    private val section: String? = savedState["section"]
    val serverId: String? = savedState.get<String>("serverId")?.takeIf { it.isNotBlank() }
    private var job: Job? = null
    private var choicesJob: Job? = null
    private var connectionPoll: Job? = null
    private var journalRevision = 0L
    private val cursors=mutableListOf<JsonElement?>()
    private var inheritedBodyKeys: Set<String> = emptySet()

    init { load() }
    private fun load() {
        viewModelScope.launch {
            try {
                val contract = contracts.load()
                val overview = mapOf("dashboard" to "/api/summary", "servers" to "/api/servers", "groups" to "/api/groups", "quick_setup" to "/api/servers/{server_id}/quick-setup", "docker" to "/api/services/docker/status", "wireguard" to "/api/services/wireguard/status", "xui" to "/api/services/3x-ui/status", "backups" to "/api/backups", "files" to "/api/files", "audit" to "/api/audit", "events" to "/api/events", "queues" to "/api/queues", "settings" to "/api/settings/web", "security" to "/api/masterkey/status", "telegram" to "/api/telegram/status", "update" to "/api/update/state")
                val availableViews=PanelWorkflows.views(section.orEmpty())
                val view = availableViews.find { it.id==initialView } ?: availableViews.firstOrNull()
                val id = operationId ?: view?.operation ?: overview[section]?.let { "GET $it" }
                require(id == null || PanelWorkflows.enabled(id)) { if (id?.substringAfter(' ')?.startsWith("/api/setup") == true) "Первичная настройка панели доступна в вебе. Привяжите телефон через работающую веб-панель." else "Резервные копии временно отключены в приложении" }
                val op = id?.let { operation -> contract.operations.find { it.id == operation } ?: error("Операция недоступна в этой версии") }
                val fields = op?.fields?.mapNotNull { field ->
                    val name = field.text("name")!!
                    (if (name == "server_id" && serverId != null) JsonPrimitive(serverId) else field["default"])?.let { name to it }
                }?.toMap().orEmpty()
                val handoff = workflow.take(operationId)
                val inheritedFields = handoff?.filterKeys { key -> (key != "server_id" || serverId == null) && op?.fields?.any { it.text("name") == key } == true }.orEmpty()
                val initialBody = op?.body?.let(NativeForm::initial) as? JsonObject
                val body = if (op?.id == "POST /api/servers") JsonObject(initialBody.orEmpty() + mapOf("test" to JsonPrimitive(false), "certificate_check" to JsonPrimitive(false))) else initialBody
                val inheritedBody = handoff?.filterKeys { key -> key in op?.body?.properties().orEmpty() }.orEmpty()
                inheritedBodyKeys = inheritedBody.keys
                _state.update { it.copy(selectedView = view?.id.orEmpty(), lockedFields = inheritedFields.keys.filter { key -> op?.fields?.any { it.text("name") == key && it.text("location") == "path" } == true }.toSet(), contract = contract, operation = op, fields = (if(op?.path == "/api/events") fields + ("limit" to JsonPrimitive(if (initialRecordId != null) 1000 else 200)) else fields) + view?.fields.orEmpty().mapValues { JsonPrimitive(it.value) } + inheritedFields, body = if (body != null) JsonObject(body + inheritedBody) else null, loading = true) }
                val stored=prefs.pendingConnection.first()
                val pending=stored?.let { runCatching { Json.decodeFromString<PanelConnection>(it) }.getOrNull() }
                if(pending != null && pending.operation==op?.id && prefs.baseUrl.first() in listOf(pending.original,pending.target)) {
                    _state.update { it.copy(connection=pending,loading=false) }
                    watchConnection(pending)
                    return@launch
                }
                loadChoices()
                prefill()
                _state.update { it.copy(loading = false) }
                if (op?.method == "GET" && (!op.download || op.path.contains("/qr/") || op.path.contains("/config/")) && op.fields.all { !it.flag("required") || _state.value.fields.containsKey(it.text("name")) }) execute()
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) { _state.update { it.copy(loading = false, prefillFailed=it.operation?.body != null, error = errorText(e)) } }
        }
    }

    private suspend fun loadChoices() {
        val op = _state.value.operation ?: return
        val needed=op.fields.mapNotNull { it.text("name") }.toSet() + op.body?.properties().orEmpty().keys
        val servers = if(needed.any { it in setOf("server_id","destination_server_id") }) runCatching { client.request("GET", "/api/servers") as? JsonObject }.getOrNull() else null
        val rows = (servers?.get("servers") as? JsonArray).orEmpty()
        val options = rows.mapNotNull { row -> (row as? JsonObject)?.let { obj -> obj.text("id")?.let { it to (obj.text("name") ?: obj.text("host") ?: it) } } }
        _state.update { it.copy(choices = it.choices + mapOf("server_id" to options, "destination_server_id" to options)) }
        val groups = if("group" in needed || op.path.startsWith("/api/groups")) runCatching { client.request("GET", "/api/groups") as? JsonObject }.getOrNull() else null
        val groupRows = (groups?.get("groups") as? JsonArray).orEmpty().mapNotNull { row ->
            val name = (row as? JsonObject)?.text("name") ?: (row as? JsonPrimitive)?.contentOrNull
            name?.let { it to it }
        }
        if (groupRows.isNotEmpty()) _state.update { it.copy(choices = it.choices + ("group" to groupRows)) }
        val selectedServer = (_state.value.fields["server_id"] as? JsonPrimitive)?.contentOrNull ?: serverId
        suspend fun options(path: String, keys: List<String>, idKeys: List<String>, target: String, query: Map<String,List<String>> = emptyMap()) {
            val result = runCatching { client.request("GET", path, query) }.getOrNull() ?: return
            val list = if (result is JsonArray) result else keys.firstNotNullOfOrNull { (result as? JsonObject)?.get(it) as? JsonArray } ?: return
            val choices = list.mapNotNull { row ->
                when (row) {
                    is JsonObject -> idKeys.firstNotNullOfOrNull { row.text(it) }?.let { id ->
                        id to (row.text("name") ?: row.text("filename") ?: row.text("label") ?: row.text("title") ?: row.text("created_at") ?: id)
                    }
                    is JsonPrimitive -> row.content to row.content
                    else -> null
                }
            }
            if (choices.isNotEmpty()) _state.update { it.copy(choices = it.choices + (target to choices)) }
        }
        if (op.path.startsWith("/api/backups")) {
            val query = selectedServer?.let { mapOf("server_id" to listOf(it)) }.orEmpty()
            options("/api/backups", listOf("catalog"), listOf("backup_id","id"), "backup_id", query)
            options("/api/backups", listOf("imported_archives"), listOf("entry_key","id"), "entry_key", query)
            options("/api/backups/operations", listOf("operations"), listOf("id","operation_id"), "operation_id", query)
        }
        if (op.path.startsWith("/api/tasks")) options("/api/tasks/history", listOf("tasks"), listOf("id"), "task_id")
        if (op.path.startsWith("/api/audit")) options("/api/audit", listOf("items","rows","records"), listOf("id"), "record_id")
        if(op.path == "/api/audit") {
            val facets=runCatching { client.request("GET", "/api/audit/facets") as? JsonObject }.getOrNull()
            if(facets!=null) {
                fun rows(key:String)= (facets[key] as? JsonArray).orEmpty().mapNotNull { it as? JsonObject }
                val choices=mapOf(
                    "actor" to rows("actors").mapNotNull { r -> r.text("type")?.let { type -> (type+r.text("id")?.let { ":$it" }.orEmpty()) to (r.text("label") ?: type) } },
                    "action" to rows("actions").mapNotNull { r -> r.text("code")?.let { it to (r.text("title") ?: it) } },
                    "result" to rows("results").mapNotNull { r -> r.text("value")?.let { it to (r.text("title") ?: it) } },
                    "server_id" to (rows("servers").mapNotNull { r -> r.text("id")?.let { it to (r.text("name") ?: it) } }+_state.value.choices["server_id"].orEmpty()).distinctBy { it.first })
                _state.update { it.copy(choices=it.choices+choices) }
            }
        }
        if (op.path.startsWith("/api/events")) options("/api/events", listOf("events"), listOf("id"), "event_id")
        if (op.path.startsWith("/api/groups/")) _state.update { it.copy(choices = it.choices + ("name" to groupRows)) }
        if (op.path.startsWith("/api/scripts/")) options("/api/scripts", listOf("scripts"), listOf("name"), "name")
        if (op.path.startsWith("/api/servers") || op.path.contains("/ssh/")) options("/api/keys", listOf("keys"), listOf("path"), "key_path")
        if (op.path.startsWith("/api/update")) options("/api/update/versions", listOf("versions"), listOf("version","name"), "version")
        if (op.path.startsWith("/api/services/") && selectedServer != null) {
            val sid = op.path.split('/').getOrNull(3).orEmpty()
            val base = "/api/services/$sid/${encodeSegment(selectedServer)}"
            if ("/stacks/" in op.path && !(op.method == "POST" && (op.path.endsWith("/file") || op.path.endsWith("/zip")))) options("$base/stacks", listOf("rows","stacks","projects","items"), listOf("name","stack"), "name")
            else if (sid == "docker" && "/logs/" in op.path) {
                val response = runCatching { client.request("GET", "$base/state") as? JsonObject }.getOrNull()
                val containers = (response?.get("state") as? JsonObject)?.objects("containers").orEmpty().mapNotNull { row -> row.text("name")?.let { it to it } }
                _state.update { it.copy(choices = it.choices + ("name" to containers)) }
            } else if ("/profiles/" in op.path || "/logs/" in op.path || "/config/" in op.path || "/qr/" in op.path) options("$base/profiles", listOf("profiles"), listOf("name","id"), "name")
        }
    }

    private suspend fun prefill() {
        val op = _state.value.operation ?: return
        val id = (_state.value.fields["server_id"] as? JsonPrimitive)?.contentOrNull ?: serverId
        val source = when {
            op.method == "PATCH" && op.path == "/api/servers/{server_id}" && id != null -> "/api/servers/${encodeSegment(id)}"
            op.method == "PUT" && op.path == "/api/backups/profiles/{server_id}" && id != null -> "/api/backups/profiles/${encodeSegment(id)}"
            op.path == "/api/auth/account" && op.method == "POST" -> "/api/auth/account"
            op.path == "/api/telegram/settings" -> "/api/telegram/status"
            op.path == "/api/files/write" -> "/api/files/read"
            op.method == "POST" && op.path.contains("/stacks/") && op.path.endsWith("/files") && (_state.value.body as? JsonObject)?.text("path") != null -> arguments().first + "/content"
            op.method in setOf("POST", "PUT") && (op.path.endsWith("/file") && _state.value.fields["name"] != null || op.path.endsWith("/configuration/content")) -> arguments().first
            op.path == "/api/backups/bot4vps-settings" -> "/api/backups"
            op.path.startsWith("/api/settings/") && op.method == "POST" && op.path.count { it == '/' } == 3 -> op.path
            else -> null
        } ?: return
        val response = client.request("GET", source, if (op.path == "/api/files/write") (_state.value.body as? JsonObject).orEmpty().filterKeys { it in setOf("root", "project", "name") }.mapValues { listOf(it.value.jsonPrimitive.content) } else if(op.method == "POST" && op.path.contains("/stacks/") && op.path.endsWith("/files")) arguments().second + (_state.value.body as? JsonObject).orEmpty().filterKeys { it in setOf("path","key") }.mapValues { listOf(it.value.jsonPrimitive.content) } else if (op.method in setOf("POST", "PUT") && (op.path.endsWith("/file") || op.path.endsWith("/configuration/content"))) arguments().second else emptyMap()) as? JsonObject ?: error("Не удалось прочитать текущие значения")
        val actual = when {
            op.path == "/api/backups/bot4vps-settings" -> buildJsonObject { put("settings", response["bot4vps"] ?: JsonObject(emptyMap())) }
            op.path.startsWith("/api/backups/profiles") -> buildJsonObject { put("profile", response["profile"] ?: response) }
            op.path.startsWith("/api/servers") && op.method == "PATCH" -> response["server"] as? JsonObject
            else -> if(response["text"] != null) JsonObject(response + ("content" to response["text"]!!)) else response
        }
        if (actual != null) {
            val allowed = op.body?.properties().orEmpty()
            val old = _state.value.body as? JsonObject ?: JsonObject(emptyMap())
            val filtered = actual.filter { (key, v) -> key in allowed && key !in inheritedBodyKeys && v != JsonNull && allowed[key]?.flag("secret") != true }
            _state.update { it.copy(body = JsonObject(old + filtered)) }
        }
    }

    fun field(name: String, value: JsonElement?) {
        if (_state.value.busy || _state.value.loading || _state.value.connection != null || name in _state.value.lockedFields || _state.value.restoreOperationId != null || name == "server_id" && serverId != null) return
        _state.update { it.copy(fields = it.fields.toMutableMap().apply { if (value == null) remove(name) else put(name, value) }, error = null, preparedRestoreId = null) }
        if (name == "server_id" && _state.value.operation?.method != "GET") {
            choicesJob?.cancel()
            _state.update { it.copy(result = null, body = it.operation?.body?.let(NativeForm::initial), loading = true) }
            choicesJob = viewModelScope.launch {
                try { loadChoices(); prefill() }
                finally { _state.update { it.copy(loading = false) } }
            }
        }
    }
    fun body(value: JsonElement?) { if (!_state.value.busy && !_state.value.loading && _state.value.connection == null && _state.value.restoreOperationId == null) _state.update { it.copy(body = value, error = null, preparedRestoreId = null) } }
    fun newServerField(name: String, value: JsonElement?) {
        val current = _state.value
        if (current.operation?.id != "POST /api/servers" || current.busy || current.loading) return
        body(updateServerCreateField(current.body as? JsonObject ?: JsonObject(emptyMap()), name, value))
        _state.update { it.copy(notice = null, result = null) }
    }
    fun selectUpload(name: String, uri: Uri) {
        if (_state.value.busy || _state.value.loading) return
        try { _state.update { it.copy(uploads = it.uploads + (name to client.upload(uri)), error = null) } }
        catch (e: Exception) { _state.update { it.copy(error = errorText(e)) } }
    }

    fun formSchema(): JsonObject? {
        val s=_state.value; val schema=s.operation?.body ?: return null
        val hidden=when {
            s.operation.path == "/api/files/write" -> setOf("root","project","name")
            s.operation.path.contains("/stacks/") && s.operation.path.endsWith("/files") -> setOf("key","path")
            else -> emptySet()
        }.filter { it in inheritedBodyKeys }.toSet()
        return JsonObject(schema+("properties" to JsonObject(schema.properties().mapValues { (key,value)-> if(key in hidden) JsonObject(value+("hidden" to JsonPrimitive(true))) else value })))
    }
    fun testNewServer() {
        val current = _state.value
        if(current.busy || current.loading) return
        val schema = current.contract?.operations?.find { it.id == "POST /api/servers/test-connection" }?.body ?: return
        val draft = current.body as? JsonObject ?: JsonObject(emptyMap())
        val body = JsonObject(draft.filterKeys { it in schema.properties() })
        if (body.text("host").isNullOrBlank()) { _state.update { it.copy(error = "Введите адрес подключения") }; return }
        NativeForm.validate(schema, body)?.let { error -> _state.update { it.copy(error = error) }; return }
        _state.update { it.copy(busy=true,error=null,notice=null) }
        viewModelScope.launch {
            try {
                val response=client.request("POST","/api/servers/test-connection",body=body) as? JsonObject
                if(response?.flag("ok") == true) _state.update { it.copy(notice="SSH-соединение работает") }
                else _state.update { it.copy(error=response?.text("message") ?: response?.text("error") ?: response?.text("detail") ?: "Подключение не подтверждено") }
            } catch(e: CancellationException) { throw e } catch(e: Exception) { _state.update { it.copy(error=errorText(e)) } } finally { _state.update { it.copy(busy=false) } }
        }
    }
    fun validate(): Boolean {
        val s = _state.value; val op = s.operation ?: return false
        for (f in op.fields) {
            val name = f.text("name")!!
            if (f.text("type") == "file") {
                if (f.flag("required") && name !in s.uploads) { _state.update { it.copy(error = "Выберите файл: ${f.text("title")}") }; return false }
            } else {
                val value = s.fields[name]
                if (f.flag("required") && (value == null || value is JsonPrimitive && value.content.isBlank())) {
                    _state.update { it.copy(error = "Заполните: ${f.text("title")}") }; return false
                }
                NativeForm.validate(f, value, f.text("title").orEmpty())?.let { error -> _state.update { it.copy(error = error) }; return false }
            }
        }
        op.body?.let { schema -> NativeForm.validate(schema, s.body)?.let { error -> _state.update { it.copy(error = error) }; return false } }
        return true
    }

    private fun arguments(): Triple<String, Map<String, List<String>>, Map<String, String>> {
        val s = _state.value; val op = s.operation!!; var path = op.path
        val query = mutableMapOf<String, List<String>>(); val form = mutableMapOf<String, String>()
        op.fields.forEach { f ->
            val name = f.text("name")!!; val value = s.fields[name] ?: return@forEach
            val values = if (value is JsonArray) value.map { it.jsonPrimitive.content } else listOf((value as? JsonPrimitive)?.content ?: value.toString())
            when (f.text("location")) {
                "path" -> path = path.replace("{$name}", encodeSegment(values.first()))
                "form" -> form[name] = values.first()
                else -> query[name] = values
            }
        }
        require(!path.contains('{')) { "Выберите объект операции" }
        return Triple(path, query, form)
    }

    fun selectView(view: PanelView) {
        if (_state.value.busy || _state.value.loading) return
        val op = _state.value.contract?.operations?.find { it.id == view.operation } ?: return
        if (op.method != "GET") { prepareNext(op.id); return }
        val fields = op.fields.mapNotNull { f -> val name = f.text("name")!!; (if(name == "server_id" && serverId != null) JsonPrimitive(serverId) else f["default"])?.let { name to it } }.toMap() + view.fields.mapValues { JsonPrimitive(it.value) }
        _state.update { it.copy(selectedView=view.id, operation=op, fields=fields, result=null, error=null) }
        execute()
    }
    fun changeFilter(name: String, value: JsonElement?) { field(name, value); if (!_state.value.loading) execute() }
    fun actor(value:String?) {
        field("actor_type",value?.substringBefore(':')?.let(::JsonPrimitive))
        field("actor_id",value?.takeIf { ':' in it }?.substringAfter(':')?.let(::JsonPrimitive))
    }
    fun applyFilters() { cursors.clear(); field("cursor",null); _state.update { it.copy(canPrevious=false) }; execute() }
    fun nextPage() {
        if(_state.value.busy) return
        val cursor = (_state.value.result as? JsonObject)?.text("next_cursor") ?: return
        cursors.add(_state.value.fields["cursor"])
        field("cursor",JsonPrimitive(cursor)); _state.update { it.copy(canPrevious=true) }; execute()
    }
    fun previousPage() {
        if(_state.value.busy || cursors.isEmpty()) return
        field("cursor",cursors.removeAt(cursors.lastIndex)); _state.update { it.copy(canPrevious=cursors.isNotEmpty()) }; execute()
    }
    fun retryPrefill() {
        if(_state.value.busy || _state.value.loading) return
        _state.update { it.copy(loading=true,error=null) }
        viewModelScope.launch {
            try { prefill(); _state.update { it.copy(prefillFailed=false) } }
            catch(e: CancellationException) { throw e }
            catch(e: Exception) { _state.update { it.copy(error=errorText(e)) } }
            finally { _state.update { it.copy(loading=false) } }
        }
    }
    fun execute(destination: Uri? = null) {
        if (_state.value.busy || _state.value.loading || _state.value.connection != null || _state.value.prefillFailed || !validate()) return
        if (_state.value.restoreOperationId != null && _state.value.preparedRestoreId == null) {
            job = viewModelScope.launch {
                _state.update { it.copy(busy=true, error=null) }
                try { val id = waitForRestore(_state.value.result ?: JsonNull, arguments().second); _state.update { it.copy(preparedRestoreId=id) } }
                catch (e: CancellationException) { throw e }
                catch (e: Exception) { _state.update { it.copy(error=errorText(e)) } }
                finally { _state.update { it.copy(busy=false) } }
            }
            return
        }
        job = viewModelScope.launch {
            _state.update { it.copy(busy = true, error = null, notice = null, preparedRestoreId = null) }
            try {
                val s = _state.value; val op = s.operation!!; val (path, query, form) = arguments()
                if (destination != null) {
                    client.download(op.method, path, query, s.body, destination)
                    _state.update { it.copy(busy = false, notice = "Файл сохранён") }
                } else {
                    if(connectionOperation(op.id)) {
                        val base=prefs.baseUrl.first() ?: error("Адрес панели не задан")
                        val previous=client.request("GET",connectionStatusPath(op.id)) as? JsonObject
                        val pending=PanelConnection(op.id,base,connectionTarget(base,op.id,s.body as? JsonObject ?: JsonObject(emptyMap()), auth.isPairedApiAddress(base)),System.currentTimeMillis(),previous?.text("started_at"))
                        prefs.rememberConnection(Json.encodeToString(pending))
                        _state.update { it.copy(connection=pending) }
                        try {
                            val accepted=client.request(op.method,path,query,s.body,form,s.uploads) as? JsonObject
                            if(accepted?.containsKey("ok")==true && !accepted.flag("ok")) throw ApiError(400,accepted.text("error") ?: "Изменение подключения не принято")
                        }
                        catch(e: ApiError) { if(e.status !in setOf(408,502,503,504)) { prefs.rememberConnection(null); _state.update { it.copy(connection=null) }; throw e } }
                        catch(e: CancellationException) { throw e }
                        catch(_: java.io.IOException) { }
                        _state.update { it.copy(busy=false,notice="Панель перезапускается. Проверяем состояние и новый адрес") }
                        watchConnection(pending)
                        return@launch
                    }
                    val body = if (op.id == "POST /api/servers") serverCreatePayload(s.body as? JsonObject ?: JsonObject(emptyMap())) else s.body
                    val result = client.request(op.method, path, query, body, form, s.uploads)
                    _state.update { it.copy(result = result) }
                    val failure = (result as? JsonObject)?.let { obj -> (obj["ok"] as? JsonPrimitive)?.booleanOrNull == false || (obj["success"] as? JsonPrimitive)?.booleanOrNull == false }
                    if (failure == true) throw ApiError(400, (result as? JsonObject)?.text("error") ?: (result as? JsonObject)?.text("detail") ?: "Операция не выполнена")
                    val prepared = if (op.body?.text("model") == "RestoreBody") waitForRestore(result, query) else null
                    val queued = (result as? JsonObject)?.let { it["operation"] != null || it["task"] != null } == true
                    _state.update { it.copy(busy = false, preparedRestoreId = prepared,
                        notice = if (op.method == "GET") null else if (prepared != null) "План подготовлен. Проверьте результат перед восстановлением." else if (queued) "Операция поставлена в очередь." else "Операция выполнена") }
                }
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) { _state.update { it.copy(busy = false, error = errorText(e)) } }
        }
    }

    fun consumeNotice() { _state.update { it.copy(notice = null) } }
    fun clearEvents() {
        val s = _state.value
        if (section != "events" || s.operation?.id != "GET /api/events" || s.busy || s.loading) return
        job?.cancel()
        journalRevision++
        _state.update { it.copy(busy = true, error = null, notice = null) }
        job = viewModelScope.launch {
            try {
                client.checkedObject("DELETE", "/api/events")
                _state.update { it.copy(result = buildJsonObject { put("events", JsonArray(emptyList())) }, notice = "Журнал событий очищен") }
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) { _state.update { it.copy(error = errorText(e)) } }
            finally { _state.update { it.copy(busy = false) } }
        }
    }

    private suspend fun waitForRestore(result: JsonElement, query: Map<String,List<String>>): String {
        var operation = (result as? JsonObject)?.get("operation") as? JsonObject ?: error("Панель не вернула операцию подготовки")
        val id = operation.text("operation_id") ?: operation.text("id") ?: error("Панель не вернула идентификатор подготовки")
        _state.update { it.copy(restoreOperationId = id, notice = "Подготовка плана восстановления…") }
        while (true) {
            currentCoroutineContext().ensureActive()
            when (operation.text("status")) {
                "failed", "cancelled" -> error(operation.text("error") ?: "Подготовка восстановления не завершена")
                "completed" -> {
                    require(operation.text("stage") == "prepared") { "Повторите подготовку плана восстановления" }
                    _state.update { it.copy(result = JsonObject(mapOf("operation" to operation))) }
                    return id
                }
            }
            delay(2000)
            val response = client.request("GET", "/api/backups/operations", query + ("limit" to listOf("200"))) as? JsonObject ?: error("Не удалось проверить подготовку")
            val rows = response["operations"] as? JsonArray ?: error("Не удалось проверить подготовку")
            operation = rows.firstNotNullOfOrNull { row -> (row as? JsonObject)?.takeIf { (it.text("operation_id") ?: it.text("id")) == id } } ?: error("Операция подготовки не найдена")
            _state.update { it.copy(result = JsonObject(mapOf("operation" to operation))) }
        }
    }

    fun applyRestore() {
        val s = _state.value; val id = s.preparedRestoreId ?: return
        if (s.busy) return
        job = viewModelScope.launch {
            _state.update { it.copy(busy = true, error = null) }
            try {
                val (path, query, _) = arguments()
                val payload = RestoreRequests.apply(id, (s.body as? JsonObject)?.get("password"), (s.body as? JsonObject)?.get("protective_backup") != JsonPrimitive(false))
                val result = client.request("POST", path, query, payload)
                if ((result as? JsonObject)?.flag("ok") == false) error(result.text("error") ?: "Не удалось запустить восстановление")
                _state.update { it.copy(busy = false, result = result, preparedRestoreId = null, restoreOperationId = null, notice = "Восстановление запущено. Следите за ним в операциях копирования.") }
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) { _state.update { it.copy(busy = false, error = errorText(e)) } }
        }
    }

    private fun watchConnection(pending: PanelConnection) {
        connectionPoll?.cancel()
        connectionPoll=viewModelScope.launch {
            while(true) {
                try {
                    val response=withTimeout(4000) { client.request("GET",connectionStatusPath(pending.operation),baseUrl=pending.original) } as? JsonObject
                    if(response?.text("started_at") != pending.previousState && response?.text("status") == "failed") {
                        val details=response["error"]
                        _state.update { it.copy(connection=null,connectionFinished=false,targetReady=false,notice=null,error=(details as? JsonObject)?.text("title") ?: (details as? JsonPrimitive)?.content ?: "Изменение подключения не удалось. Панель вернула прежние параметры") }
                        prefs.rememberConnection(null); return@launch
                    }
                    if(response?.text("started_at") != pending.previousState && response?.text("status") == "done") _state.update { it.copy(notice="Изменение завершено. Проверяем подключение",connectionFinished=true) }
                } catch(e: TimeoutCancellationException) { }
                catch(e: CancellationException) { throw e }
                catch(_: Exception) { }
                try {
                    val me=withTimeout(4000) { client.request("GET","/api/me",baseUrl=pending.target) } as? JsonObject
                    if(me?.containsKey("auth_enabled")==true && (pending.target != pending.original || _state.value.connectionFinished)) {
                        _state.update { it.copy(targetReady=true,notice="Панель отвечает по адресу ${pending.target}") }
                        return@launch
                    }
                } catch(e: TimeoutCancellationException) { }
                catch(e: CancellationException) { throw e }
                catch(e: javax.net.ssl.SSLHandshakeException) { _state.update { it.copy(error="Сертификат не принят Android. Установите доверенный сертификат на устройство и повторите подключение") } }
                catch(_: Exception) { }
                if(System.currentTimeMillis()-pending.started>120000) {
                    _state.update { it.copy(notice="Автоматическая проверка пока не завершена. Можно повторить её; запрос изменения повторно не отправляется") }; return@launch
                }
                delay(1800)
            }
        }
    }
    fun checkConnection() { _state.value.connection?.let { watchConnection(it) } }
    fun connectTarget(onLogin:()->Unit) {
        val pending=_state.value.connection ?: return
        viewModelScope.launch {
            try { auth.setBaseUrl(pending.target); prefs.rememberConnection(null); onLogin() }
            catch(e: CancellationException) { throw e }
            catch(e: Exception) { _state.update { it.copy(error=errorText(e)) } }
        }
    }

    fun cancelRequest() { job?.cancel(); _state.update { it.copy(busy = false, notice = "Запрос отменён. Уже запущенная серверная операция может продолжаться.") } }

    fun prepareNext(destination: String) {
        val s = _state.value
        val result = s.result as? JsonObject ?: JsonObject(emptyMap())
        val extra = (result["server"] as? JsonObject).orEmpty() + (result["file"] as? JsonObject).orEmpty() + (result["data"] as? JsonObject).orEmpty()
        val textContent = result["text"]?.let { mapOf("content" to it) }.orEmpty()
        workflow.put(destination, JsonObject(s.fields + (s.body as? JsonObject).orEmpty() + result + extra + textContent))
    }

    fun related(): List<NativeOperation> {
        val s = _state.value; val op = s.operation ?: return emptyList()
        val expected = when {
            op.path.endsWith("/confirm") -> emptyList()
            op.path == "/api/auth/recover" || op.path.startsWith("/api/auth/recover/") -> listOf("/api/auth/recover/confirm", "/api/auth/recover/resend")
            op.path == "/api/auth/totp/setup" -> listOf("/api/auth/totp/enable")
            op.path.startsWith("/api/auth/disable") && (s.result as? JsonObject)?.text("channel") != null -> listOf("/api/auth/disable/confirm", "/api/auth/disable/resend")
            op.path == "/api/masterkey/view" || op.path == "/api/masterkey/view/resend" -> listOf("/api/masterkey/view/confirm", "/api/masterkey/view/resend")
            op.path.startsWith("/api/settings/backup-password/forgot") -> listOf("/api/settings/backup-password/forgot/confirm", "/api/settings/backup-password/forgot/resend")
            op.path == "/api/settings/web/tls/upload" -> listOf("/api/settings/web/tls/custom")
            op.path == "/api/files/read" -> listOf("/api/files/write")
            op.path.endsWith("/file") && op.method == "GET" -> listOf(op.path)
            op.path.endsWith("/configuration/content") && op.method == "GET" -> listOf(op.path)
            else -> emptyList()
        }
        return s.contract?.operations.orEmpty().filter { it.path in expected && it.id != op.id && it.method != "GET" && !(it.path.endsWith("/resend") && (s.result as? JsonObject)?.text("channel") == "totp") }
    }

    fun openRecord(record: JsonObject, collection: String, show: (JsonObject, String) -> Unit) {
        viewModelScope.launch {
            try {
                val id = record.text("id")
                val detail = when {
                    _state.value.operation?.path == "/api/audit" && id != null -> client.request("GET", "/api/audit/${encodeSegment(id)}") as? JsonObject ?: record
                    collection == "events" && id != null && !record.flag("read") -> {
                        client.request("POST", "/api/events/mark-read", body=buildJsonObject { put("event_id",id) })
                        JsonObject(record + ("read" to JsonPrimitive(true)))
                    }
                    else -> record
                }
                show(detail, collection)
            } catch(e: CancellationException) { throw e }
            catch(e: Exception) { _state.update { it.copy(error=errorText(e)) }; show(record,collection) }
        }
    }
    fun recordActions(record: JsonObject, collection: String): List<NativeOperation> {
        val s = _state.value
        val ids: List<String> = when {
            collection in setOf("catalog", "imported_archives") -> {
                val base = if(collection == "catalog") "/api/backups/{backup_id}" else "/api/backups/imported/{entry_key}"
                listOf("GET $base/preview", "POST $base/restore", "GET $base/download", "PATCH $base/filename", "DELETE $base")
            }
            collection == "operations" -> if(record.text("status") in setOf("queued","running","pending")) listOf("POST /api/backups/operations/{operation_id}/cancel") else emptyList()
            collection == "queues" -> buildList {
                if(record.flag("paused")) { add("POST /api/queues/{server_id}/continue"); add("POST /api/queues/{server_id}/retry") }
                if((record["queue"] as? JsonArray)?.isNotEmpty() == true) add("POST /api/queues/{server_id}/clear")
            }
            collection in setOf("tasks", "queue") -> buildList {
                add("GET /api/tasks/{task_id}")
                if(record.text("status") in setOf("running","queued","pending")) add("POST /api/tasks/{task_id}/cancel")
            }
            s.operation?.path?.endsWith("/ignored-stacks") == true -> listOf("DELETE /api/services/docker/{server_id}/ignored-stacks")
            s.operation?.path?.contains("/stacks/") == true && s.operation.path.endsWith("/files") -> buildList {
                add("POST /api/services/docker/{server_id}/stacks/{name}/files")
                if(!record.flag("is_compose")) add("DELETE /api/services/docker/{server_id}/stacks/{name}/files")
            }
            s.operation?.path == "/api/files" -> buildList {
                val keys=s.fields["root"] == JsonPrimitive("keys")
                if(keys) add("GET /api/keys/view") else if(record.flag("editable") && !record.flag("is_dir")) add("POST /api/files/write")
                if(!record.flag("is_dir")) add("GET /api/files/download")
                if(!record.flag("protected") && !record.flag("used")) add("DELETE /api/files")
            }
            else -> emptyList()
        }
        return ids.mapNotNull { id -> s.contract?.operations?.find { it.id == id } }
    }

    fun openDirectory(record: JsonObject): Boolean {
        val s = _state.value
        if (s.operation?.path != "/api/files" || !record.flag("is_dir") || s.busy || s.loading) return false
        val result = s.result as? JsonObject
        val next = if (result?.text("level") == "projects") {
            mapOf("project" to JsonPrimitive(record.text("name") ?: return false), "directory" to JsonPrimitive(""))
        } else mapOf("directory" to JsonPrimitive(record.text("path") ?: record.text("name") ?: return false))
        _state.update { it.copy(fields = it.fields + next, result = null) }
        execute()
        return true
    }

    fun parentDirectory() {
        val s = _state.value
        if (s.operation?.path != "/api/files" || s.busy || s.loading) return
        val directory = (s.fields["directory"] as? JsonPrimitive)?.contentOrNull.orEmpty()
        val next = if (directory.isNotEmpty()) mapOf("directory" to JsonPrimitive(directory.substringBeforeLast('/', "")))
        else mapOf("project" to JsonPrimitive(""))
        _state.update { it.copy(fields = it.fields + next, result = null) }
        execute()
    }

    fun recordNext(destination: String, record: JsonObject, collection: String) {
        val s = _state.value
        val id = record.text("id")
        val alias = when (collection) {
            "catalog" -> "backup_id"
            "imported_archives" -> "entry_key"
            "operations" -> "operation_id"
            "servers" -> "server_id"
            "events" -> "event_id"
            "tasks", "queue" -> "task_id"
            else -> if (s.operation?.section == "audit") "record_id" else "id"
        }
        val recordFields = record.toMutableMap()
        if (id != null) recordFields.putIfAbsent(alias, JsonPrimitive(id))
        if(s.operation?.path?.endsWith("/ignored-stacks") == true) record.text("key")?.let { recordFields.putIfAbsent("ignore_key",JsonPrimitive(it)) }
        if (record["operation_id"] != null) recordFields["operation_id"] = record["operation_id"]!!
        if (record["filename"] != null) recordFields.putIfAbsent("name", record["filename"]!!)
        if (s.operation?.path == "/api/files" && record.text("path") != null) recordFields["name"] = record["path"]!!
        if (s.operation?.path == "/api/keys") recordFields["root"] = JsonPrimitive("keys")
        val params = JsonObject(recordFields.filterKeys { it in setOf("name", "stack", "key", "image") } + (record.text("name")?.let { mapOf("stack" to JsonPrimitive(it)) }).orEmpty())
        workflow.put(destination, JsonObject(s.fields + recordFields + ("params" to params)))
    }

    suspend fun observe() {
        if(_state.value.operation?.path == "/api/tasks/{task_id}") {
            while(true) { if(!_state.value.busy && !_state.value.loading) execute(); delay(2000) }
        }
        realtime.events.collect {
            val s = _state.value; val op = s.operation
            val revision = journalRevision
            val cacheOnly = op != null && op.method == "GET" && (op.path in setOf("/api/servers", "/api/summary", "/api/queues", "/api/events", "/api/audit", "/api/backups", "/api/backups/operations") || op.path.startsWith("/api/services/") && op.path.endsWith("/status"))
            if (cacheOnly && s.result != null && !s.busy) {
                try {
                    val (path,query,_) = arguments()
                    val result = client.request("GET",path,query)
                    _state.update { if (it.fields == s.fields && !it.busy && journalRevision == revision) it.copy(result = result) else it }
                } catch (e: CancellationException) { throw e }
                catch (e: Exception) { _state.update { if (!it.busy && journalRevision == revision) it.copy(error = errorText(e)) else it } }
                delay(2500)
            }
        }
    }
}
