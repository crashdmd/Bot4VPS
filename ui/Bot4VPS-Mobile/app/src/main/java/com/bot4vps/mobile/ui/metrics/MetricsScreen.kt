package com.bot4vps.mobile.ui.metrics

import com.bot4vps.mobile.ui.components.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.repeatOnLifecycle
import com.bot4vps.mobile.data.api.*
import com.bot4vps.mobile.data.model.*
import com.bot4vps.mobile.data.repository.checkedObject
import com.bot4vps.mobile.ui.control.NativeField
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.serialization.json.*
import java.time.Instant
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import javax.inject.Inject

data class MetricsState(val servers: List<Pair<String,String>> = emptyList(), val selected: String? = null,
    val days: Int = 1, val history: MetricHistory? = null, val chartRevision: Int = 0,
    val busy: Boolean = false, val error: String? = null, val from: String = "", val to: String = "",
    val marks: List<JsonObject> = emptyList(), val marksTruncated: Boolean = false, val timelineError: String? = null,
    val focusedRecord: String = "", val focusedTime: Long? = null)

@HiltViewModel
class MetricsViewModel @Inject constructor(savedState: SavedStateHandle, private val panel: NativePanelClient) : ViewModel() {
    private val initialServer = auditInitialServer(savedState.get<String>("serverId"))
    private var manuallySelected = false
    fun auditServer() = auditNavigationServer(initialServer, _state.value.selected, manuallySelected)
    private val focus = savedState.get<String>("ts")?.toLongOrNull()
    private val _state = MutableStateFlow(MetricsState(selected = initialServer,
        focusedRecord=savedState.get<String>("recordId").orEmpty(),focusedTime=focus,
        from=focus?.let { Instant.ofEpochSecond(it-3600).toString() }.orEmpty(),to=focus?.let { Instant.ofEpochSecond(it+3600).toString() }.orEmpty()))
    val state = _state.asStateFlow()
    private var request: Job? = null
    private var windowOverride: HistoryWindow? = null
    private var backgroundRequest = false
    init {
        viewModelScope.launch {
            try {
                val response = panel.request("GET", "/api/servers") as JsonObject
                val servers = (response["servers"] as? JsonArray).orEmpty().mapNotNull { row -> (row as? JsonObject)?.let { obj -> obj.text("id")?.let { it to (obj.text("name") ?: it) } } }
                _state.update { it.copy(servers = servers, selected = it.selected ?: servers.firstOrNull()?.first) }
                refresh()
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) { _state.update { it.copy(error = errorText(e)) } }
        }
    }
    fun select(id: String) { manuallySelected = true; windowOverride = null; _state.update { it.copy(selected = id,focusedRecord="",focusedTime=null, history=null, marks=emptyList(), chartRevision=it.chartRevision+1) }; refresh() }
    fun range(days: Int) { windowOverride = null; _state.update { it.copy(days = days, from = "", to = "",focusedRecord="",focusedTime=null, history=null, marks=emptyList(), chartRevision=it.chartRevision+1) }; refresh() }
    fun from(value: String) { _state.update { it.copy(from = value) } }
    fun to(value: String) { _state.update { it.copy(to = value) } }
    fun applyDates() { windowOverride = null; _state.update { it.copy(chartRevision=it.chartRevision+1) }; refresh() }
    fun showWindow(window: HistoryWindow?) { windowOverride = window; reload(false) }
    fun refresh() { reload(true) }
    private fun reload(manual: Boolean) {
        val s = _state.value; val id = s.selected ?: return
        request?.cancel()
        backgroundRequest = !manual
        request = viewModelScope.launch {
            _state.update { it.copy(busy = manual || it.history == null, error = null) }
            try {
                val now = Instant.now().epochSecond
                val from = windowOverride?.from ?: if (s.from.isBlank()) now - s.days * 86400L else parseTime(s.from)
                val to = windowOverride?.to ?: if (s.to.isNotBlank()) parseTime(s.to)
                    else if (s.from.isNotBlank()) Instant.ofEpochSecond(from).atZone(ZoneId.systemDefault()).toLocalDate()
                        .plusDays(1).atStartOfDay(ZoneId.systemDefault()).toEpochSecond().minus(1).coerceAtMost(now)
                    else now
                require(from < to) { "Начало периода должно быть раньше конца" }
                val query=mapOf("from" to listOf(from.toString()), "to" to listOf(to.toString()), "step" to listOf("auto"))
                val result = panel.checkedObject("GET", "/api/metrics/servers/${encodeSegment(id)}", query=query)
                currentCoroutineContext().ensureActive()
                _state.update { it.copy(history = decodeMetricHistory(result, HistoryWindow(from, to)), timelineError=null) }
                try {
                    val timeline=panel.checkedObject("GET","/api/timeline/${encodeSegment(id)}",query=query)
                    _state.update { it.copy(marks=(timeline["marks"] as? JsonArray).orEmpty().mapNotNull { it as? JsonObject },marksTruncated=timeline.flag("marks_truncated")) }
                } catch(e: CancellationException) { throw e }
                catch(e: Exception) { _state.update { it.copy(timelineError="Хронология недоступна: ${errorText(e)}") } }
                _state.update { it.copy(busy=false) }
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) { _state.update { it.copy(busy = false, error = errorText(e)) } }
        }
    }
    suspend fun observe() {
        try {
            while (true) {
                delay(15_000)
                val current = _state.value
                // Fixed dates, the audit window and a user's pan/zoom remain fixed.
                if (windowOverride == null && current.from.isBlank() && current.to.isBlank() && request?.isActive != true) {
                    reload(false)
                    request?.join()
                }
            }
        } finally { if (backgroundRequest) request?.cancel() }
    }
    private fun parseTime(value: String): Long = value.toLongOrNull() ?: runCatching { Instant.parse(value).epochSecond }.getOrElse { error("Укажите дату в формате 2026-11-03T12:00:00Z") }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MetricsScreen(onBack: () -> Unit, onAdvanced: (String?) -> Unit = {}, onAudit: (String,String) -> Unit = { _,_ -> }, viewModel: MetricsViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(lifecycle, viewModel) { lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) { viewModel.observe() } }
    var custom by rememberSaveable { mutableStateOf(state.focusedTime!=null) }
    var calendar by remember { mutableStateOf<String?>(null) }
    calendar?.let { boundary ->
        val date = rememberDatePickerState()
        DatePickerDialog(onDismissRequest = { calendar = null },
            confirmButton = { TextButton(enabled = date.selectedDateMillis != null, onClick = {
                date.selectedDateMillis?.let { millis ->
                    val day = Instant.ofEpochMilli(millis).atZone(ZoneOffset.UTC).toLocalDate()
                    val instant = if (boundary == "from") day.atStartOfDay(ZoneId.systemDefault()).toInstant()
                        else day.plusDays(1).atStartOfDay(ZoneId.systemDefault()).toInstant().minusSeconds(1)
                    if (boundary == "from") viewModel.from(instant.toString()) else viewModel.to(instant.toString())
                }
                calendar = null
            }) { Text("Выбрать") } }, dismissButton = { TextButton(onClick = { calendar = null }) { Text("Отмена") } }) {
            DatePicker(state = date)
        }
    }
    PanelScaffold(topBar = { PanelTopBar(title = { Text("Мониторинг серверов") }, navigationIcon = { TextButton(onClick = onBack) { Text("Назад") } }, actions = { TextButton(onClick = { onAdvanced(viewModel.auditServer()) }) { Text("Аудит") } }) }) { padding ->
        Refreshable(state.busy, viewModel::refresh, Modifier.fillMaxSize().padding(padding)) {
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = refreshArrangement(12.dp)) {
            item { NativeField("server_id", buildJsonObject { put("type","string"); put("title","Сервер") }, state.selected?.let { JsonPrimitive(it) }, true, { (it as? JsonPrimitive)?.content?.let(viewModel::select) }, mapOf("server_id" to state.servers)) }
            item { LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                listOf(1,7,30,90).forEach { days -> item { PanelTab(state.days == days && !custom, onClick = { custom = false; viewModel.range(days) }, label = { Text(if (days == 1) "24 часа" else "$days дней") }) } }
                item { PanelTab(custom, { custom = true }, label = { Text("Произвольный") }) }
            } }
            if (custom) item { Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                fun dateLabel(raw: String): String = runCatching { DateTimeFormatter.ofPattern("dd.MM.yyyy").withZone(ZoneId.systemDefault()).format(Instant.parse(raw)) }.getOrDefault("Выбрать дату")
                PanelSecondaryButton(onClick = { calendar = "from" }, modifier = Modifier.fillMaxWidth()) { Text("С: ${dateLabel(state.from)}") }
                PanelSecondaryButton(onClick = { calendar = "to" }, modifier = Modifier.fillMaxWidth()) { Text("По: ${dateLabel(state.to)}") }
                Text("Выберите начало периода. Дата «По» необязательна.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                PanelButton(onClick = viewModel::applyDates, enabled = !state.busy && state.from.isNotBlank()) { Text("Показать") }
            } }
            if (state.busy) item { LinearProgressIndicator(Modifier.fillMaxWidth()) }
            state.error?.let { item { Text(it, color = MaterialTheme.colorScheme.error) } }
            state.focusedTime?.let { stamp -> item { Text("Операция: ${auditTime(stamp)} · окно ±1 час",style=MaterialTheme.typography.bodySmall) } }
            state.history?.let { history -> item(key="history-chart") { HistoryChart(history, state.marks,
                state.focusedRecord, "${state.selected}:${state.chartRevision}", viewModel::showWindow) } }
            item { Text("Хронология сервера",style=MaterialTheme.typography.titleMedium); Text("Вертикальные метки: действия и системные события",style=MaterialTheme.typography.bodySmall) }
            state.timelineError?.let { item { Text(it,color=MaterialTheme.colorScheme.error) } }
            if(state.marksTruncated) item { Text("Показана часть операций. Сократите период, чтобы увидеть остальные.") }
            if(!state.busy && state.marks.isEmpty() && state.timelineError==null) item { Text("За этот период действий и смен статуса нет") }
            items(state.marks) { mark -> PanelCard(mark.text("title") ?: "Действие") {
                Text(auditTime((mark["ts"] as? JsonPrimitive)?.longOrNull),style=MaterialTheme.typography.bodySmall)
                Text(auditActor(mark),style=MaterialTheme.typography.bodySmall)
                Text(auditResultLabel(mark.text("result") ?: "unknown"))
                val availability=mark["availability"] as? JsonObject
                availability?.text("error")?.let { Text(it,color=MaterialTheme.colorScheme.error) }
                if(availability==null) mark.text("audit_id")?.let { record -> state.selected?.let { server -> TextButton(onClick={ onAudit(server,record) }) { Text("Открыть операцию") } } }
            } }
        }
    }
    }
}
