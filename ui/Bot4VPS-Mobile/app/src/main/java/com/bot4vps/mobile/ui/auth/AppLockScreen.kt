package com.bot4vps.mobile.ui.auth

import androidx.activity.compose.BackHandler
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import com.bot4vps.mobile.R
import com.bot4vps.mobile.data.local.AppLockManager
import com.bot4vps.mobile.data.local.AppLockState
import com.bot4vps.mobile.data.model.LockPhase
import com.bot4vps.mobile.data.model.LockPin
import com.bot4vps.mobile.ui.settings.AppPinSetupDialog
import kotlinx.coroutines.delay

@Composable
fun BiometricPromptHost(activity: FragmentActivity, manager: AppLockManager) {
    val request by manager.prompt.collectAsState()
    request?.let { pending ->
        DisposableEffect(activity, manager, pending.cipher) {
            val enrollment = pending.enrollmentAlias != null
            val prompt = BiometricPrompt(activity, ContextCompat.getMainExecutor(activity), object : BiometricPrompt.AuthenticationCallback() {
                override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                    val cipher = result.cryptoObject?.cipher
                    if (cipher === pending.cipher) manager.biometricResult(cipher)
                    else manager.biometricError(pending.cipher, "Не удалось подтвердить биометрию. Повторите вход.")
                }
                override fun onAuthenticationError(errorCode: Int, errString: CharSequence) {
                    val canceled = errorCode in setOf(BiometricPrompt.ERROR_USER_CANCELED, BiometricPrompt.ERROR_CANCELED, BiometricPrompt.ERROR_NEGATIVE_BUTTON)
                    manager.biometricError(pending.cipher, if (canceled) null else if (enrollment)
                        "Не удалось включить биометрию. Проверьте отпечаток в настройках Android." else "Биометрия недоступна. Введите PIN-код.")
                }
            })
            try {
                prompt.authenticate(BiometricPrompt.PromptInfo.Builder()
                    .setTitle(if (enrollment) "Включить биометрию" else "Вход в Bot4VPS")
                    .setSubtitle("Подтвердите отпечаток или биометрию телефона")
                    .setAllowedAuthenticators(BiometricManager.Authenticators.BIOMETRIC_STRONG)
                    .setNegativeButtonText(if (enrollment) "Отмена" else "Ввести PIN-код").build(), BiometricPrompt.CryptoObject(pending.cipher))
            } catch (_: Exception) {
                manager.biometricError(pending.cipher, if (enrollment) "Не удалось открыть подтверждение биометрии." else "Не удалось открыть биометрию. Введите PIN-код.")
            }
            onDispose { prompt.cancelAuthentication() }
        }
    }
}

@Composable
fun AppLockScreen(manager: AppLockManager, onClose: () -> Unit) {
    val state by manager.state.collectAsState()
    val context = LocalContext.current
    var pin by remember { mutableStateOf("") }
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    val remaining = (state.retryAt - now).coerceIn(0, 300_000)
    val biometricAvailable = remember(state.generation) {
        BiometricManager.from(context).canAuthenticate(BiometricManager.Authenticators.BIOMETRIC_STRONG) == BiometricManager.BIOMETRIC_SUCCESS
    }
    LaunchedEffect(state.retryAt) {
        do { now = System.currentTimeMillis(); if (state.retryAt > now) delay(250) } while (state.retryAt > now)
    }
    LaunchedEffect(state.generation, state.foreground) {
        pin = ""
        if (state.phase == LockPhase.LOCKED && state.foreground && !state.needsPinSetup) {
            if (state.biometricEnabled && biometricAvailable && !state.usePin) manager.biometricUnlock()
            else manager.showPin()
        }
    }
    LaunchedEffect(state.error, state.needsPinSetup) { if (state.error != null || state.needsPinSetup) pin = "" }
    BackHandler { onClose() }
    if (state.phase == LockPhase.LOCKED && !state.legacyPassword) {
        PinEntryScreen(title = "Bot4VPS", prompt = "Введите PIN-код", digits = pin.length,
            onDigit = { value ->
                if (!state.busy && remaining == 0L && pin.length < LockPin.LENGTH) {
                    manager.clearError(); pin += value
                    if (pin.length == LockPin.LENGTH) manager.unlock(pin)
                }
            }, onDelete = { pin = pin.dropLast(1); manager.clearError() }, onBack = onClose,
            enabled = !state.busy && remaining == 0L, busy = state.busy,
            error = if (remaining > 0) "Повторный ввод через ${(remaining + 999) / 1000} с" else state.error,
            onBiometric = if (state.biometricEnabled && biometricAvailable) manager::biometricUnlock else null)
        return
    }
    Column(Modifier.fillMaxSize().systemBarsPadding().imePadding().verticalScroll(rememberScrollState()).padding(28.dp),
        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
        Image(painterResource(R.drawable.ic_launcher_foreground), "Bot4VPS", Modifier.size(108.dp))
        Text("Bot4VPS", style = MaterialTheme.typography.headlineMedium)
        Spacer(Modifier.height(12.dp))
        when (state.phase) {
            LockPhase.LOADING -> { Text("Проверка защиты приложения…"); Spacer(Modifier.height(16.dp)); CircularProgressIndicator() }
            LockPhase.UNAVAILABLE -> {
                Text(state.error ?: "Настройки защиты недоступны", color = MaterialTheme.colorScheme.error)
                Spacer(Modifier.height(16.dp))
                Button(onClick = manager::reload, enabled = !state.busy) { Text("Повторить проверку") }
                TextButton(onClick = onClose) { Text("Закрыть приложение") }
            }
            else -> LegacyPasswordEntry(manager, state, pin, { pin = it }, remaining)
        }
    }
    if (state.needsPinSetup) AppPinSetupDialog(manager)
}

@Composable
private fun LegacyPasswordEntry(manager: AppLockManager, state: AppLockState, password: String, onPassword: (String) -> Unit, remaining: Long) {
    val focus = remember { FocusRequester() }
    val keyboard = LocalSoftwareKeyboardController.current
    LaunchedEffect(state.usePin, state.busy, state.foreground, state.needsPinSetup, remaining > 0) {
        if (state.foreground && state.usePin && !state.busy && !state.needsPinSetup && remaining == 0L) {
            withFrameNanos { }; focus.requestFocus(); withFrameNanos { }; keyboard?.show()
        } else keyboard?.hide()
    }
    DisposableEffect(Unit) { onDispose { keyboard?.hide() } }
    Text("Подтвердите пароль предыдущей версии, чтобы создать PIN-код", color = MaterialTheme.colorScheme.onSurfaceVariant)
    Spacer(Modifier.height(24.dp))
    val enabled = !state.busy && remaining == 0L && !state.needsPinSetup
    fun submit() { if (enabled && password.isNotEmpty()) manager.unlock(password) }
    OutlinedTextField(password, { if (it.length <= 256) { onPassword(it); manager.clearError() } },
        modifier = Modifier.fillMaxWidth().focusRequester(focus), label = { Text("Пароль предыдущей версии") }, singleLine = true,
        visualTransformation = PasswordVisualTransformation(),
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
        keyboardActions = KeyboardActions(onDone = { submit() }), enabled = enabled)
    if (remaining > 0) Text("Повторный ввод через ${(remaining + 999) / 1000} с", Modifier.padding(top = 12.dp), color = MaterialTheme.colorScheme.error)
    state.error?.let { Text(it, Modifier.padding(top = 12.dp), color = MaterialTheme.colorScheme.error) }
    Spacer(Modifier.height(16.dp))
    Button(onClick = ::submit, enabled = enabled && password.isNotEmpty(), modifier = Modifier.fillMaxWidth()) {
        if (state.busy) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp) else Text("Войти")
    }
    if (state.biometricEnabled) TextButton(onClick = manager::biometricUnlock, enabled = !state.busy) { Text("Войти по биометрии") }
}
