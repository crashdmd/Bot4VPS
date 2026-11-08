package com.bot4vps.mobile.ui.settings

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.*
import androidx.compose.runtime.*
import android.widget.Toast
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import com.bot4vps.mobile.data.model.*
import com.bot4vps.mobile.data.local.MobileUpdateManager
import com.bot4vps.mobile.ui.components.*

@Composable
private fun VersionText(text: String) {
    SelectionContainer {
        Column(Modifier.fillMaxWidth().heightIn(max = 360.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            text.split("\n\n").forEach { paragraph ->
                val body = paragraph.trim()
                Text(body.replace(Regex("(?m)^#{1,6}\\s+"), "").replace("**", ""),
                    style = if (body.startsWith('#')) MaterialTheme.typography.titleSmall else MaterialTheme.typography.bodyMedium)
            }
        }
    }
}

@Composable
fun UpdatesContent(modifier: Modifier = Modifier, onLogin: () -> Unit, mobileUpdates: MobileUpdateManager, restartOnly:Boolean=false, onRestartFinished: () -> Unit = {}, viewModel: UpdatesViewModel = hiltViewModel()) {
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(lifecycle, viewModel) { lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) { viewModel.observe() } }
    UpdateDialogs(viewModel)
    LaunchedEffect(restartOnly, viewModel.progress?.phase) {
        if (restartOnly && viewModel.progress?.phase == MaintenancePhase.DONE && !viewModel.requiresLogin) {
            kotlinx.coroutines.delay(1000)
            viewModel.closeProgress()
            onRestartFinished()
        }
    }
    LazyColumn(modifier, contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        if(restartOnly) item { PanelCard("Перезапуск Bot4VPS") {
            Text("Перед перезапуском панель проверит текущие задачи и даст им время завершиться")
            PanelButton(onClick={ if(viewModel.update == null) viewModel.refresh() else viewModel.prepareRestart() },enabled=!viewModel.busy && !viewModel.active) { Text(if(viewModel.active) "Выполняется…" else if(viewModel.update == null) "Повторить загрузку" else "Перезапустить") }
            UpdateFeedback(viewModel)
        } }
        else item { SettingsCard("Панель Bot4VPS", "Обновление сервиса на хосте панели. Перед установкой проверяются активные задачи; результат отслеживается после перезапуска.") {
            SettingRow("Автоматическая проверка", "Проверять наличие новых версий в фоне") { Switch(viewModel.automatic, viewModel::automatic, enabled = viewModel.update != null && !viewModel.busy && !viewModel.active) }
            SettingRow("Текущая версия", viewModel.update?.text("current_version") ?: "Загрузка состояния") {
                if (viewModel.update != null) TextButton(onClick = viewModel::currentNotes, enabled = !viewModel.busy) { Text("Описание") }
            }
            viewModel.available?.let { StatusBadge("Доступна версия $it", StatusTone.WARNING) }
            if (viewModel.update?.text("status") == "failed") Text(viewModel.update?.text("last_error") ?: "Предыдущая операция завершилась с ошибкой", color = MaterialTheme.colorScheme.error)
            PanelButton(enabled = !viewModel.busy && !viewModel.active,
                onClick = { if(viewModel.update == null) viewModel.refresh() else if (viewModel.available == null) viewModel.check() else viewModel.prepare() }) {
                Text(when { viewModel.active -> "Выполняется…"; viewModel.busy -> "Подождите…"; viewModel.update == null -> "Повторить загрузку"; viewModel.available != null -> "Установить"; else -> "Проверить" })
            }
            UpdateFeedback(viewModel)
        } }
        if (viewModel.progress != null) item { UpdateProgress(viewModel, onLogin, autoClose = restartOnly) }
        if(viewModel.requiresLogin && viewModel.progress == null) item { TextButton(onClick=onLogin) { Text("Войти заново") } }
        if (!restartOnly) item { MobileUpdateCard(mobileUpdates) }
    }
}

@Composable
private fun UpdateFeedback(viewModel: UpdatesViewModel) {
    viewModel.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
    viewModel.message?.let { Text(it, color = MaterialTheme.colorScheme.secondary) }
}

@Composable
fun UpdateDialogs(viewModel: UpdatesViewModel) {
    val context = LocalContext.current
    LaunchedEffect(viewModel.latest) {
        if (viewModel.latest) {
            Toast.makeText(context, "Установлена последняя версия", Toast.LENGTH_SHORT).show()
            viewModel.dismissLatest()
        }
    }
    viewModel.notes?.let { notes -> AlertDialog(onDismissRequest = viewModel::dismissNotes,
        title = { Text("Описание версии ${notes.version}") }, text = { VersionText(notes.text) },
        confirmButton = { if (notes.current && !viewModel.active) TextButton(onClick = viewModel::rollbackVersions, enabled = !viewModel.busy) { Text("Откатить") } },
        dismissButton = { TextButton(onClick = viewModel::dismissNotes) { Text("Закрыть") } }) }
    viewModel.versions?.let { versions ->
        var selected by remember(versions) { mutableStateOf(versions.firstOrNull()) }
        var all by remember(versions) { mutableStateOf(false) }
        AlertDialog(onDismissRequest = viewModel::dismissVersions, title = { Text("Выбор версии для отката") },
            text = { Column {
                Text("Текущая версия: ${viewModel.update?.text("current_version") ?: "—"}")
                LazyColumn(Modifier.heightIn(max = 300.dp)) {
                    items(if (all) versions else versions.take(3), key = { it }) { version -> Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                        RadioButton(selected == version, { selected = version }, enabled = !viewModel.busy)
                        Text(version, Modifier.weight(1f))
                        TextButton(onClick = { viewModel.versionNotes(version) }, enabled = !viewModel.busy) { Text("Описание") }
                    } }
                    if (versions.size > 3 && !all) item { TextButton(onClick = { all = true }) { Text("Показать все версии") } }
                    if (versions.isEmpty()) item { Text("Нет доступных версий для отката") }
                }
            } }, confirmButton = { TextButton(enabled = selected != null && !viewModel.busy, onClick = { viewModel.prepare("rollback", selected) }) { Text("Продолжить") } },
            dismissButton = { TextButton(onClick = viewModel::dismissVersions) { Text("Отмена") } })
    }
    viewModel.confirmation?.let { ready -> AlertDialog(onDismissRequest = viewModel::dismissConfirmation,
        title = { Text(if(ready.kind == "restart") "Перезапустить Bot4VPS?" else if (ready.kind == "rollback") "Установить версию ${ready.notes.version}?" else "Обновить Bot4VPS до ${ready.notes.version}?") },
        text = { Column(Modifier.heightIn(max = 420.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Text(if(ready.kind == "restart") "Панель временно прервёт соединения и перезапустится" else "После установки панель будет перезапущена.")
            if (ready.notes.text.isNotBlank()) VersionText(ready.notes.text)
            Text(maintenanceTaskWarning(ready.preview))
        } }, confirmButton = { TextButton(enabled = !viewModel.busy, onClick = viewModel::install) { Text(if(ready.kind == "restart") "Перезапустить" else if (ready.kind == "rollback") "Откатить" else "Установить обновление") } },
        dismissButton = { TextButton(onClick = viewModel::dismissConfirmation, enabled = !viewModel.busy) { Text("Отмена") } }) }

}

@Composable
fun UpdateProgress(viewModel: UpdatesViewModel, onLogin: () -> Unit, autoClose: Boolean = false) {
    if (viewModel.progress != null) PanelCard("Состояние операции") {
        MaintenanceProgressBody(viewModel, onLogin, autoClose)
    }
}

@Composable
fun PanelMaintenanceDialog(viewModel: UpdatesViewModel, onLogin: () -> Unit, onFinished: () -> Unit = {}) {
    val progress = viewModel.progress ?: return
    val autoClose = viewModel.operationKind == "restart"
    LaunchedEffect(progress.phase, viewModel.requiresLogin, autoClose) {
        if (autoClose && progress.phase == MaintenancePhase.DONE && !viewModel.requiresLogin) {
            kotlinx.coroutines.delay(1000)
            viewModel.closeProgress()
            onFinished()
        }
    }
    AlertDialog(onDismissRequest = { if (viewModel.run == null) viewModel.closeProgress() },
        title = { Text(when(viewModel.operationKind) { "restart" -> "Перезапуск Bot4VPS"; "rollback" -> "Откат Bot4VPS"; else -> "Обновление Bot4VPS" }) },
        text = { Column(Modifier.fillMaxWidth().heightIn(max = 420.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            MaintenanceProgressBody(viewModel, onLogin, autoClose)
        } }, confirmButton = {})
}

@Composable
private fun MaintenanceProgressBody(viewModel: UpdatesViewModel, onLogin: () -> Unit, autoClose: Boolean) {
    var force by remember { mutableStateOf(false) }
    var elapsed by remember(viewModel.startedAt) { mutableLongStateOf(0L) }
    LaunchedEffect(viewModel.startedAt) {
        val start = viewModel.startedAt ?: return@LaunchedEffect
        while (true) {
            elapsed = ((System.currentTimeMillis() - start) / 1000).coerceAtLeast(0)
            kotlinx.coroutines.delay(1000)
        }
    }
        viewModel.progress?.let { progress -> Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(progress.message)
            if (viewModel.run != null) LinearProgressIndicator(Modifier.fillMaxWidth())
            if (viewModel.startedAt != null) Text("Прошло: $elapsed с", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (progress.phase == MaintenancePhase.DONE) Text("Связь с панелью восстановлена.")
            viewModel.error?.takeUnless { it == progress.message }?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            if (progress.phase == MaintenancePhase.WAITING) {
                Text("Осталось: ${progress.remaining} с")
                Column {
                    TextButton(onClick = { viewModel.control("cancel") }, enabled = !viewModel.busy) { Text("Отменить подготовку") }
                    TextButton(onClick = { force = true }, enabled = !viewModel.busy) { Text("Остановить сейчас") }
                }
            }
            if (viewModel.run != null) Text("Связь и результат проверяются автоматически. Выход с экрана не отменяет операцию.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            else if (!autoClose || progress.phase != MaintenancePhase.DONE) TextButton(onClick = viewModel::closeProgress) { Text("Закрыть") }
            if (viewModel.requiresLogin) TextButton(onClick = onLogin) { Text("Войти заново для проверки результата") }
        } }
    if (force) AlertDialog(onDismissRequest = { force = false }, title = { Text("Остановить задачи принудительно?") },
        text = { Text("Текущие и ожидающие задачи будут остановлены. Изменения на серверах не откатываются.") },
        confirmButton = { TextButton(onClick = { force = false; viewModel.control("force") }) { Text("Остановить и продолжить") } },
        dismissButton = { TextButton(onClick = { force = false }) { Text("Отмена") } })
}
