package com.bot4vps.mobile.ui.control

import com.bot4vps.mobile.ui.components.*
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import com.bot4vps.mobile.data.model.*
import com.bot4vps.mobile.ui.components.SearchableChoice
import kotlinx.serialization.json.*

private val choiceLabels = mapOf("acme" to "acme.sh", "certbot" to "certbot", "password" to "Пароль", "key" to "SSH-ключ", "merge" to "Объединить", "clean" to "Очистить и восстановить", "full" to "Всё", "selected" to "Выбранные файлы", "server" to "Управляемый сервер", "bot4vps" to "Установка Bot4VPS", "dark" to "Тёмная", "light" to "Светлая", "none" to "Без HTTPS", "domain" to "Домен", "ip" to "IP-адрес", "custom" to "Свой сертификат", "proxy" to "Прокси", "scripts" to "Скрипты", "keys" to "SSH-ключи", "docker" to "Docker", "raw" to "Исходные пробы", "hour" to "По часам", "auto" to "Автоматически")

@Composable
fun NativeField(
    name: String, schema: JsonObject, value: JsonElement?, required: Boolean,
    onChange: (JsonElement?) -> Unit, choices: Map<String, List<Pair<String, String>>> = emptyMap(),
    depth: Int = 0
) {
    if (schema.flag("hidden")) return
    val label = schema.text("title") ?: name.replace('_', ' ')
    val type = schema.text("type") ?: "string"
    if (name in setOf("q", "query", "search") && type == "string") {
        PanelSearchField((value as? JsonPrimitive)?.contentOrNull.orEmpty(), { onChange(JsonPrimitive(it)) },
            modifier = Modifier.fillMaxWidth(), placeholder = label)
        return
    }
    val enum = schema["enum"] as? JsonArray
    val options = choices[name]?.takeIf { it.isNotEmpty() }
        ?: enum?.map { it.jsonPrimitive.content to (choiceLabels[it.jsonPrimitive.content] ?: it.jsonPrimitive.content) }
    if (type == "object" && !required && schema.flag("nullable")) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (value == null || value == JsonNull) {
                PanelSecondaryButton(onClick = { onChange(NativeForm.initial(JsonObject(schema - "nullable")) ?: JsonObject(emptyMap())) }) { Text("Задать: $label") }
                if (value == JsonNull) Text("Будет очищено")
            } else {
                TextButton(onClick = { onChange(null) }) { Text("Не изменять: $label") }
                TextButton(onClick = { onChange(JsonNull) }) { Text("Очистить") }
            }
        }
        if (value == null || value == JsonNull) return
    }
    when {
        type == "object" -> {
            val fields = schema.properties()
            val values = (value as? JsonObject) ?: JsonObject(emptyMap())
            PanelSurfaceCard(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text(label, style = MaterialTheme.typography.titleSmall)
                    fields.forEach { (key, field) ->
                        NativeField(key, field, values[key], key in schema.required(), { next ->
                            onChange(JsonObject(values.toMutableMap().apply { if (next == null) remove(key) else put(key, next) }))
                        }, choices, depth + 1)
                    }
                    if (fields.isEmpty() && schema["additionalProperties"] != JsonPrimitive(false) || schema["additionalProperties"] is JsonObject || schema.flag("additionalProperties")) {
                        values.filterKeys { it !in fields }.forEach { (key, v) ->
                            Row(Modifier.fillMaxWidth()) {
                                val inferred = JsonObject(mapOf("type" to JsonPrimitive(if (v is JsonPrimitive && v.booleanOrNull != null) "boolean" else if (v is JsonPrimitive && !v.isString && v.doubleOrNull != null) "number" else "string"), "title" to JsonPrimitive(key)))
                                Box(Modifier.weight(1f)) { NativeField(key, inferred, v, false, { next -> onChange(JsonObject(values.toMutableMap().apply { if (next == null) remove(key) else put(key, next) })) }, choices, depth + 1) }
                                TextButton(onClick = { onChange(JsonObject(values.filterKeys { it != key })) }) { Text("×") }
                            }
                        }
                        var key by remember { mutableStateOf("") }
                        var propertyType by remember { mutableStateOf("string") }
                        PanelTextField(key, { key = it }, label = { Text("Имя дополнительного параметра") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            listOf("string" to "Текст", "number" to "Число", "boolean" to "Да/нет").forEach { (v, t) ->
                                PanelTab(selected = propertyType == v, onClick = { propertyType = v }, label = { Text(t) })
                            }
                        }
                        TextButton(enabled = key.isNotBlank() && key !in values, onClick = {
                            val v = when (propertyType) { "boolean" -> JsonPrimitive(false); "number" -> JsonPrimitive(0); else -> JsonPrimitive("") }
                            onChange(JsonObject(values + (key.trim() to v))); key = ""
                        }) { Text("Добавить параметр") }
                    }
                }
            }
        }
        type == "array" -> {
            val items = schema["items"] as? JsonObject ?: JsonObject(mapOf("type" to JsonPrimitive("string")))
            val list = (value as? JsonArray) ?: JsonArray(emptyList())
            Text(label, style = MaterialTheme.typography.labelLarge)
            list.forEachIndexed { index, item ->
                Column(Modifier.fillMaxWidth()) {
                    NativeField("${index + 1}", items, item, true, { next ->
                        onChange(JsonArray(list.toMutableList().apply { this[index] = next ?: JsonPrimitive("") }))
                    }, choices, depth + 1)
                    TextButton(onClick = { onChange(JsonArray(list.filterIndexed { i, _ -> i != index })) }) { Text("Удалить элемент") }
                }
            }
            TextButton(onClick = { onChange(JsonArray(list + (NativeForm.initial(items) ?: JsonPrimitive("")))) }) { Text("Добавить элемент") }
            if (!required && value != null && schema["default"] == null) TextButton(onClick = { onChange(null) }) { Text("Не изменять") }
        }
        options != null && (name in setOf("server_id", "destination_server_id") || options.size>6) -> {
            SearchableChoice(label, (value as? JsonPrimitive)?.contentOrNull, options, { onChange(it?.let(::JsonPrimitive)) },
                allowEmpty = !required, emptyLabel = if (required) "Выберите сервер" else "Все серверы")
        }
        options != null -> {
            var expanded by remember { mutableStateOf(false) }
            val current = (value as? JsonPrimitive)?.contentOrNull
            Box {
                PanelSecondaryButton(onClick = { expanded = true }, modifier = Modifier.fillMaxWidth()) {
                    Text("$label: ${options.find { it.first == current }?.second ?: current ?: "Выберите"}")
                }
                DropdownMenu(expanded, { expanded = false }) {
                    if (!required) DropdownMenuItem(text = { Text("Не изменять / не фильтровать") }, onClick = { onChange(null); expanded = false })
                    if (!required && schema.flag("nullable")) DropdownMenuItem(text = { Text("Очистить поле") }, onClick = { onChange(JsonNull); expanded = false })
                    options.forEach { (id, title) -> DropdownMenuItem(text = { Text(title) }, onClick = { onChange(JsonPrimitive(id)); expanded = false }) }
                }
            }
        }
        type == "boolean" -> {
            Column {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text(label, Modifier.weight(1f))
                    Switch(checked = (value as? JsonPrimitive)?.booleanOrNull == true, onCheckedChange = { onChange(JsonPrimitive(it)) })
                }
                schema.text("description")?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                if (!required && value != null && schema["default"] == null) TextButton(onClick = { onChange(null) }) { Text("Не изменять") }
            }
        }
        else -> {
            val secret = schema.flag("secret")
            val multiline = schema.flag("multiline")
            val content = (value as? JsonPrimitive)?.contentOrNull.orEmpty()
            PanelTextField(
                value = content,
                onValueChange = { entered ->
                    val next = when {
                        entered.isEmpty() && !required -> null
                        type == "integer" -> entered.toLongOrNull()?.let { JsonPrimitive(it) } ?: JsonPrimitive(entered)
                        type == "number" -> entered.toDoubleOrNull()?.let { JsonPrimitive(it) } ?: JsonPrimitive(entered)
                        else -> JsonPrimitive(entered)
                    }
                    onChange(next)
                },
                label = { Text(label + if (required) " *" else "") },
                modifier = Modifier.fillMaxWidth(), singleLine = !multiline, minLines = if (multiline) 3 else 1,
                textStyle = if (name == "content") TextStyle(fontFamily = FontFamily.Monospace) else LocalTextStyle.current,
                visualTransformation = if (secret) PasswordVisualTransformation() else VisualTransformation.None,
                keyboardOptions = KeyboardOptions(keyboardType = when { secret -> KeyboardType.Password; type in listOf("integer", "number") -> KeyboardType.Decimal; else -> KeyboardType.Text })
            )
            if (!required && schema.flag("nullable")) {
                Row {
                    TextButton(onClick = { onChange(null) }) { Text("Не изменять") }
                    TextButton(onClick = { onChange(JsonNull) }) { Text(if (value == JsonNull) "Будет очищено" else "Очистить") }
                }
            }
        }
    }
}
