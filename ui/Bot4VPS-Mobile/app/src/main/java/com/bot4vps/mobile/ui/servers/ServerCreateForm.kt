package com.bot4vps.mobile.ui.servers

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import com.bot4vps.mobile.data.model.*
import com.bot4vps.mobile.ui.components.*
import com.bot4vps.mobile.ui.settings.SettingRow
import kotlinx.serialization.json.*

@Composable
fun ServerCreateForm(draft: JsonObject, choices: Map<String, List<Pair<String, String>>>, enabled: Boolean,
    onField: (String, JsonElement?) -> Unit) {
    @Composable
    fun field(name: String, title: String, numeric: Boolean = false, secret: Boolean = false, detail: String? = null) {
        PanelTextField(draft.text(name).orEmpty(), { entered ->
            onField(name, if (numeric) entered.toLongOrNull()?.let(::JsonPrimitive) ?: JsonPrimitive(entered) else JsonPrimitive(entered))
        }, modifier = Modifier.fillMaxWidth(), enabled = enabled, label = { Text(title) }, singleLine = true,
            visualTransformation = if (secret) PasswordVisualTransformation() else VisualTransformation.None,
            keyboardOptions = KeyboardOptions(keyboardType = if (numeric) KeyboardType.Number else if (secret) KeyboardType.Password else KeyboardType.Text),
            supportingText = detail?.let { { Text(it) } })
    }
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        PanelCard("Сервер") {
            field("name", "Название")
            field("host", "Адрес подключения", detail = "IP-адрес или домен сервера")
            SearchableChoice("Группа", draft.text("group"), choices["group"].orEmpty().ifEmpty { listOf("vps" to "vps") },
                { onField("group", it?.let(::JsonPrimitive)) }, enabled = enabled, emptyLabel = "Выберите группу")
        }
        PanelCard("Подключение по SSH") {
            field("port", "Порт", numeric = true)
            field("user", "Пользователь SSH")
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf("password" to "Пароль", "key" to "SSH-ключ").forEach { (id, title) ->
                    PanelTab(draft.text("auth_type") == id, { onField("auth_type", JsonPrimitive(id)) }, { Text(title) }, enabled = enabled)
                }
            }
            val keyAuth = draft.text("auth_type") == "key"
            if (keyAuth) SearchableChoice("SSH-ключ", draft.text("key_path"), choices["key_path"].orEmpty(),
                { onField("key_path", it?.let(::JsonPrimitive)) }, enabled = enabled, emptyLabel = "Выберите ключ")
            field("password", if (keyAuth) "Sudo-пароль" else "Пароль", secret = true,
                detail = if (keyAuth) "Для sudo у пользователя без прав root; можно оставить пустым" else null)
            Text("Подключение можно проверить вручную перед добавлением сервера.", style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        PanelCard("Сертификат SSL") {
            SettingRow("Проверять сертификат", "Следить за сроком действия сертификата сервера") {
                Switch(draft.flag("certificate_check"), { onField("certificate_check", JsonPrimitive(it)) }, enabled = enabled)
            }
            if (draft.flag("certificate_check")) field("ssl_host", "Домен сертификата",
                detail = "Подставляется из адреса подключения, если там указан домен")
        }
    }
}
