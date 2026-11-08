package com.bot4vps.mobile.ui.dashboard

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.RestartAlt
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.repeatOnLifecycle
import com.bot4vps.mobile.ui.components.*
import com.bot4vps.mobile.ui.settings.*
import androidx.compose.runtime.saveable.rememberSaveable

@Composable
fun HostMonitorScreen(onBack: () -> Unit, onTelegram: () -> Unit, onJournal: () -> Unit, onLogin: () -> Unit,
    promptRestart: Boolean = false, viewModel: DashboardViewModel = hiltViewModel(), restart: UpdatesViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(lifecycle, viewModel) { lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) { viewModel.observe() } }
    LaunchedEffect(lifecycle, restart) { lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) { restart.observe() } }
    var prompted by rememberSaveable { mutableStateOf(false) }
    LaunchedEffect(promptRestart, restart.busy, restart.update, restart.error) {
        if (promptRestart && !prompted && !restart.busy && (restart.update != null || restart.error != null)) {
            prompted = true
            if (!restart.active) restart.prepareRestart()
        }
    }
    UpdateDialogs(restart)
    PanelMaintenanceDialog(restart, onLogin, viewModel::refresh)
    PanelScaffold(topBar = {
        PanelTopBar(title = { Text("Мониторинг Bot4VPS") },
            navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Назад") } },
            actions = { IconButton(onClick = viewModel::refresh) { Icon(Icons.Default.Refresh, "Обновить") } })
    }) { padding ->
        Refreshable(state.loading, viewModel::refresh, Modifier.fillMaxSize().padding(padding)) {
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = refreshArrangement(12.dp)) {
            item { SystemOverview(state.system, state.samples, state.systemError, onTelegram, onJournal) }
            item { ActionRow("Перезапустить Bot4VPS", "Перезапуск службы с проверкой текущих задач", Icons.Default.RestartAlt,
                restart::prepareRestart, enabled = !restart.busy && !restart.active) }
            if (restart.progress == null) restart.error?.let { item { ErrorCard(it, restart::prepareRestart) } }
            if (restart.requiresLogin && restart.progress == null) item { TextButton(onClick = onLogin) { Text("Войти заново") } }
        }
    }
    }
}
