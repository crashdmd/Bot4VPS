package com.bot4vps.mobile.ui.settings

import android.content.Intent
import android.net.Uri
import android.provider.Settings
import android.widget.Toast
import androidx.core.content.FileProvider
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.bot4vps.mobile.BuildConfig
import com.bot4vps.mobile.data.local.MobileUpdateManager
import com.bot4vps.mobile.ui.components.PanelSecondaryButton

@Composable
fun MobileUpdateCard(manager: MobileUpdateManager) {
    val state by manager.state.collectAsState()
    val automatic by manager.prefs.appAutoUpdate.collectAsState(initial = true)
    SettingsCard("Приложение Bot4VPS Mobile", "Обновление Android-приложения с GitHub независимо от версии панели.") {
        SettingRow("Текущая версия", BuildConfig.VERSION_NAME)
        HorizontalDivider()
        SettingRow("Проверять автоматически", "При открытии приложения, не чаще одного раза в сутки") {
            Switch(automatic, manager::automatic)
        }
        HorizontalDivider()
        PanelSecondaryButton(onClick = { if (state.release != null) manager.show() else manager.check() }, enabled = !state.checking && state.progress == null) {
            Text(if (state.checking) "Проверка…" else state.release?.let { "Доступна версия ${it.version}" } ?: "Проверить обновление APK")
        }
        state.error?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error) }
        Text("Скачивание начинается после подтверждения. Установку обновления подтверждает Android.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
fun MobileUpdateDialog(manager: MobileUpdateManager) {
    val state by manager.state.collectAsState()
    val context = LocalContext.current
    LaunchedEffect(state.notice) { state.notice?.let { Toast.makeText(context, it, Toast.LENGTH_SHORT).show(); manager.consumeNotice() } }
    val release = state.release
    if (state.dialog && release != null) AlertDialog(onDismissRequest = manager::close,
        title = { Text("Bot4VPS Mobile ${release.version}") },
        text = { Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("Новая версия приложения. Версия панели Bot4VPS не изменится.")
            Text(release.notes.ifBlank { "Описание изменений не опубликовано." }, style = MaterialTheme.typography.bodySmall)
            Text("APK: ${"%.1f".format(release.size / 1048576.0)} МБ. Проверяются размер, контрольная сумма и сертификат подписи.", style = MaterialTheme.typography.bodySmall)
            state.progress?.let { LinearProgressIndicator(progress = { it / 100f }, modifier = Modifier.fillMaxWidth()); Text("Скачивание: $it%") }
            if (state.file != null) Text("APK проверен. Можно установить обновление.")
            state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        } },
        confirmButton = { TextButton(enabled = state.progress == null, onClick = {
            val file = state.file
            if (file == null) manager.download()
            else try {
                check(file.isFile) { "APK удалён из кэша. Скачайте его заново." }
                if (!context.packageManager.canRequestPackageInstalls()) {
                    context.startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${context.packageName}")))
                    Toast.makeText(context, "Разрешите установку, вернитесь и нажмите «Установить»", Toast.LENGTH_LONG).show()
                } else {
                    val uri = FileProvider.getUriForFile(context, "${context.packageName}.updates", file)
                    context.startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(uri, "application/vnd.android.package-archive")
                        .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION))
                }
            } catch (e: Exception) { manager.error(e.message ?: "Не удалось открыть установку APK") }
        }) { Text(if (state.file == null) "Скачать APK" else "Установить") } },
        dismissButton = { TextButton(onClick = manager::close) { Text(if (state.progress != null) "Отменить загрузку" else "Позже") } })
}
