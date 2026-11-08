package com.bot4vps.mobile.ui.settings

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.os.PersistableBundle
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.DialogProperties
import androidx.compose.ui.window.SecureFlagPolicy
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.bot4vps.mobile.data.api.NativePanelClient
import com.bot4vps.mobile.data.local.AppLockManager
import com.bot4vps.mobile.data.model.*
import com.bot4vps.mobile.data.repository.checkedObject
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

@Composable
fun MasterKeyViewDialog(client: NativePanelClient, protection: AppLockManager, onClose: () -> Unit) {
    val viewer = remember(client) { MasterKeyViewer({ path, body -> client.checkedObject("POST", path, body) }) }
    val state by viewer.state.collectAsState()
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    val close by rememberUpdatedState(onClose)
    var value by remember(state.step) { mutableStateOf("") }
    var copied by remember(state.step) { mutableStateOf(false) }
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    DisposableEffect(viewer, protection, lifecycle) {
        protection.protectScreen()
        val observer = LifecycleEventObserver { _, event -> if (event == Lifecycle.Event.ON_STOP) { viewer.close(); close() } }
        lifecycle.addObserver(observer)
        onDispose { lifecycle.removeObserver(observer); viewer.close(); protection.releaseScreen() }
    }
    LaunchedEffect(state.resendAt) {
        do { now = System.currentTimeMillis(); if (state.resendAt > now) delay(500) } while (state.resendAt > now)
    }
    fun submit() { if (!state.busy) scope.launch { if (state.step == MasterKeyStep.PASSWORD) viewer.begin(value) else viewer.confirm(value) } }
    fun dismiss() { viewer.close(); onClose() }
    AlertDialog(onDismissRequest = ::dismiss,
        properties = DialogProperties(securePolicy = SecureFlagPolicy.SecureOn),
        title = { Text(when (state.step) { MasterKeyStep.PASSWORD -> "Просмотр мастер-ключа"; MasterKeyStep.CODE -> "Подтверждение владельца"; MasterKeyStep.KEY -> "Мастер-ключ" }) },
        text = { Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            when (state.step) {
                MasterKeyStep.PASSWORD -> {
                    Text("Введите пароль учётной записи панели Bot4VPS.", style = MaterialTheme.typography.bodySmall)
                    OutlinedTextField(value, { value = it }, Modifier.fillMaxWidth(), label = { Text("Пароль панели") }, singleLine = true,
                        visualTransformation = PasswordVisualTransformation(), enabled = !state.busy,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Done), keyboardActions = KeyboardActions(onDone = { submit() }))
                }
                MasterKeyStep.CODE -> {
                    Text(if (state.channel == "totp") "Введите код из приложения-аутентификатора." else "Код отправлен в Telegram. Введите его для просмотра ключа.", style = MaterialTheme.typography.bodySmall)
                    OutlinedTextField(value, { value = it.filter { char -> char in '0'..'9' }.take(6) }, Modifier.fillMaxWidth(), label = { Text("Код подтверждения") }, singleLine = true, enabled = !state.busy,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword, imeAction = ImeAction.Done), keyboardActions = KeyboardActions(onDone = { submit() }))
                    if (state.channel == "telegram") {
                        val seconds = ((state.resendAt - now).coerceAtLeast(0) + 999) / 1000
                        TextButton(onClick = { scope.launch { viewer.resend() } }, enabled = !state.busy && seconds == 0L) { Text(if (seconds == 0L) "Отправить код ещё раз" else "Повторная отправка через $seconds с") }
                    }
                    if (state.error?.let { it.contains("начните заново", true) || it.contains("истёк", true) } == true) TextButton(onClick = { viewer.close() }, enabled = !state.busy) { Text("Начать заново") }
                }
                MasterKeyStep.KEY -> {
                    Text("Сохраните ключ в надёжном месте. Он нужен для восстановления доступа к зашифрованным данным панели.", style = MaterialTheme.typography.bodySmall)
                    Surface(shape = MaterialTheme.shapes.medium, color = MaterialTheme.colorScheme.surfaceVariant) {
                        Text(state.key.orEmpty(), Modifier.fillMaxWidth().padding(14.dp), fontFamily = FontFamily.Monospace)
                    }
                    OutlinedButton(onClick = {
                        val clip = ClipData.newPlainText("Мастер-ключ Bot4VPS", state.key.orEmpty())
                        clip.description.extras = PersistableBundle().apply { putBoolean("android.content.extra.IS_SENSITIVE", true) }
                        (context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager).setPrimaryClip(clip)
                        copied = true
                    }, modifier = Modifier.fillMaxWidth()) { Text(if (copied) "Ключ скопирован" else "Скопировать ключ") }
                }
            }
            state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            if (state.busy) LinearProgressIndicator(Modifier.fillMaxWidth())
        } },
        confirmButton = {
            if (state.step == MasterKeyStep.KEY) TextButton(onClick = ::dismiss) { Text("Закрыть") }
            else TextButton(onClick = ::submit, enabled = !state.busy && if (state.step == MasterKeyStep.PASSWORD) value.isNotEmpty() else value.length == 6) { Text(if (state.step == MasterKeyStep.PASSWORD) "Продолжить" else "Подтвердить") }
        }, dismissButton = { if (state.step != MasterKeyStep.KEY) TextButton(onClick = ::dismiss) { Text("Отмена") } })
}
