package com.bot4vps.mobile.ui.audit

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.*
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.*
import androidx.lifecycle.repeatOnLifecycle
import com.bot4vps.mobile.data.model.*
import com.bot4vps.mobile.ui.components.*
import kotlinx.serialization.json.*
import java.time.*
import java.time.format.DateTimeFormatter

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AuditScreen(onBack: () -> Unit, onTask: (String) -> Unit, onGraph: (String,Long,String) -> Unit,
    viewModel: AuditViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    var filters by rememberSaveable { mutableStateOf(false) }
    var custom by rememberSaveable { mutableStateOf(false) }
    var calendar by remember { mutableStateOf<String?>(null) }
    var from by remember { mutableStateOf<Long?>(null) }
    var to by remember { mutableStateOf<Long?>(null) }
    calendar?.let { boundary ->
        val date = rememberDatePickerState()
        DatePickerDialog(onDismissRequest={ calendar=null }, confirmButton={ TextButton(enabled=date.selectedDateMillis!=null,onClick={
            date.selectedDateMillis?.let { millis ->
                val day=Instant.ofEpochMilli(millis).atZone(ZoneOffset.UTC).toLocalDate()
                val stamp=if(boundary=="from") day.atStartOfDay(ZoneId.systemDefault()).toEpochSecond()
                    else day.plusDays(1).atStartOfDay(ZoneId.systemDefault()).toEpochSecond()-1
                if(boundary=="from") from=stamp else to=stamp
            }; calendar=null
        }) { Text("Выбрать") } },dismissButton={ TextButton(onClick={ calendar=null }) { Text("Отмена") } }) { DatePicker(state=date) }
    }
    if(state.selectedId!=null) {
        fun back() { if(state.event!=null) viewModel.closeEvent() else viewModel.close() }
        BackHandler { back() }
        PanelScaffold(topBar={ PanelTopBar(title={ Text(if(state.event!=null) "Событие" else "Операция") },navigationIcon={ IconButton(onClick=::back) { Icon(Icons.AutoMirrored.Filled.ArrowBack,"Назад") } },actions={ IconButton(onClick={ viewModel.open(state.selectedId!!) },enabled=!state.detailLoading) { Icon(Icons.Default.Refresh,"Обновить") } }) }) { padding ->
        LazyColumn(Modifier.fillMaxSize().padding(padding),contentPadding=PaddingValues(16.dp),verticalArrangement=Arrangement.spacedBy(12.dp)) {
            if(state.detailLoading) item { LinearProgressIndicator(Modifier.fillMaxWidth()) }
            state.detailError?.let { item { ErrorCard(it,onRetry={ viewModel.open(state.selectedId!!) }) } }
            state.detail?.let { detail ->
                val record=detail["record"] as JsonObject
                if(state.event!=null) {
                    item { TextButton(onClick=viewModel::closeEvent) { Text("← К операции") } }
                    item { AuditEvent(state.event!!) }
                } else {
                    item { AuditOperation(record,full=true) }
                    val task=detail["task"] as? JsonObject
                    if(task!=null) item { PanelCard("Задача") {
                        Text(task.text("name") ?: task.text("id") ?: "Задача")
                        Text(auditResultLabel(task.text("status").orEmpty()))
                        task.text("attempt")?.let { Text("Попытка: $it") }
                        task.text("id")?.let { id -> PanelSecondaryButton(onClick={ onTask(id) }) { Text("Открыть вывод задачи") } }
                    } } else if(record.text("task_id")!=null) item { Text("Задача уже удалена из истории. Запись операции сохранена.") }
                    val event=detail["event"] as? JsonObject
                    if(event!=null) item { PanelCard("Событие") {
                        Text(event.text("title") ?: "Событие")
                        event.text("message")?.let { Text(it) }
                        PanelSecondaryButton(onClick=viewModel::event) { Text("Открыть событие") }
                    } } else if(record.text("event_id")!=null) item { Text("Событие уже удалено из журнала по ротации.") }
                    val params=detail["params"] as? JsonObject
                    if(!params.isNullOrEmpty()) item { AuditParams(params) }
                    (detail["log"] as? JsonObject)?.let { log -> item { Text(if(log.flag("available")) "Лог доступен" else if(record.text("task_id")!=null) "Вывод хранится в связанной задаче" else "Отдельного лога у этой операции нет",style=MaterialTheme.typography.bodySmall) } }
                    val raw=(detail["technical_records"] as? JsonArray).orEmpty().mapNotNull { it as? JsonObject }
                    if(raw.isNotEmpty()) item { Text("Техническая хронология",style=MaterialTheme.typography.titleMedium) }
                    items(raw) { row -> AuditTechnicalRecord(row) }
                    val server=(record["server"] as? JsonObject)?.text("id")
                    if(server!=null && record.auditStart()!=null) item { PanelSecondaryButton(onClick={ onGraph(server,record.auditStart()!!,record.text("id").orEmpty()) },modifier=Modifier.fillMaxWidth()) { Text("Показать на графике") } }
                }
            }
        }
        }
        return
    }
    PanelScaffold(topBar={ PanelTopBar(title={ Text("Аудит") },navigationIcon={ IconButton(onClick=onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack,"Назад") } },actions={ IconButton(onClick=viewModel::refresh,enabled=!state.loading) { Icon(Icons.Default.Refresh,"Обновить") } }) }) { padding ->
        Refreshable(state.loading, viewModel::refresh, Modifier.fillMaxSize().padding(padding)) {
        LazyColumn(Modifier.fillMaxSize(),contentPadding=PaddingValues(16.dp),verticalArrangement=refreshArrangement(10.dp)) {
            item { LazyRow(horizontalArrangement=Arrangement.spacedBy(6.dp)) {
                listOf(1,7,30,90).forEach { days -> item { PanelTab(!custom && state.filters.days==days,{ custom=false; viewModel.filters(state.filters.copy(days=days,from=null,to=null)) },{ Text(if(days==1) "24 часа" else "$days дней") }) } }
                item { PanelTab(custom,{ custom=true },{ Text("Произвольный") }) }
            } }
            if(custom) item { Column(verticalArrangement=Arrangement.spacedBy(8.dp)) {
                fun dateLabel(stamp: Long?)=stamp?.let { DateTimeFormatter.ofPattern("dd.MM.yyyy").withZone(ZoneId.systemDefault()).format(Instant.ofEpochSecond(it)) } ?: "Выбрать дату"
                PanelSecondaryButton(onClick={ calendar="from" }) { Text("С: ${dateLabel(from)}") }
                PanelSecondaryButton(onClick={ calendar="to" }) { Text("По: ${dateLabel(to)}") }
                Text("Время устройства. Дата «По» необязательна.",style=MaterialTheme.typography.bodySmall)
                PanelButton(onClick={ viewModel.filters(state.filters.copy(from=from,to=to)) },enabled=from!=null && !state.loading) { Text("Показать") }
            } }
            item { PanelSearchField(state.filters.search,viewModel::search,Modifier.fillMaxWidth(),placeholder="Поиск по журналу") }
            item { Row { TextButton(onClick={ filters=!filters }) { Text(if(filters) "Скрыть фильтры" else "Фильтры") }; TextButton(onClick={ custom=false; from=null; to=null; viewModel.filters(AuditFilters()) }) { Text("Сбросить") } } }
            state.filters.server?.let { id -> item { Row(verticalAlignment=androidx.compose.ui.Alignment.CenterVertically) {
                Text("Сервер: ${state.choices["server"]?.find { it.first==id }?.second ?: id}", Modifier.weight(1f),style=MaterialTheme.typography.bodySmall)
                TextButton(onClick={ viewModel.filters(state.filters.copy(server=null)) }) { Text("Все серверы") }
            } } }
            if(filters) {
                item { SearchableChoice("Кто выполнил",state.filters.actor,state.choices["actor"].orEmpty(),{ viewModel.filters(state.filters.copy(actor=it)) },allowEmpty=true,emptyLabel="Все") }
                item { SearchableChoice("Действие",state.filters.action,state.choices["action"].orEmpty(),{ viewModel.filters(state.filters.copy(action=it)) },allowEmpty=true,emptyLabel="Все") }
                item { SearchableChoice("Сервер",state.filters.server,state.choices["server"].orEmpty(),{ viewModel.filters(state.filters.copy(server=it)) },allowEmpty=true,emptyLabel="Все") }
                item { SearchableChoice("Результат",state.filters.result,state.choices["result"].orEmpty(),{ viewModel.filters(state.filters.copy(result=it)) },allowEmpty=true,emptyLabel="Все") }
            }
            if(state.loading) item { LinearProgressIndicator(Modifier.fillMaxWidth()) }
            state.error?.let { item { ErrorCard(it,onRetry=viewModel::refresh) } }
            item { Text("Показано операций: ${state.records.size}${if(state.next!=null) " · есть ещё" else ""}",style=MaterialTheme.typography.bodySmall) }
            if(state.loaded && state.records.isEmpty()) item { Text("За выбранный период операций нет. Измените фильтры или расширьте период.") }
            items(state.records,key={ it.text("id").orEmpty() }) { row ->
                PanelSurfaceCard(Modifier.fillMaxWidth().clickable { row.text("id")?.let(viewModel::open) }) { Column(Modifier.padding(14.dp)) { AuditOperation(row) } }
            }
            if(state.next!=null) item { PanelSecondaryButton(onClick=viewModel::more,enabled=!state.loading,modifier=Modifier.fillMaxWidth()) { Text("Показать ещё") } }
        }
    }
    }
}

@Composable
fun AuditOperation(record: JsonObject, full: Boolean=false) {
    Column(verticalArrangement=Arrangement.spacedBy(6.dp)) {
        Text(record.text("title") ?: record.text("action") ?: "Операция",style=MaterialTheme.typography.titleSmall)
        val result=auditResult(record)
        Text(auditResultLabel(result),color=if(result in setOf("failed","denied")) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary)
        Text("Кто: ${auditActor(record,full)}",style=MaterialTheme.typography.bodySmall)
        auditServer(record)?.let { Text("Сервер: $it",style=MaterialTheme.typography.bodySmall) }
        Text("Начало: ${auditTime(record.auditStart())}",style=MaterialTheme.typography.bodySmall)
        if(record.text("status")!="waiting_rule_selection") Text("Завершение: ${record["ended_at"]?.let { (it as? JsonPrimitive)?.longOrNull }?.let(::auditTime) ?: "Нет записи о завершении"}",style=MaterialTheme.typography.bodySmall)
        auditDuration((record["duration_seconds"] as? JsonPrimitive)?.doubleOrNull)?.let { Text("Длительность: $it",style=MaterialTheme.typography.bodySmall) }
        record.text("error")?.let { Text(it,color=MaterialTheme.colorScheme.error) }
        if(full && result=="incomplete") Text("Аудит увидел начало операции, но не получил итог. Это не означает, что операция всё ещё выполняется. Сопоставьте запись с задачей, логом и событиями.",style=MaterialTheme.typography.bodySmall)
        if(!full) (record["attachments"] as? JsonObject)?.let { a -> Text(listOfNotNull(if(a.flag("task")) "Задача" else null,if(a.flag("event")) "Событие" else null).joinToString(" · "),style=MaterialTheme.typography.labelSmall) }
    }
}

@Composable
private fun AuditParams(params: JsonObject) {
    PanelCard("Параметры") { SelectionContainer { Column(verticalArrangement=Arrangement.spacedBy(4.dp)) {
        params.forEach { (key,value) -> Text("$key: ${if(value is JsonPrimitive) value.content else value.toString()}",style=MaterialTheme.typography.bodySmall) }
    } } }
}

@Composable
private fun AuditTechnicalRecord(record: JsonObject) {
    var expanded by remember { mutableStateOf(false) }
    PanelSurfaceCard(Modifier.fillMaxWidth().clickable { expanded=!expanded }) { Column(Modifier.padding(12.dp),verticalArrangement=Arrangement.spacedBy(5.dp)) {
        Text(auditTime(record.auditStart()),style=MaterialTheme.typography.labelSmall)
        Text(record.text("title") ?: record.text("action") ?: "Запись",style=MaterialTheme.typography.titleSmall)
        Text(auditResultLabel(auditResult(record)),style=MaterialTheme.typography.bodySmall)
        if(expanded) {
            Text("Код: ${record.text("action").orEmpty()}"); Text("Кто: ${auditActor(record,true)}")
            auditServer(record)?.let { Text("Сервер: $it") }
            listOf("op_id" to "Операция","task_id" to "Задача","error" to "Ошибка","failure_detail" to "Причина отказа").forEach { (key,label) -> record.text(key)?.let { Text("$label: $it") } }
            (record["params"] as? JsonObject)?.takeIf { it.isNotEmpty() }?.let { AuditParams(it) }
        }
    } }
}

@Composable
private fun AuditEvent(event: JsonObject) {
    PanelCard("Событие") {
        Text(event.text("title") ?: "Событие",style=MaterialTheme.typography.titleSmall)
        Text((event["ts_epoch"] as? JsonPrimitive)?.longOrNull?.let(::auditTime) ?: event.text("timestamp") ?: "—")
        event.text("message")?.let { Text(it) }
        (event["details"] as? JsonObject)?.takeIf { it.isNotEmpty() }?.let { AuditParams(it) }
    }
}
