package com.bot4vps.mobile.ui.control

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.bot4vps.mobile.data.model.*
import com.bot4vps.mobile.ui.components.*
import kotlinx.serialization.json.*

private val collectionTitles = mapOf("catalog" to "Резервные копии", "imported_archives" to "Загруженные архивы", "operations" to "Операции копирования", "items" to "Файлы", "events" to "События", "queues" to "Очереди", "rows" to "Действия", "records" to "Действия", "queue" to "Ожидающие задачи")
private val statuses = mapOf("pending" to "В очереди", "running" to "Выполняется", "completed" to "Завершено", "failed" to "Ошибка", "cancelled" to "Отменено", "SUCCESS" to "Успешно", "FAILED" to "Ошибка", "RUNNING" to "Выполняется", "PENDING" to "В очереди", "CANCELLED" to "Отменено", "ok" to "Успешно", "success" to "Успешно")
@Composable
fun DomainDataView(value: JsonElement, section: String, labels: Map<String,String>, search: String, onRecord: (JsonObject,String)->Unit) {
    val obj=value as? JsonObject ?: return NativeDataView(value,labels)
    val keys=when(section) { "backups" -> if(obj["catalog"] != null) listOf("catalog","imported_archives") else listOf("operations"); "files" -> listOf("items"); "project" -> listOf("files"); "events" -> listOf("events"); "queues" -> listOf("queues"); "audit" -> listOf("items","rows","records","buckets"); else -> emptyList() }
    var found=false
    Column(verticalArrangement=Arrangement.spacedBy(8.dp)) {
        keys.forEach { key ->
            val rows=obj[key] as? JsonArray ?: return@forEach
            found=true
            if(keys.size>1) Text(collectionTitles[key] ?: "Хронология",style=MaterialTheme.typography.titleMedium)
            val visible=rows.mapNotNull { it as? JsonObject }.filter { search.isBlank() || it.values.filterIsInstance<JsonPrimitive>().any { v-> v.content.contains(search,true) } }
            if(visible.isEmpty()) Text(if(search.isBlank()) "Нет записей" else "Ничего не найдено",color=MaterialTheme.colorScheme.onSurfaceVariant)
            visible.forEach { row ->
                val title=row.text("display_name") ?: row.text("title") ?: row.text("name") ?: row.text("server_name") ?: row.text("filename") ?: row.text("action") ?: row.text("created_at") ?: "Запись"
                PanelSurfaceCard(Modifier.fillMaxWidth().clickable { onRecord(row,key) }) {
                    Column(Modifier.padding(14.dp),verticalArrangement=Arrangement.spacedBy(5.dp)) {
                        Text((if(row.flag("is_dir")) "▸ " else "")+title,style=MaterialTheme.typography.titleSmall)
                        val status=row.text("status") ?: row.text("result")
                        status?.let { Text(statuses[it] ?: it, color=if(it.lowercase()=="failed") MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant) }
                        listOf("display_created_at","created_at","message","server_name","size_display","label").mapNotNull { row.text(it) }.distinct().filter { it != title }.take(3).forEach { Text(it,style=MaterialTheme.typography.bodySmall,maxLines=3) }
                        if(key=="queues") {
                            val running=row["running"] as? JsonObject
                            running?.let { Text("Сейчас: "+it.text("name").orEmpty()); TextButton(onClick={ onRecord(it,"tasks") }) { Text("Открыть задачу") } }
                            (row["queue"] as? JsonArray).orEmpty().forEach { task-> (task as? JsonObject)?.let { TextButton(onClick={ onRecord(it,"queue") }) { Text(it.text("name") ?: "Задача") } } }
                            if(row.flag("paused")) Text("Очередь приостановлена",color=MaterialTheme.colorScheme.error)
                        }
                    }
                }
            }
        }
        if(!found) NativeDataView(value,labels)
    }
}
