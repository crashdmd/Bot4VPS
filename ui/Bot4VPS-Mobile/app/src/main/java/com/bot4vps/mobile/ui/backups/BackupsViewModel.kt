package com.bot4vps.mobile.ui.backups

import android.net.Uri
import androidx.lifecycle.*
import com.bot4vps.mobile.data.api.*
import com.bot4vps.mobile.data.model.*
import com.bot4vps.mobile.data.repository.checkedObject
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import kotlinx.serialization.json.*
import javax.inject.Inject

data class BackupsState(val serverId: String? = null, val data: JsonObject? = null, val settings: JsonObject? = null,
    val passwordStatus: JsonObject? = null, val loading: Boolean = false, val busy: Boolean = false,
    val page: String = "archives", val error: String? = null, val notice: String? = null,
    val archive: BackupArchive? = null, val preview: JsonObject? = null,
    val restore: BackupRestoreOptions = BackupRestoreOptions(), val requiresRoot: Boolean = false,
    val fullUnavailable: Boolean = false, val policy: String? = null, val readinessLoaded: Boolean = false, val needsInspection: Boolean = false,
    val nodes: List<JsonObject> = emptyList(), val parents: List<String> = emptyList(), val cursor: String? = null,
    val inventoryReady: Boolean = false, val operation: JsonObject? = null) {
    val servers get() = data?.objects("servers").orEmpty().mapNotNull { row -> row.text("id")?.let { it to (row.text("name") ?: it) } }
    val target get() = servers.find { it.first == serverId }?.second ?: if(serverId==null) "Панель Bot4VPS" else serverId
    val archives get() = data?.let { BackupArchive.list(it,serverId) }.orEmpty()
    val operations get() = data?.objects("operations").orEmpty().filter { row ->
        val target = row["target"] as? JsonObject
        if(serverId==null) target?.text("kind")=="bot4vps" else target?.text("server_id")==serverId
    }
    val configured get() = serverId==null || settings?.objects("sources")?.isNotEmpty()==true
}

@HiltViewModel
class BackupsViewModel @Inject constructor(private val saved: SavedStateHandle, private val panel: NativePanelClient) : ViewModel() {
    private val _state = MutableStateFlow(BackupsState(serverId=auditInitialServer(saved.get<String>("serverId"))))
    val state = _state.asStateFlow()
    private var request: Job? = null
    private var action: Job? = null
    private var watchedId: String? = null
    // Retain the request ID after an uncertain network result; retry must not
    // submit the same confirmed restore as a second independent operation.
    private var pendingApply: Pair<String,JsonObject>? = null
    private fun query(id: String?) = id?.let { mapOf("server_id" to listOf(it)) } ?: emptyMap()
    init { refresh() }
    fun select(id: String?) {
        if(_state.value.busy) return
        request?.cancel(); action?.cancel(); watchedId=null; pendingApply=null
        _state.value=BackupsState(serverId=id); refresh()
    }
    fun refresh() {
        if(_state.value.busy) return
        val current=_state.value
        if(current.page=="archive" && current.archive!=null) { open(current.archive); return }
        if(current.page=="restore" && !current.readinessLoaded) { restore(); return }
        request?.cancel(); request=viewModelScope.launch { load(true) }
    }
    private suspend fun load(show: Boolean) {
        val id=_state.value.serverId
        if(show) _state.update { it.copy(loading=true,error=null) }
        try {
            val (data,settings,password) = coroutineScope {
                val overview=async { panel.checkedObject("GET","/api/backups",query=query(id)) }
                val profile=if(id!=null) async { panel.checkedObject("GET","/api/backups/profiles/${encodeSegment(id)}")["profile"] as? JsonObject } else null
                val password=async { panel.checkedObject("GET","/api/settings/backup-password") }
                val data=overview.await()
                Triple(data,if(id==null) data["bot4vps"] as? JsonObject else profile?.await(),password.await())
            }
            _state.update { s -> if(s.serverId!=id) s else s.copy(data=data,settings=settings,passwordStatus=password,loading=false,
                operation=watchedId?.let { key -> data.objects("operations").find { backupOperationId(it)==key } } ?: s.operation) }
        } catch(e: CancellationException) { throw e }
        catch(e: Exception) { _state.update { it.copy(loading=false,error=errorText(e)) } }
    }
    suspend fun observe() {
        while(currentCoroutineContext().isActive) {
            delay(3000)
            if(!_state.value.busy && !_state.value.loading && (_state.value.operations.any(::backupOperationActive) || _state.value.operation?.let(::backupOperationActive)==true)) load(false)
        }
    }
    private fun run(block: suspend () -> Unit) {
        if(_state.value.busy) return
        action=viewModelScope.launch {
            _state.update { it.copy(busy=true,error=null,notice=null) }
            try { block() }
            catch(e: CancellationException) { throw e }
            catch(e: Exception) { _state.update { it.copy(error=errorText(e)) } }
            finally { _state.update { it.copy(busy=false) } }
        }
    }
    fun page(value: String) { if(!_state.value.busy) _state.update { it.copy(page=value,error=null) } }
    fun closeArchive() {
        if(_state.value.busy) return
        watchedId=null; pendingApply=null
        _state.update { it.copy(page="archives",archive=null,preview=null,restore=BackupRestoreOptions(),operation=null,nodes=emptyList(),readinessLoaded=false) }
    }
    fun open(archive: BackupArchive) = run {
        watchedId=null; pendingApply=null
        _state.update { it.copy(archive=archive,preview=null,page="archive",operation=null,restore=BackupRestoreOptions(),nodes=emptyList(),parents=emptyList(),inventoryReady=false,readinessLoaded=false) }
        val preview=panel.checkedObject("GET","${archive.base}/preview",query=archive.query)
        _state.update { it.copy(preview=preview,archive=archive.copy(row=JsonObject(archive.row+preview.filterKeys { key -> key in setOf("filename","format","bytes","display_created_at") }))) }
    }
    fun restore() = run {
        val a=_state.value.archive ?: return@run
        _state.update { it.copy(page="restore",readinessLoaded=false,requiresRoot=false,fullUnavailable=false,policy=null) }
        if(a.imported) {
            val data=panel.checkedObject("GET","${a.base}/restore/readiness",query=a.query)
            _state.update { it.copy(requiresRoot=data.flag("requires_target_root"),needsInspection=data.flag("encrypted") && data.flag("requires_target_root"),policy=(data["policy"] as? JsonObject)?.text("message")) }
        }
        _state.update { it.copy(readinessLoaded=true) }
    }
    fun options(value: BackupRestoreOptions) {
        if(_state.value.busy) return
        watchedId=null; pendingApply=null
        val old=_state.value.restore
        val scopeChanged=old.root!=value.root || old.password!=value.password
        _state.update { it.copy(restore=if(scopeChanged) value.copy(selected=emptySet()) else value,operation=null,error=null,
            inventoryReady=it.inventoryReady && old.root==value.root && old.password==value.password,
            nodes=if(old.root==value.root && old.password==value.password) it.nodes else emptyList()) }
    }
    fun inventory() = run {
        val s=_state.value; val a=s.archive ?: return@run
        if(s.requiresRoot) s.restore.copy(partial=false).prepare(true)
        val body=buildJsonObject {
            if(s.requiresRoot) put("target_root",s.restore.root.trim())
            if(s.restore.password.isNotEmpty()) put("password",s.restore.password)
            put("retry",true)
        }
        var status=panel.checkedObject("POST","${a.base}/restore/inventory/prepare",body,a.query)
        while(status.text("status") in setOf("queued","indexing")) {
            delay(1500)
            status=panel.checkedObject("GET","${a.base}/restore/inventory/status",query=a.query +
                if(s.requiresRoot) mapOf("target_root" to listOf(s.restore.root.trim())) else emptyMap())
        }
        require(status.text("status")=="ready") { status.text("message") ?: "Не удалось прочитать состав архива. Повторите проверку." }
        _state.update { it.copy(inventoryReady=true,parents=emptyList(),nodes=emptyList()) }
        children(null,false)
    }
    private suspend fun children(parent: String?, append: Boolean) {
        val s=_state.value; val a=s.archive ?: return
        val body=buildJsonObject {
            parent?.let { put("parent",it) }; if(append) s.cursor?.let { put("cursor",it) }
            if(s.requiresRoot) put("target_root",s.restore.root.trim()); put("limit",100)
        }
        val data=panel.checkedObject("POST","${a.base}/restore/tree/children",body,a.query)
        _state.update { it.copy(nodes=if(append) (it.nodes+data.objects("items")).distinctBy { r -> r.text("path") } else data.objects("items"),cursor=data.text("next_cursor")) }
    }
    fun directory(path: String?) = run {
        val stack=if(path==null) _state.value.parents.dropLast(1) else _state.value.parents+path
        children(stack.lastOrNull(),false); _state.update { it.copy(parents=stack) }
    }
    fun moreNodes() = run { children(_state.value.parents.lastOrNull(),true) }
    fun inspect() = run {
        val s=_state.value; val a=s.archive ?: return@run
        val body=buildJsonObject { put("view","archive"); put("retry",true); if(s.restore.password.isNotEmpty()) put("password",s.restore.password) }
        var status=panel.checkedObject("POST","${a.base}/restore/inventory/prepare",body,a.query)
        while(status.text("status") in setOf("queued","indexing")) {
            delay(1500); status=panel.checkedObject("GET","${a.base}/restore/inventory/status",query=a.query+("view" to listOf("archive")))
        }
        require(status.text("status")=="ready") { status.text("message") ?: "Не удалось прочитать архив. Проверьте пароль." }
        val data=panel.checkedObject("GET","${a.base}/restore/readiness",query=a.query)
        _state.update { it.copy(requiresRoot=data.flag("requires_target_root"),needsInspection=false) }
    }
    fun prepare() = run {
        pendingApply=null
        val s=_state.value; val a=s.archive ?: return@run
        require(s.readinessLoaded) { "Сначала прочитайте состояние архива" }
        require(!s.needsInspection) { "Сначала проверьте зашифрованный архив" }
        val body=s.restore.prepare(s.requiresRoot)
        val check=JsonObject(body.filterKeys { it !in setOf("restore_mode","protective_backup","apply","request_id") } + ("include_directory_tree" to JsonPrimitive(false)))
        val plan=panel.checkedObject("POST","${a.base}/restore/plan",check,a.query)
        val forbidden=plan.flag("full_restore_unavailable")
        _state.update { it.copy(fullUnavailable=forbidden,policy=(plan["policy"] as? JsonObject)?.text("message")) }
        require(!forbidden || s.restore.partial) { (plan["policy"] as? JsonObject)?.text("message") ?: "Выберите разрешённые файлы для частичного восстановления" }
        val data=panel.checkedObject("POST","${a.base}/restore",body,a.query)
        val op=data["operation"] as? JsonObject ?: error("Панель не вернула подготовку восстановления")
        watchedId=backupOperationId(op) ?: error("Нет идентификатора операции")
        _state.update { it.copy(operation=op,page="plan") }
        load(false)
    }
    fun apply() = run {
        val s=_state.value; val a=s.archive ?: return@run; val op=s.operation ?: return@run
        require(backupPrepared(op)) { "Дождитесь готового плана" }
        val id=backupOperationId(op)!!
        val body=pendingApply?.takeIf { it.first==id }?.second ?: RestoreRequests.apply(id,s.restore.password.takeIf(String::isNotEmpty)?.let(::JsonPrimitive),s.restore.protective).also { pendingApply=id to it }
        val data=panel.checkedObject("POST","${a.base}/restore",body,a.query)
        val active=data["operation"] as? JsonObject ?: error("Панель не вернула операцию")
        pendingApply=null
        watchedId=backupOperationId(active)
        _state.update { it.copy(page="operations",operation=active,archive=null,preview=null,restore=BackupRestoreOptions(),notice="Восстановление запущено. Здесь появится результат.") }
        load(false)
    }
    fun create(label: String, encrypt: Boolean, password: String) = run {
        val s=_state.value; require(s.configured) { "Сначала выберите файлы и папки в настройках копирования" }
        require(!encrypt || password.isNotEmpty() || s.passwordStatus?.flag("configured")==true && s.passwordStatus.flag("masterkey_available")) { "Задайте пароль архива" }
        val result=panel.checkedObject("POST","/api/backups/create",buildJsonObject {
            put("target",if(s.serverId==null) "bot4vps" else "server"); s.serverId?.let { put("server_id",it) }
            if(label.isNotBlank()) put("label",label.trim()); put("encrypt",encrypt)
            if(encrypt && password.isNotEmpty()) put("password",password)
        })
        val operation=result["operation"] as? JsonObject ?: error("Панель не вернула операцию копирования")
        watchedId=backupOperationId(operation) ?: error("Нет идентификатора операции копирования")
        _state.update { it.copy(page="operations",notice="Резервное копирование запущено") }; load(false)
    }
    fun saveSettings(settings: JsonObject, currentPassword: String) = run {
        val s=_state.value
        if(s.settings?.flag("encrypt")==true && !settings.flag("encrypt") && s.passwordStatus?.flag("configured")==true) {
            panel.checkedObject("POST","/api/settings/backup-password/verify",buildJsonObject { put("password",currentPassword) })
        }
        require(!settings.flag("encrypt") || s.passwordStatus?.flag("configured")==true && s.passwordStatus.flag("masterkey_available")) { "Сначала настройте пароль резервных копий" }
        val path=if(s.serverId==null) "/api/backups/bot4vps-settings" else "/api/backups/profiles/${encodeSegment(s.serverId)}"
        panel.checkedObject(if(s.serverId==null) "PATCH" else "PUT",path,buildJsonObject { put(if(s.serverId==null) "settings" else "profile",settings) })
        _state.update { it.copy(notice="Настройки копирования сохранены") }; load(false)
    }
    fun import(uri: Uri) = run {
        val s=_state.value
        val args=s.serverId?.let { mapOf("destination_server_id" to listOf(it)) } ?: emptyMap()
        val response=panel.request("POST","/api/backups/import",query=args,uploads=mapOf("file" to panel.upload(uri))) as? JsonObject ?: error("Не удалось импортировать архив")
        require(response["ok"]!=JsonPrimitive(false)) { response.text("error") ?: "Не удалось импортировать архив" }
        _state.update { it.copy(notice="Архив добавлен. Для восстановления откройте его в списке.") }; load(false)
    }
    fun download(uri: Uri) = run {
        val a=_state.value.archive ?: return@run
        panel.download("GET","${a.base}/download",a.query,null,uri)
        _state.update { it.copy(notice="Архив сохранён") }
    }
    fun rename(name: String) = run {
        val a=_state.value.archive ?: return@run
        panel.checkedObject("PATCH","${a.base}/filename",buildJsonObject { put("filename",name.trim()) },a.query)
        _state.update { it.copy(archive=a.copy(row=JsonObject(a.row+("filename" to JsonPrimitive(name.trim())))),notice="Архив переименован") }; load(false)
    }
    fun delete() = run {
        val a=_state.value.archive ?: return@run
        panel.checkedObject("DELETE",a.base,query=a.query)
        _state.update { it.copy(archive=null,preview=null,page="archives",notice="Архив удалён") }; load(false)
    }
    fun cancel(row: JsonObject) = run {
        val id=backupOperationId(row) ?: return@run
        panel.checkedObject("POST","/api/backups/operations/${encodeSegment(id)}/cancel")
        _state.update { it.copy(notice="Запрошена отмена операции") }; load(false)
    }
}
