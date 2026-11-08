package com.bot4vps.mobile.ui.auth

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.bot4vps.mobile.data.repository.AuthRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject
import com.bot4vps.mobile.data.api.errorText
import com.bot4vps.mobile.data.api.MobilePairingRequired
import retrofit2.HttpException
import kotlinx.coroutines.CancellationException

data class LoginUiState(
    val username: String = "",
    val password: String = "",
    val otpCode: String = "",
    val otpRequired: Boolean = false,
    val pairingRequired: Boolean = false,
    val pairingCode: String = "",
    val isLoading: Boolean = false,
    val error: String? = null,
    val loggedIn: Boolean = false
)

@HiltViewModel
class LoginViewModel @Inject constructor(
    private val authRepository: AuthRepository
) : ViewModel() {

    private val _uiState = MutableStateFlow(LoginUiState())
    val uiState: StateFlow<LoginUiState> = _uiState.asStateFlow()

    init {
        viewModelScope.launch {
            try {
                val me = authRepository.checkSession()
                if (me.authenticated) _uiState.update { it.copy(loggedIn = true) }
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) {
                if (needsPairing(e)) _uiState.update { it.copy(pairingRequired = true) }
            }
        }
    }
    private fun needsPairing(error: Exception) = error is MobilePairingRequired || error is javax.net.ssl.SSLHandshakeException || error is HttpException && error.code() == 428
    fun showPairing() { _uiState.update { it.copy(pairingRequired = true, otpRequired = false, error = null) } }
    fun onPairingCode(value: String) { _uiState.update { it.copy(pairingCode = value, error = null) } }
    fun pairPhone() {
        if (_uiState.value.isLoading) return
        val code = _uiState.value.pairingCode.trim()
        if (code.isBlank()) { _uiState.update { it.copy(error = "Введите одноразовый код привязки") }; return }
        _uiState.update { it.copy(isLoading = true, error = null) }
        viewModelScope.launch {
            try {
                authRepository.pairMobile(code)
                _uiState.update { it.copy(pairingRequired = false, pairingCode = "") }
                val me = authRepository.checkSession()
                _uiState.update { it.copy(loggedIn = me.authenticated) }
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) { _uiState.update { it.copy(error = errorText(e), pairingRequired = it.pairingRequired || needsPairing(e)) } }
            finally { _uiState.update { it.copy(isLoading = false) } }
        }
    }
    fun resetOtp() { _uiState.update { it.copy(otpRequired = false, otpCode = "", error = null) } }

    fun onUsernameChange(value: String) {
        _uiState.update { it.copy(username = value, error = null) }
    }

    fun onPasswordChange(value: String) {
        _uiState.update { it.copy(password = value, error = null) }
    }

    fun onOtpChange(value: String) {
        _uiState.update { it.copy(otpCode = value, error = null) }
    }

    suspend fun saveBaseUrl(url: String) = authRepository.setBaseUrl(url)
    suspend fun pairFromWeb(code: String) = authRepository.pairMobile(code)

    fun login() {
        if (_uiState.value.isLoading) return
        val state = _uiState.value
        if (state.username.isBlank() || state.password.isBlank()) {
            _uiState.update { it.copy(error = "Введите логин и пароль") }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }
            try {
                val response = authRepository.login(state.username, state.password)
                when {
                    response.otpRequired -> {
                        _uiState.update {
                            it.copy(isLoading = false, otpRequired = true, password = "")
                        }
                    }
                    response.ok -> {
                        _uiState.update {
                            it.copy(isLoading = false, loggedIn = true, password = "", otpCode = "")
                        }
                    }
                    else -> {
                        _uiState.update {
                            it.copy(
                                isLoading = false,
                                error = response.detail ?: "Неверный логин или пароль"
                            )
                        }
                    }
                }
            } catch (e: Exception) {
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        error = errorText(e), pairingRequired = needsPairing(e)
                    )
                }
            }
        }
    }

    fun submitOtp() {
        if (_uiState.value.isLoading) return
        val code = _uiState.value.otpCode
        if (code.isBlank()) {
            _uiState.update { it.copy(error = "Введите код 2FA") }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }
            try {
                val response = authRepository.loginOtp(code)
                if (response.ok) {
                    _uiState.update { it.copy(isLoading = false, loggedIn = true, password = "", otpCode = "") }
                } else {
                    _uiState.update {
                        it.copy(
                            isLoading = false,
                            error = response.detail ?: "Неверный код"
                        )
                    }
                }
            } catch (e: Exception) {
                _uiState.update {
                    it.copy(isLoading = false, error = errorText(e), pairingRequired = needsPairing(e))
                }
            }
        }
    }
}
