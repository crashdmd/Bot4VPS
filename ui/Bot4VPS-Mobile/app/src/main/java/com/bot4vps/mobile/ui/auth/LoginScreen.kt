package com.bot4vps.mobile.ui.auth

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import com.bot4vps.mobile.ui.components.*
import com.bot4vps.mobile.ui.theme.OutlineVariant
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import com.bot4vps.mobile.ui.theme.Background
import com.bot4vps.mobile.ui.theme.CardBackground
import com.bot4vps.mobile.ui.theme.Error
import com.bot4vps.mobile.ui.theme.OnSurface
import com.bot4vps.mobile.ui.theme.OnSurfaceVariant
import com.bot4vps.mobile.ui.theme.Outline
import com.bot4vps.mobile.ui.theme.Primary
import com.bot4vps.mobile.ui.theme.TextDim
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.imePadding

@Composable
fun LoginScreen(
    onLoggedIn: () -> Unit,
    onChangeUrl: () -> Unit,
    onRecovery: () -> Unit = {},
    viewModel: LoginViewModel = hiltViewModel()
) {
    val state by viewModel.uiState.collectAsState()

    LaunchedEffect(state.loggedIn) {
        if (state.loggedIn) onLoggedIn()
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .imePadding()
            .padding(24.dp),
        contentAlignment = Alignment.Center
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .background(CardBackground, RoundedCornerShape(12.dp))
                .border(1.dp, OutlineVariant, RoundedCornerShape(12.dp))
                .padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Text(
                text = "Bot4VPS",
                fontSize = 28.sp,
                fontWeight = FontWeight.Bold,
                color = OnSurface
            )
            Text(
                text = if (state.pairingRequired) "Привязка телефона" else if (state.otpRequired) "Двухфакторная аутентификация" else "Вход в панель",
                fontSize = 14.sp,
                color = TextDim
            )

            Spacer(Modifier.height(8.dp))

            if (state.pairingRequired) {
                Text("Скопируйте код из локальной веб-панели: Настройки → Мобильное приложение. Код содержит адрес и ключ сервера; после привязки бот будет доверять этому телефону.",
                    color = OnSurfaceVariant, fontSize = 13.sp)
                PanelTextField(state.pairingCode, viewModel::onPairingCode, modifier = Modifier.fillMaxWidth(),
                    label = { Text("Код привязки") }, singleLine = true, enabled = !state.isLoading,
                    visualTransformation = PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
                    keyboardActions = KeyboardActions(onDone = { viewModel.pairPhone() }))
            } else if (!state.otpRequired) {
                PanelTextField(
                    value = state.username,
                    onValueChange = viewModel::onUsernameChange,
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("Логин") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Next),
                    shape = RoundedCornerShape(8.dp)
                )

                PanelTextField(
                    value = state.password,
                    onValueChange = viewModel::onPasswordChange,
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("Пароль") },
                    singleLine = true,
                    visualTransformation = PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(
                        keyboardType = KeyboardType.Password,
                        imeAction = ImeAction.Done
                    ),
                    keyboardActions = KeyboardActions(onDone = { viewModel.login() }),
                    shape = RoundedCornerShape(8.dp)
                )
            } else {
                PanelTextField(
                    value = state.otpCode,
                    onValueChange = viewModel::onOtpChange,
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("Код из приложения") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(
                        keyboardType = KeyboardType.Number,
                        imeAction = ImeAction.Done
                    ),
                    keyboardActions = KeyboardActions(onDone = { viewModel.submitOtp() }),
                    shape = RoundedCornerShape(8.dp)
                )
            }

            if (state.error != null) {
                Text(
                    text = state.error!!,
                    color = Error,
                    fontSize = 13.sp,
                    modifier = Modifier.fillMaxWidth()
                )
            }

            PanelButton(
                onClick = {
                    if (state.pairingRequired) viewModel.pairPhone() else if (state.otpRequired) viewModel.submitOtp() else viewModel.login()
                },
                enabled = !state.isLoading,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(48.dp),
                shape = RoundedCornerShape(8.dp)
            ) {
                if (state.isLoading) {
                    CircularProgressIndicator(
                        color = Color.White,
                        strokeWidth = 2.dp,
                        modifier = Modifier.height(22.dp)
                    )
                } else {
                    Text(
                        text = if (state.pairingRequired) "Привязать телефон" else if (state.otpRequired) "Подтвердить" else "Войти",
                        fontWeight = FontWeight.SemiBold
                    )
                }
            }

            TextButton(onClick = onChangeUrl) {
                Text("Изменить адрес панели", color = OnSurfaceVariant, fontSize = 13.sp)
            }
            if (!state.pairingRequired) {
                TextButton(onClick = viewModel::showPairing) { Text("Привязать через веб-панель") }
                if (state.otpRequired) TextButton(onClick = viewModel::resetOtp) { Text("Вернуться к вводу пароля") }
                TextButton(onClick = onRecovery) { Text("Восстановить доступ") }
            }
        }
    }
}
