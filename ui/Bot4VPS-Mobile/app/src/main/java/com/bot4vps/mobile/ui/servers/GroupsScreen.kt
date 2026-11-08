package com.bot4vps.mobile.ui.servers

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.bot4vps.mobile.data.api.errorText
import com.bot4vps.mobile.data.local.PreferencesManager
import com.bot4vps.mobile.data.model.*
import com.bot4vps.mobile.data.repository.GroupRepository
import com.bot4vps.mobile.ui.components.*
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import javax.inject.Inject

@HiltViewModel
class GroupsViewModel @Inject constructor(val repo: GroupRepository, val prefs: PreferencesManager) : ViewModel() {
    val groups = repo.groups
    val display = prefs.groupDisplay.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), GroupDisplaySettings())
    var busy by mutableStateOf(false); private set
    var error by mutableStateOf<String?>(null); private set
    var notice by mutableStateOf<String?>(null); private set
    init { refresh() }
    fun refresh() = perform { repo.refresh() }
    fun save(old: String?, name: String, ssl: Boolean, done: () -> Unit = {}) = perform {
        repo.save(old, name, ssl); notice = if (old == null) "Группа создана" else "Группа сохранена"; done()
    }
    fun delete(group: ServerGroup) = perform { repo.delete(group); notice = "Группа удалена" }
    fun visible(name: String, shown: Boolean) = perform { prefs.editGroupDisplay { it.copy(hidden = if (shown) it.hidden - name else it.hidden + name) } }
    fun move(name: String, direction: Int) = perform {
        prefs.editGroupDisplay { current ->
            val order = current.ordered(groups.value.orEmpty().map { it.name }).toMutableList()
            val index = order.indexOf(name); val to = index + direction
            if (index >= 0 && to in order.indices) { order.removeAt(index); order.add(to, name) }
            current.copy(order = order)
        }
    }
    private fun perform(block: suspend () -> Unit) {
        if (busy) return
        busy = true; error = null; notice = null
        viewModelScope.launch {
            try { block() }
            catch (e: CancellationException) { throw e }
            catch (e: Exception) { error = errorText(e) }
            finally { busy = false }
        }
    }
}

@Composable
fun GroupsScreen(onBack: () -> Unit, viewModel: GroupsViewModel = hiltViewModel()) {
    val groups by viewModel.groups.collectAsStateWithLifecycle()
    val display by viewModel.display.collectAsStateWithLifecycle()
    var delete by remember { mutableStateOf<ServerGroup?>(null) }
    var newName by rememberSaveable { mutableStateOf("") }
    var newSsl by rememberSaveable { mutableStateOf(false) }
    val snack = remember { SnackbarHostState() }
    LaunchedEffect(viewModel.notice, viewModel.error) { (viewModel.error ?: viewModel.notice)?.let { snack.showSnackbar(it) } }
    delete?.let { group -> AlertDialog(onDismissRequest = { delete = null }, title = { Text("Удалить группу?") },
        text = { Text("Удалить пустую группу «${group.name}»?") },
        confirmButton = { TextButton(onClick = { delete = null; viewModel.delete(group) }) { Text("Удалить") } },
        dismissButton = { TextButton(onClick = { delete = null }) { Text("Отмена") } }) }
    PanelScaffold(topBar = { PanelTopBar(title = { Text("Настройки групп") }, navigationIcon = {
        IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Назад") }
    }) }, snackbarHost = { SnackbarHost(snack) }) { padding ->
        Refreshable(viewModel.busy, { if (!viewModel.busy) viewModel.refresh() }, Modifier.fillMaxSize().padding(padding)) {
        LazyColumn(Modifier.fillMaxSize().imePadding(), contentPadding = PaddingValues(16.dp), verticalArrangement = refreshArrangement(12.dp)) {
            if (groups == null) item { if (viewModel.busy) CircularProgressIndicator() else ErrorCard(viewModel.error ?: "Не удалось загрузить группы", viewModel::refresh) }
            item { Text("Группы серверов", style = MaterialTheme.typography.titleMedium) }
            if (groups?.isEmpty() == true) item { Text("Групп пока нет — создайте первую ниже", color = MaterialTheme.colorScheme.onSurfaceVariant) }
            items(groups.orEmpty(), key = { it.name }) { group ->
                var name by rememberSaveable(group.name) { mutableStateOf(group.name) }
                var ssl by rememberSaveable(group.name, group.ssl_monitor) { mutableStateOf(group.ssl_monitor) }
                val changed = name.trim() != group.name || ssl != group.ssl_monitor
                PanelCard {
                    PanelTextField(name, { name = it }, label = { Text("Название группы") }, singleLine = true, enabled = !viewModel.busy, modifier = Modifier.fillMaxWidth())
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(ssl, { ssl = it }, enabled = !viewModel.busy)
                        Text("Проверять SSL", Modifier.weight(1f))
                        Text("Серверов: ${group.servers}", style = MaterialTheme.typography.bodySmall)
                    }
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        TextButton(enabled = changed && name.isNotBlank() && !viewModel.busy, onClick = { viewModel.save(group.name, name, ssl) }) { Text("Сохранить") }
                        TextButton(enabled = group.servers == 0 && !viewModel.busy, onClick = { delete = group }) { Text("Удалить") }
                    }
                    if (group.servers > 0) Text("Для удаления сначала переместите серверы в другую группу", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            item { PanelCard("Новая группа") {
                PanelTextField(newName, { newName = it }, label = { Text("Название") }, singleLine = true, enabled = !viewModel.busy, modifier = Modifier.fillMaxWidth())
                Row(verticalAlignment = Alignment.CenterVertically) { Checkbox(newSsl, { newSsl = it }, enabled = !viewModel.busy); Text("Проверять SSL") }
                PanelButton(enabled = newName.isNotBlank() && !viewModel.busy, onClick = { viewModel.save(null, newName, newSsl) { newName = ""; newSsl = false } }) { Text("Создать группу") }
            } }
            item { Text("Меню серверов", style = MaterialTheme.typography.titleMedium); Text("Выберите видимые группы и их порядок. Настройка сохраняется для этой панели на устройстве.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
            val ordered = display.ordered(groups.orEmpty().map { it.name })
            items(ordered, key = { "display-$it" }) { name ->
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(name !in display.hidden, { viewModel.visible(name, it) }, enabled = !viewModel.busy)
                    Text(name, Modifier.weight(1f))
                    IconButton(enabled = ordered.indexOf(name) > 0 && !viewModel.busy, onClick = { viewModel.move(name, -1) }) { Icon(Icons.Default.KeyboardArrowUp, "Выше") }
                    IconButton(enabled = ordered.indexOf(name) < ordered.lastIndex && !viewModel.busy, onClick = { viewModel.move(name, 1) }) { Icon(Icons.Default.KeyboardArrowDown, "Ниже") }
                }
            }
        }
    }
    }
}
