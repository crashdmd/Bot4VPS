package com.bot4vps.mobile.ui.settings

import androidx.biometric.BiometricManager
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.compose.ui.window.SecureFlagPolicy
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.bot4vps.mobile.data.local.AppLockManager
import com.bot4vps.mobile.data.model.*
import com.bot4vps.mobile.ui.auth.PinEntryScreen
import com.bot4vps.mobile.ui.components.PanelSecondaryButton
import kotlinx.coroutines.delay

private enum class LockAction { ENABLE, CHANGE, DISABLE, BIOMETRIC_ON, BIOMETRIC_OFF }

@Composable
fun AppLockSettingsCard(manager: AppLockManager) {
    val state by manager.state.collectAsState()
    val request by manager.prompt.collectAsState()
    val context = LocalContext.current
    val biometricAvailable = BiometricManager.from(context).canAuthenticate(BiometricManager.Authenticators.BIOMETRIC_STRONG) == BiometricManager.BIOMETRIC_SUCCESS
    var action by remember { mutableStateOf<LockAction?>(null) }
    LaunchedEffect(state.revision, request) { action = null }
    fun open(value: LockAction) { manager.cancelPinChange(); manager.clearError(); action = value }
    SettingsCard("Защита приложения", "Вход по PIN-коду или биометрии на этом телефоне.") {
        SettingRow("Блокировка приложения", if (state.enabled) "PIN-код из 4 цифр. Блокировка при сворачивании" else "Создайте PIN-код из 4 цифр для входа в Bot4VPS") {
            Switch(state.enabled, { open(if (it) LockAction.ENABLE else LockAction.DISABLE) }, enabled = !state.busy && state.phase !in setOf(LockPhase.LOADING, LockPhase.UNAVAILABLE))
        }
        if (state.enabled) {
            HorizontalDivider()
            SettingRow("Вход по биометрии", if (biometricAvailable) "Отпечаток или защищённое распознавание лица вместо PIN-кода" else "Защищённая биометрия не настроена на телефоне") {
                Switch(state.biometricEnabled, { open(if (it) LockAction.BIOMETRIC_ON else LockAction.BIOMETRIC_OFF) }, enabled = !state.busy && (biometricAvailable || state.biometricEnabled))
            }
            HorizontalDivider()
            SettingRow("PIN-код приложения", "Для смены нужен текущий PIN-код") {
                PanelSecondaryButton(onClick = { open(LockAction.CHANGE) }, enabled = !state.busy) { Text("Изменить") }
            }
            Text("Содержимое скрыто в последних приложениях и на снимках экрана. Уведомления показывают только наличие события.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        if (action == null) state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
    }
    action?.let { selected -> LockPinDialog(selected, manager) { action = null; manager.cancelPinChange(); manager.clearError() } }
}

@Composable
fun AppPinSetupDialog(manager: AppLockManager) {
    LockPinDialog(LockAction.ENABLE, manager, migrating = true, onDismiss = manager::cancelPinSetup)
}

@Composable
private fun LockPinDialog(action: LockAction, manager: AppLockManager, migrating: Boolean = false, onDismiss: () -> Unit) {
    val state by manager.state.collectAsState()
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    val dismiss by rememberUpdatedState(onDismiss)
    var draft by remember { mutableStateOf(PinEntryDraft(if (action == LockAction.ENABLE) PinEntryStage.NEW else PinEntryStage.CURRENT)) }
    var mismatch by remember { mutableStateOf(false) }
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    val remaining = (state.retryAt - now).coerceIn(0, 300_000)
    DisposableEffect(manager, lifecycle) {
        manager.protectScreen()
        val observer = LifecycleEventObserver { _, event -> if (event == Lifecycle.Event.ON_STOP) dismiss() }
        lifecycle.addObserver(observer)
        onDispose { lifecycle.removeObserver(observer); manager.releaseScreen(); manager.cancelPinChange() }
    }
    LaunchedEffect(state.retryAt) {
        do { now = System.currentTimeMillis(); if (state.retryAt > now) delay(250) } while (state.retryAt > now)
    }
    LaunchedEffect(state.error) { if (state.error != null) draft = draft.copy(digits = "") }
    LaunchedEffect(state.pinChangeAuthorized) {
        if (action == LockAction.CHANGE && state.pinChangeAuthorized) draft = PinEntryDraft(PinEntryStage.NEW)
    }
    fun digit(value: Int) {
        if (state.busy || remaining > 0) return
        mismatch = false; manager.clearError()
        val updated = draft.digit(value)
        draft = updated
        if (!updated.complete) return
        when (updated.stage) {
            PinEntryStage.CURRENT -> when (action) {
                LockAction.CHANGE -> manager.authorizePinChange(updated.digits)
                LockAction.DISABLE -> manager.disable(updated.digits)
                LockAction.BIOMETRIC_ON, LockAction.BIOMETRIC_OFF -> manager.setBiometric(action == LockAction.BIOMETRIC_ON, updated.digits)
                LockAction.ENABLE -> Unit
            }
            PinEntryStage.NEW -> draft = updated.repeat()
            PinEntryStage.REPEAT -> if (updated.matches) manager.setPin(null, updated.firstPin, updated.digits)
                else { mismatch = true; draft = updated.copy(digits = "") }
        }
    }
    val title = when (action) {
        LockAction.ENABLE -> "Создать PIN-код"; LockAction.CHANGE -> "Изменить PIN-код"
        LockAction.DISABLE -> "Отключить блокировку"; LockAction.BIOMETRIC_ON -> "Включить биометрию"; LockAction.BIOMETRIC_OFF -> "Отключить биометрию"
    }
    val prompt = when (draft.stage) {
        PinEntryStage.CURRENT -> "Введите текущий PIN-код"
        PinEntryStage.NEW -> if (action == LockAction.CHANGE) "Введите новый PIN-код" else "Придумайте PIN-код"
        PinEntryStage.REPEAT -> if (action == LockAction.CHANGE) "Повторите новый PIN-код" else "Повторите PIN-код"
    }
    Dialog(onDismissRequest = { if (!state.busy) onDismiss() },
        properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false, securePolicy = SecureFlagPolicy.SecureOn)) {
        PinEntryScreen(title = title, prompt = prompt, digits = draft.digits.length, onDigit = ::digit,
            onDelete = { draft = draft.delete(); mismatch = false; manager.clearError() }, onBack = onDismiss,
            enabled = !state.busy && remaining == 0L, busy = state.busy, firstPinComplete = draft.stage == PinEntryStage.REPEAT,
            subtitle = if (draft.stage == PinEntryStage.NEW) (if (migrating) "Вход подтверждён. Создайте PIN-код из 4 цифр." else "4 цифры для входа в Bot4VPS") else null,
            error = if (remaining > 0) "Повторный ввод через ${(remaining + 999) / 1000} с" else if (mismatch) "PIN-коды не совпадают. Повторите ввод." else state.error)
    }
}
