package com.bot4vps.mobile.ui.settings

import android.Manifest
import android.content.Intent
import android.os.Build
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.app.NotificationManagerCompat
import com.bot4vps.mobile.data.local.PreferencesManager
import com.bot4vps.mobile.data.model.notificationCategories
import com.bot4vps.mobile.notifications.PhoneNotificationService
import com.bot4vps.mobile.ui.components.*
import kotlinx.coroutines.launch

@Composable
fun PhoneNotificationsContent(modifier: Modifier, prefs: PreferencesManager) {
    val enabled by prefs.phoneNotifications.collectAsState(initial = false)
    val categories by prefs.phoneCategories.collectAsState(initial = emptySet())
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var denied by remember { mutableStateOf(false) }
    fun enable() { scope.launch { prefs.setPhoneNotifications(true); PhoneNotificationService.start(context) } }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        denied = !granted
        if (granted) enable()
    }
    LazyColumn(modifier, contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item { SettingsCard("Уведомления телефона", "Настройки действуют только на этом устройстве") {
            SettingRow("Получать уведомления", "Новые события панели в шторке телефона, в том числе в фоне") {
                Switch(enabled, { next ->
                    if (!next) scope.launch { prefs.setPhoneNotifications(false); PhoneNotificationService.stop(context) }
                    else if (NotificationManagerCompat.from(context).areNotificationsEnabled()) enable()
                    else if (Build.VERSION.SDK_INT >= 33) permission.launch(Manifest.permission.POST_NOTIFICATIONS)
                    else denied = true
                })
            }
            Text("Получение идёт через постоянное соединение с панелью. В шторке будет плашка службы. Интервал и выключатель Telegram на уведомления телефона не влияют.", style = MaterialTheme.typography.bodySmall)
            if (denied || enabled && !NotificationManagerCompat.from(context).areNotificationsEnabled()) {
                Text("Разрешите уведомления в настройках Android", color = MaterialTheme.colorScheme.error)
                TextButton(onClick = { context.startActivity(Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName)) }) { Text("Настройки Android") }
            }
        } }
        item { SettingsCategoryCard("Что присылать на телефон",
            "Включено ${notificationCategories.count { it.name in categories }} из ${notificationCategories.size}") {
            notificationCategories.forEachIndexed { index, category ->
                if (index > 0) HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                ToggleSetting(category.title, category.phoneDescription, category.name in categories, enabled,
                    { next -> scope.launch { prefs.setPhoneCategory(category.name, next) } })
            }
            Text("Выбор хранится на телефоне и не меняет категории Telegram или журнал событий.", style = MaterialTheme.typography.bodySmall)
        } }
    }
}
