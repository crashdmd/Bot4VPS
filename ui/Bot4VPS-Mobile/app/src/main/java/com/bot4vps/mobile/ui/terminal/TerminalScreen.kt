package com.bot4vps.mobile.ui.terminal

import com.bot4vps.mobile.ui.components.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import com.bot4vps.mobile.data.api.*
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch
import kotlinx.serialization.json.*
import okhttp3.*
import javax.inject.Inject
import java.util.concurrent.atomic.AtomicInteger

@HiltViewModel
class TerminalViewModel @Inject constructor(savedState: SavedStateHandle, private val panel: NativePanelClient) : ViewModel() {
    private val serverId: String = checkNotNull(savedState["serverId"])
    private var socket: WebSocket? = null
    private val generation = AtomicInteger()
    private var columns = 80
    private var rows = 24
    private val channel = Channel<String>(Channel.UNLIMITED)
    val output = channel.receiveAsFlow()
    private val _status = MutableStateFlow("Подключение…")
    val status = _status.asStateFlow()
    fun connect() {
        if (socket != null) return
        val epoch = generation.incrementAndGet()
        viewModelScope.launch {
            try {
                val request = Request.Builder().url(panel.url("/api/servers/${encodeSegment(serverId)}/shell/ws")).build()
                if (epoch != generation.get()) return@launch
                socket = panel.httpClient(request.url).newWebSocket(request, object : WebSocketListener() {
                    override fun onOpen(webSocket: WebSocket, response: Response) { if (epoch == generation.get()) { _status.value = "Подключено"; resize(columns, rows) } else webSocket.close(1000,"Сессия уже закрыта") }
                    override fun onMessage(webSocket: WebSocket, text: String) { if (epoch == generation.get()) channel.trySend(text) }
                    override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) { if (epoch == generation.get()) { _status.value = errorText(t); socket = null } }
                    override fun onClosed(webSocket: WebSocket, code: Int, reason: String) { if (epoch == generation.get()) { _status.value = if (code == 4401) "Сессия истекла. Войдите заново." else "Сессия закрыта"; socket = null } }
                })
            } catch (e: Exception) { _status.value = errorText(e) }
        }
    }
    fun send(data: String) { socket?.send(buildJsonObject { put("type", "input"); put("data", data) }.toString()) }
    fun resize(cols: Int, rows: Int) { columns = cols; this.rows = rows; socket?.send(buildJsonObject { put("type", "resize"); put("cols", cols); put("rows", rows) }.toString()) }
    fun close() { generation.incrementAndGet(); socket?.close(1000, "Клиент закрыл терминал"); socket = null }
    override fun onCleared() { close(); channel.close() }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TerminalScreen(onBack: () -> Unit, viewModel: TerminalViewModel = hiltViewModel()) {
    val status by viewModel.status.collectAsState()
    var terminal by remember { mutableStateOf<NativeTerminalView?>(null) }
    var ctrl by remember { mutableStateOf(false) }
    val keyboard = LocalSoftwareKeyboardController.current
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    DisposableEffect(lifecycle, viewModel) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_START) viewModel.connect()
            if (event == Lifecycle.Event.ON_STOP) { terminal?.hideKeyboard(); keyboard?.hide(); viewModel.close() }
        }
        lifecycle.addObserver(observer)
        if (lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)) viewModel.connect()
        onDispose { terminal?.hideKeyboard(); keyboard?.hide(); lifecycle.removeObserver(observer); viewModel.close() }
    }
    LaunchedEffect(viewModel) { viewModel.output.collect { terminal?.append(it) } }
    PanelScaffold(topBar = { PanelTopBar(title = { Text("SSH-терминал") }, navigationIcon = { TextButton(onClick = { terminal?.hideKeyboard(); keyboard?.hide(); onBack() }) { Text("Назад") } }, actions = { TextButton(onClick = { viewModel.close(); viewModel.connect() }) { Text("Подключить") } }) }) { padding ->
        Column(Modifier.fillMaxSize().padding(padding).consumeWindowInsets(padding).imePadding()) {
            Text(status, Modifier.padding(horizontal = 12.dp, vertical = 2.dp), style = MaterialTheme.typography.bodySmall)
            AndroidView(factory = { context -> NativeTerminalView(context).apply { onInput = viewModel::send; onResize = viewModel::resize; input.onCtrlChanged = { ctrl = it }; terminal = this } }, modifier = Modifier.weight(1f).fillMaxWidth())
            Row(Modifier.fillMaxWidth().height(48.dp).horizontalScroll(rememberScrollState())) {
                TextButton(onClick = { terminal?.input?.toggleCtrl() }, contentPadding = PaddingValues(horizontal = 8.dp),
                    colors = ButtonDefaults.textButtonColors(containerColor = if (ctrl) MaterialTheme.colorScheme.primaryContainer else androidx.compose.ui.graphics.Color.Transparent)) { Text(if (ctrl) "Ctrl ✓" else "Ctrl") }
                listOf("Esc" to "\u001b", "Tab" to "\t", "↑" to "\u001b[A", "↓" to "\u001b[B", "←" to "\u001b[D", "→" to "\u001b[C", "Enter" to "\r").forEach { (label, value) ->
                    TextButton(onClick = { terminal?.sendInput(value) }, contentPadding = PaddingValues(horizontal = 8.dp)) { Text(label) }
                }
            }
        }
    }
}
