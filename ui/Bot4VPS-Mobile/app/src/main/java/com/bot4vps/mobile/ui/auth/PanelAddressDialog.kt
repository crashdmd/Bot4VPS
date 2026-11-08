package com.bot4vps.mobile.ui.auth

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import com.bot4vps.mobile.data.api.errorText
import com.bot4vps.mobile.data.repository.AuthRepository
import com.bot4vps.mobile.ui.components.PanelTextField
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class PanelAddressViewModel @Inject constructor(val auth: AuthRepository) : ViewModel()

@Composable
fun PanelAddressDialog(onDismiss: () -> Unit, onSaved: () -> Unit, viewModel: PanelAddressViewModel = hiltViewModel()) {
    val current by viewModel.auth.baseUrl.collectAsState(initial = null)
    var draft by remember { mutableStateOf("") }
    var edited by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(current) { if (!edited) draft = current.orEmpty() }
    AlertDialog(onDismissRequest = { if (!busy) onDismiss() },
        title = { Text("Адрес панели") },
        text = { Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("Введите новый адрес. После сохранения потребуется вход в панель.")
            PanelTextField(draft, { draft = it; edited = true; error = null }, modifier = Modifier.fillMaxWidth(),
                label = { Text("Адрес") }, placeholder = { Text("https://сервер:порт") }, singleLine = true,
                enabled = !busy, isError = error != null, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri))
            error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        } },
        confirmButton = { TextButton(enabled = !busy && draft.isNotBlank(), onClick = {
            scope.launch {
                busy = true
                try { viewModel.auth.setBaseUrl(draft); onSaved() }
                catch (e: Exception) { error = errorText(e) }
                finally { busy = false }
            }
        }) { Text(if (busy) "Сохранение…" else "Сохранить") } },
        dismissButton = { TextButton(onClick = onDismiss, enabled = !busy) { Text("Отмена") } })
}
