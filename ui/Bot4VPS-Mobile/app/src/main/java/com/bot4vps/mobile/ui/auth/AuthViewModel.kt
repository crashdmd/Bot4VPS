package com.bot4vps.mobile.ui.auth

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.bot4vps.mobile.data.repository.AuthRepository
import com.bot4vps.mobile.ui.navigation.Routes
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class AuthViewModel @Inject constructor(
    private val authRepository: AuthRepository
) : ViewModel() {

    private val _startDestination = MutableStateFlow<String?>(null)
    val startDestination: StateFlow<String?> = _startDestination.asStateFlow()

    init {
        viewModelScope.launch {
            val url = authRepository.baseUrl.first()
            _startDestination.value = if (url.isNullOrBlank()) {
                Routes.SETUP_URL
            } else {
                if (runCatching { authRepository.checkSession().authenticated }.getOrDefault(false)) Routes.MAIN else Routes.LOGIN
            }
        }
    }
}
