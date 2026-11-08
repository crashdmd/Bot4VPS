package com.bot4vps.mobile.ui.dashboard

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.*
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.*
import androidx.lifecycle.compose.*
import com.bot4vps.mobile.data.api.*
import com.bot4vps.mobile.data.repository.JournalRepository
import com.bot4vps.mobile.ui.components.*
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import java.io.IOException
import javax.inject.Inject

data class JournalState(val lines: List<String> = emptyList(), val revision: Long = 0,
    val paused: Boolean = false, val live: Boolean = false, val message: String = "Подключаемся к журналу…", val error: String? = null, val login: Boolean = false)

@HiltViewModel
class ServiceJournalViewModel @Inject constructor(private val repo: JournalRepository) : ViewModel() {
    private val _state = MutableStateFlow(JournalState())
    val state = _state.asStateFlow()
    private val retry = MutableStateFlow(0)
    fun reconnect() { _state.update { it.copy(paused = false) }; retry.update { it + 1 } }
    fun toggle() { _state.update { it.copy(paused = !it.paused, live = false, message = if (!it.paused) "Обновление остановлено" else "Подключаемся к журналу…") }; retry.update { it + 1 } }
    suspend fun observe() = retry.collectLatest {
        if (_state.value.paused) return@collectLatest
        _state.update { it.copy(live=false, error=null, login=false, message="Подключаемся к журналу…") }
        repo.frames().retryWhen { cause, attempt ->
            if(cause is IOException && cause !is ApiError) {
                _state.update { it.copy(live=false, message="Связь прервалась. Переподключаемся…") }
                delay(((attempt+1)*1000).coerceAtMost(10000)); true
            } else false
        }.catch { e -> _state.update { it.copy(live=false, error=errorText(e), login=e is ApiError && e.status in setOf(401,403)) } }
            .collect { frame -> when(frame.event) {
                "hello" -> _state.update { it.copy(live=true, error=null, message="Прямой эфир · журнал службы Bot4VPS") }
                "line" -> _state.update { it.copy(lines=(it.lines+frame.data.take(16384)).takeLast(500), revision=it.revision+1, live=true) }
                "fail" -> _state.update { it.copy(live=false, error=frame.data, message="Журнал недоступен") }
                "end" -> _state.update { it.copy(live=false, message="Поток журнала завершён", error=if(frame.data.trim() == "0") null else "Журнал завершился с ошибкой (${frame.data})") }
            } }
    }
}

@Composable
fun ServiceJournalScreen(onBack: () -> Unit, onLogin: () -> Unit, viewModel: ServiceJournalViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    val list = rememberLazyListState()
    var follow by remember { mutableStateOf(true) }
    LaunchedEffect(lifecycle, viewModel) { lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) { viewModel.observe() } }
    LaunchedEffect(list.isScrollInProgress) {
        follow = !list.isScrollInProgress && (list.layoutInfo.totalItemsCount == 0 ||
            (list.layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: 0) >= list.layoutInfo.totalItemsCount-2)
    }
    LaunchedEffect(state.revision, follow) { if(follow && state.lines.isNotEmpty()) list.scrollToItem(state.lines.lastIndex) }
    PanelScaffold(topBar={ PanelTopBar(title={ Text("Журнал службы Bot4VPS") },
        navigationIcon={ IconButton(onClick=onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack,"Назад") } },
        actions={ IconButton(onClick=viewModel::reconnect) { Icon(Icons.Default.Refresh,"Переподключиться") } }) }) { padding ->
        Column(Modifier.fillMaxSize().padding(padding).padding(horizontal=12.dp), verticalArrangement=Arrangement.spacedBy(8.dp)) {
            TextButton(onClick = viewModel::toggle) { Text(if (state.paused) "Продолжить обновление" else "Остановить обновление") }
            Text(state.message, style=MaterialTheme.typography.bodySmall, color=MaterialTheme.colorScheme.onSurfaceVariant)
            state.error?.let { ErrorCard(it, viewModel::reconnect) }
            if(state.login) TextButton(onClick=onLogin) { Text("Войти заново") }
            if(state.lines.isEmpty() && state.error == null) Text("Ожидаем строки журнала…")
            if(!follow) TextButton(onClick={ follow=true }) { Text("К новым строкам ↓") }
            LazyColumn(Modifier.weight(1f).fillMaxWidth(), state=list, verticalArrangement=Arrangement.spacedBy(1.dp)) {
                items(state.lines) { line -> SelectionContainer { Text(line, fontFamily=FontFamily.Monospace, fontSize=11.sp, lineHeight=14.sp) } }
            }
        }
    }
}
