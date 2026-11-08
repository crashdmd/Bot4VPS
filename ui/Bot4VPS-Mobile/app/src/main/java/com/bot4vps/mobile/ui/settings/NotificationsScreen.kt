package com.bot4vps.mobile.ui.settings

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.bot4vps.mobile.data.model.*
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.awaitCancellation
import com.bot4vps.mobile.ui.components.*

fun androidx.compose.foundation.lazy.LazyListScope.telegramDeliveryItems(state: NotificationsState, viewModel: NotificationsViewModel) {
    val settings = state.settings
    val editable = !state.loading && !state.saving
    if (state.loading || state.saving) item { LinearProgressIndicator(Modifier.fillMaxWidth()) }
    state.error?.let { item { ErrorCard(it, if (settings == null) viewModel::refresh else null) } }
    state.notice?.let { item { Text(it, color = MaterialTheme.colorScheme.primary) } }
    if (settings != null) {
        item { SettingsCard("Доставка в Telegram", "Когда и как отправлять события панели получателю бота") {
            ToggleSetting("Оповещать в Telegram", "Присылать уведомления в Telegram. Бот и журнал событий продолжают работать при выключенной доставке.", settings.telegramChannel, editable, viewModel::channel)
            if (settings.telegramChannel && settings.telegramIssue != null) Text(settings.telegramIssue, color = MaterialTheme.colorScheme.error)
            var interval by rememberSaveable(settings.interval("online")) { mutableStateOf(settings.interval("online").toString()) }
            val value = interval.toIntOrNull()
            val changed = value != settings.interval("online")
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                PanelTextField(interval, { interval = it }, label = { Text("Интервал, мин") }, singleLine = true,
                    enabled = editable && settings.telegramChannel, isError = value == null || value !in 1..10080,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number, imeAction = ImeAction.Done),
                    keyboardActions = KeyboardActions(onDone = { if (changed && value != null && editable) viewModel.interval("online", value) }), modifier = Modifier.weight(1f))
                if (changed) TextButton(onClick = { value?.let { viewModel.interval("online", it) } }, enabled = editable && settings.telegramChannel && value != null && value in 1..10080) { Text("Применить") }
            }
            Text("Интервал задаёт фоновую проверку Telegram. Уведомления телефона получают события из потока панели независимо от этого интервала. Если сервер вернулся раньше этого срока, отдельное уведомление об офлайне не создаётся.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        } }
        item { SettingsCategoryCard("Категории Telegram и журнала",
            "Включено ${notificationCategories.count(settings::enabled)} из ${notificationCategories.size}") {
        Text("Переключатели сохраняются сразу. Выключенная категория оставляет события в журнале прочитанными и отключает оповещения о них.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        notificationCategories.forEachIndexed { index, category ->
            if (index > 0) HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            ToggleSetting(category.title, category.description, settings.enabled(category), editable, { viewModel.toggle(category, it) })
            if (category.name == "ssl") {
                val current = settings.interval("ssl")
                var menu by remember { mutableStateOf(false) }
                Box {
                    PanelSecondaryButton(onClick = { menu = true }, enabled = editable && settings.enabled(category)) { Text(sslIntervals[current] ?: "Сейчас: $current мин"); Icon(Icons.Default.ExpandMore, null) }
                    DropdownMenu(menu, { menu = false }) { sslIntervals.forEach { (minutes, title) -> DropdownMenuItem(text = { Text(title) }, onClick = { menu = false; viewModel.interval("ssl", minutes) }) } }
                }
            }
        }
        } }
    }
}


@Composable
fun ToggleSetting(title: String, description: String, checked: Boolean, enabled: Boolean, onChange: (Boolean) -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(title, style = MaterialTheme.typography.titleSmall)
            Text(description, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Switch(checked, onChange, enabled = enabled)
    }
}
