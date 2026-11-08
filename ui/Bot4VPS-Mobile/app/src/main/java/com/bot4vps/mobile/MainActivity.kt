package com.bot4vps.mobile

import android.os.Bundle
import android.content.Intent
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.Lifecycle
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.*
import androidx.core.app.NotificationManagerCompat
import com.bot4vps.mobile.notifications.PhoneNotificationService
import androidx.fragment.app.FragmentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.ui.Modifier
import com.bot4vps.mobile.ui.navigation.Bot4VpsNavHost
import com.bot4vps.mobile.ui.components.PanelBackground
import com.bot4vps.mobile.ui.theme.Background
import com.bot4vps.mobile.ui.theme.Bot4VpsTheme
import dagger.hilt.android.AndroidEntryPoint
import com.bot4vps.mobile.data.local.PreferencesManager
import com.bot4vps.mobile.data.local.AppLockManager
import com.bot4vps.mobile.data.local.MobileUpdateManager
import com.bot4vps.mobile.ui.settings.MobileUpdateDialog
import androidx.compose.runtime.LaunchedEffect
import com.bot4vps.mobile.ui.auth.AppLockScreen
import com.bot4vps.mobile.ui.auth.BiometricPromptHost
import android.view.WindowManager
import androidx.core.view.WindowInsetsCompat
import androidx.compose.runtime.saveable.rememberSaveableStateHolder
import javax.inject.Inject
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.SideEffect
import androidx.core.view.WindowCompat
import androidx.compose.foundation.isSystemInDarkTheme

@AndroidEntryPoint
class MainActivity : FragmentActivity() {
    @Inject lateinit var preferences: PreferencesManager
    @Inject lateinit var appLock: AppLockManager
    @Inject lateinit var mobileUpdates: MobileUpdateManager
    private val pendingEvent = MutableStateFlow<String?>(null)
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        pendingEvent.value = intent.getStringExtra("event_id")
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                combine(preferences.phoneNotifications.distinctUntilChanged(), preferences.username.distinctUntilChanged()) { enabled, user -> enabled && user != null }
                    .distinctUntilChanged().collect { enabled ->
                        if (enabled && NotificationManagerCompat.from(this@MainActivity).areNotificationsEnabled()) PhoneNotificationService.start(this@MainActivity)
                        else PhoneNotificationService.stop(this@MainActivity)
                    }
            }
        }
        enableEdgeToEdge()
        setContent {
            val protection by appLock.state.collectAsState()
            val secureViews by appLock.secureViews.collectAsState()
            val theme by preferences.theme.collectAsState(initial = "dark")
            LaunchedEffect(protection.allowsContent, protection.foreground) {
                if (protection.allowsContent && protection.foreground) mobileUpdates.check(manual = false)
            }
            SideEffect {
                if (protection.protectsContent || secureViews > 0) window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
                else window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE)
                val bars = WindowCompat.getInsetsController(window, window.decorView)
                bars.isAppearanceLightStatusBars = theme == "light"
                bars.isAppearanceLightNavigationBars = theme == "light"
            }
            Bot4VpsTheme(darkTheme = theme != "light", blueTheme = theme == "glass") {
                BiometricPromptHost(this@MainActivity, appLock)
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = Background
                ) {
                    val eventId by pendingEvent.collectAsState()
                    val contentState = rememberSaveableStateHolder()
                    if (protection.allowsContent) contentState.SaveableStateProvider("panel") {
                        PanelBackground { Bot4VpsNavHost(eventId = eventId, onEventConsumed = { pendingEvent.value = null; intent.removeExtra("event_id"); intent.data = null }) }
                        MobileUpdateDialog(mobileUpdates)
                    } else AppLockScreen(appLock, onClose = { finish() })
                }
            }
        }
    }
    override fun onStart() { super.onStart(); appLock.foreground() }
    override fun onStop() {
        if (!isChangingConfigurations) {
            appLock.background()
            WindowCompat.getInsetsController(window, window.decorView).hide(WindowInsetsCompat.Type.ime())
            window.decorView.clearFocus()
        }
        super.onStop()
    }
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        if (appLock.state.value.protectsContent) appLock.lock()
        setIntent(intent)
        pendingEvent.value = intent.getStringExtra("event_id")
    }
}
