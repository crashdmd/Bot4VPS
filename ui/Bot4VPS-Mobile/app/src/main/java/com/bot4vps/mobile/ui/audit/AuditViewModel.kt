package com.bot4vps.mobile.ui.audit

import androidx.lifecycle.*
import com.bot4vps.mobile.data.api.*
import com.bot4vps.mobile.data.model.*
import com.bot4vps.mobile.data.repository.checkedObject
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import kotlinx.serialization.json.*
import java.time.Instant
import javax.inject.Inject

data class AuditState(val filters: AuditFilters = AuditFilters(), val records: List<JsonObject> = emptyList(),
    val choices: Map<String, List<Pair<String,String>>> = emptyMap(), val next: String? = null,
    val loading: Boolean = false, val loaded: Boolean = false, val error: String? = null,
    val selectedId: String? = null, val detail: JsonObject? = null, val detailLoading: Boolean = false, val detailError: String? = null,
    val event: JsonObject? = null)

@HiltViewModel
class AuditViewModel @Inject constructor(saved: SavedStateHandle, private val panel: NativePanelClient) : ViewModel() {
    private val initialServer = auditInitialServer(saved.get<String>("serverId"))
    private val _state = MutableStateFlow(AuditState(filters=AuditFilters(server=initialServer)))
    val state = _state.asStateFlow()
    private var request: Job? = null
    private var detailRequest: Job? = null
    private var debounce: Job? = null
    private var pageQuery: Map<String,List<String>> = emptyMap()
    init {
        viewModelScope.launch {
            try {
                val facets = panel.checkedObject("GET", "/api/audit/facets")
                fun rows(key: String) = (facets[key] as? JsonArray).orEmpty().mapNotNull { it as? JsonObject }
                fun label(row: JsonObject, value: String) = "$value (${row.text("count") ?: "0"})"
                _state.update { it.copy(choices=mapOf(
                    "actor" to rows("actors").mapNotNull { r -> r.text("type")?.let { type -> (type+r.text("id")?.let { ":$it" }.orEmpty()) to label(r,r.text("label") ?: type) } },
                    "action" to rows("actions").mapNotNull { r -> r.text("code")?.let { it to label(r,r.text("title") ?: it) } },
                    "result" to rows("results").mapNotNull { r -> r.text("value")?.let { it to label(r,r.text("title") ?: auditResultLabel(it)) } },
                    "server" to rows("servers").mapNotNull { r -> r.text("id")?.let { it to label(r,r.text("name") ?: it) } }
                )) }
            } catch(e: CancellationException) { throw e }
            catch(e: Exception) { _state.update { it.copy(error="Не удалось загрузить фильтры: ${errorText(e)}") } }
        }
        refresh()
        saved.get<String>("recordId")?.takeIf(String::isNotBlank)?.let(::open)
    }
    fun filters(value: AuditFilters) { _state.update { it.copy(filters=value) }; debounce?.cancel(); refresh() }
    fun search(value: String) {
        _state.update { it.copy(filters=it.filters.copy(search=value)) }
        request?.cancel(); _state.update { it.copy(loading=false) }
        debounce?.cancel(); debounce=viewModelScope.launch { delay(350); refresh() }
    }
    fun refresh() = load(false)
    fun more() { if(!_state.value.loading && _state.value.next != null) load(true) }
    private fun load(append: Boolean) {
        val s = _state.value
        request?.cancel()
        request=viewModelScope.launch {
            _state.update { it.copy(loading=true,error=null) }
            try {
                val query = if(append) pageQuery + ("cursor" to listOf(s.next!!)) else s.filters.query(Instant.now().epochSecond)
                val data = panel.checkedObject("GET", "/api/audit", query=query)
                val rows = (data["items"] as? JsonArray)?.mapNotNull { it as? JsonObject } ?: error("Панель вернула неизвестный формат аудита")
                if(!append) pageQuery=query
                _state.update { it.copy(records=if(append) (it.records+rows).distinctBy { r -> r.text("id") } else rows,
                    next=data.text("next_cursor"),loading=false,loaded=true) }
            } catch(e: CancellationException) { throw e }
            catch(e: Exception) { _state.update { it.copy(loading=false,error=errorText(e)) } }
        }
    }
    fun open(id: String) {
        detailRequest?.cancel()
        _state.update { it.copy(selectedId=id,detail=null,detailLoading=true,detailError=null,event=null) }
        detailRequest=viewModelScope.launch {
            try {
                val data = panel.checkedObject("GET", "/api/audit/${encodeSegment(id)}")
                require(data["record"] is JsonObject) { "Не удалось прочитать операцию" }
                _state.update { it.copy(detail=data,detailLoading=false) }
            } catch(e: CancellationException) { throw e }
            catch(e: Exception) { _state.update { it.copy(detailError=errorText(e),detailLoading=false) } }
        }
    }
    fun close() { detailRequest?.cancel(); _state.update { it.copy(selectedId=null,detail=null,detailLoading=false,event=null) } }
    fun event() {
        val event = _state.value.detail?.get("event") as? JsonObject ?: return
        _state.update { it.copy(event=event) }
        val id = event.text("id") ?: return
        if(!event.flag("read")) viewModelScope.launch {
            try { panel.checkedObject("POST", "/api/events/mark-read", buildJsonObject { put("event_id",id) }) }
            catch(e: CancellationException) { throw e }
            catch(e: Exception) { _state.update { it.copy(detailError=errorText(e)) } }
        }
    }
    fun closeEvent() { _state.update { it.copy(event=null) } }
}
