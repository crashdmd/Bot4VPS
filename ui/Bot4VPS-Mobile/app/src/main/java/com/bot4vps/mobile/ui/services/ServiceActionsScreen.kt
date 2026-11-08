package com.bot4vps.mobile.ui.services

import android.content.Context
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.bot4vps.mobile.data.api.*
import com.bot4vps.mobile.data.model.*
import com.bot4vps.mobile.data.repository.*
import com.bot4vps.mobile.ui.components.*
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.*
import javax.inject.Inject

@Serializable
data class ServiceActionChoice(val serviceId: String, val method: String, val suffix: String, val title: String, val description: String, val group: String) {
    fun operationId() = "$method /api/services/$serviceId/{server_id}/$suffix"
}
data class ServiceActionsState(val choices: List<ServiceActionChoice> = emptyList(), val serverName: String = "", val loading: Boolean = true, val busy: Boolean = false, val error: String? = null)

@HiltViewModel
class ServiceActionsViewModel @Inject constructor(saved: SavedStateHandle, @ApplicationContext private val context: Context,
    private val json: Json, private val contracts: ContractRepository, private val panel: NativePanelClient,
    private val workflow: NativeWorkflow) : ViewModel() {
    val kind = ServiceKind.find(saved.get<String>("serviceId")) ?: error("Сервис не найден")
    private val serverId: String = checkNotNull(saved["serverId"])
    private val _state = MutableStateFlow(ServiceActionsState(serverName = serverId))
    val state = _state.asStateFlow()
    init { viewModelScope.launch {
        try {
            val catalog = withContext(Dispatchers.IO) { context.assets.open("service_actions.json").bufferedReader().use { json.decodeFromString<List<ServiceActionChoice>>(it.readText()) } }
            val operations = contracts.load().operations.map { it.id }.toSet()
            val choices = catalog.filter { it.serviceId == kind.id && it.operationId() in operations }
            _state.update { it.copy(choices = choices, loading = false) }
            val server = panel.checkedObject("GET", "/api/servers/${encodeSegment(serverId)}")["server"] as? JsonObject
            _state.update { it.copy(serverName = server?.text("name") ?: serverId) }
        } catch (e: CancellationException) { throw e }
        catch (e: Exception) { _state.update { it.copy(loading = false, error = errorText(e)) } }
    } }
    fun open(choice: ServiceActionChoice, onOpen: (String) -> Unit) {
        if (_state.value.busy) return
        _state.update { it.copy(busy = true, error = null) }
        viewModelScope.launch {
            try {
                val names = if (choice.suffix == "export-zip") {
                    val profiles = panel.checkedObject("GET", "/api/services/wireguard/${encodeSegment(serverId)}/profiles").objects("profiles")
                    profiles.filter { it["managed"] != JsonPrimitive(false) }.mapNotNull { it.text("name") }.also {
                        require(it.isNotEmpty()) { "Нет профилей с доступными клиентскими конфигами" }
                    }
                } else emptyList()
                val values = buildJsonObject {
                    put("server_id", serverId)
                    if (choice.suffix == "export-zip") put("names", JsonArray(names.map(::JsonPrimitive)))
                }
                workflow.put(choice.operationId(), values)
                _state.update { it.copy(busy = false) }
                onOpen(choice.operationId())
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) { _state.update { it.copy(busy = false, error = errorText(e)) } }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ServiceActionsScreen(onBack: () -> Unit, onOperation: (String) -> Unit, viewModel: ServiceActionsViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    PanelScaffold(topBar = { PanelTopBar(title = { Text("Действия ${viewModel.kind.title}") }, navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Назад") } }) }) { padding ->
        LazyColumn(Modifier.fillMaxSize().padding(padding), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            item { Text(state.serverName, style = MaterialTheme.typography.titleLarge) }
            if (state.loading) item { CircularProgressIndicator() }
            state.error?.let { item { ErrorCard(it) } }
            state.choices.groupBy { it.group }.forEach { (group, choices) ->
                item { Text(group, style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(top = 10.dp)) }
                choices.forEach { choice -> item(key = choice.operationId()) { ActionRow(choice.title, choice.description, Icons.Default.Tune, { viewModel.open(choice, onOperation) }, enabled = !state.busy) } }
            }
        }
    }
}
