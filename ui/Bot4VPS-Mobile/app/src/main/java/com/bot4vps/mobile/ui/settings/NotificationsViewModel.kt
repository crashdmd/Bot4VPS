package com.bot4vps.mobile.ui.settings

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.bot4vps.mobile.data.api.errorText
import com.bot4vps.mobile.data.model.*
import com.bot4vps.mobile.data.repository.NotificationRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import kotlinx.serialization.json.*
import javax.inject.Inject

data class NotificationsState(val settings: NotificationSettings? = null, val loading: Boolean = false,
    val saving: Boolean = false, val error: String? = null, val notice: String? = null)

@HiltViewModel
class NotificationsViewModel @Inject constructor(private val repo: NotificationRepository) : ViewModel() {
    private val _state = MutableStateFlow(NotificationsState())
    val state = _state.asStateFlow()
    private var request: Job? = null
    init { refresh() }
    fun refresh() {
        if (_state.value.saving) return
        request?.cancel()
        request = viewModelScope.launch {
            _state.update { it.copy(loading = true, error = null) }
            try { val settings = repo.load(); _state.update { it.copy(settings = settings, loading = false) } }
            catch (e: CancellationException) { throw e }
            catch (e: Exception) { _state.update { it.copy(loading = false, error = errorText(e)) } }
        }
    }
    fun toggle(category: NotificationCategory, enabled: Boolean) {
        val old = _state.value.settings ?: return
        save(old.withEnabled(category, enabled)) { current ->
            val response = repo.category(category, enabled)
            if (category.monitor) current.copy(monitor = response["monitor"] as? JsonObject ?: current.monitor)
            else current.copy(categories = response["categories"] as? JsonObject ?: current.categories)
        }
    }
    fun channel(enabled: Boolean) {
        val old = _state.value.settings ?: return
        if (enabled && old.telegramIssue != null) {
            _state.update { it.copy(error = "${old.telegramIssue}. Сначала настройте Telegram.") }; return
        }
        save(old.copy(telegramChannel = enabled)) { current ->
            val response = repo.channel(enabled)
            current.copy(telegramChannel = (response["telegram_channel"] as? JsonPrimitive)?.booleanOrNull ?: enabled)
        }
    }
    fun interval(name: String, minutes: Int) {
        val old = _state.value.settings ?: return
        if (minutes !in 1..10080) { _state.update { it.copy(error = "Интервал должен быть от 1 до 10080 минут") }; return }
        save(old) { current ->
            val response = repo.interval(name, minutes)
            current.copy(monitor = response["monitor"] as? JsonObject ?: current.monitor)
        }
    }
    private fun save(optimistic: NotificationSettings, block: suspend (NotificationSettings) -> NotificationSettings) {
        val old = _state.value
        if (old.loading || old.saving) return
        _state.update { it.copy(settings = optimistic, saving = true, error = null, notice = null) }
        viewModelScope.launch {
            try { val settings = block(optimistic); _state.update { it.copy(settings = settings, saving = false, notice = "Сохранено") } }
            catch (e: CancellationException) { _state.update { it.copy(settings = old.settings, saving = false) }; throw e }
            catch (e: Exception) { _state.update { it.copy(settings = old.settings, saving = false, error = errorText(e)) } }
        }
    }
}
