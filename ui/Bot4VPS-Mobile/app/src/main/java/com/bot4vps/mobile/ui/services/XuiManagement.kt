package com.bot4vps.mobile.ui.services

import android.widget.Toast
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.unit.dp
import com.bot4vps.mobile.data.model.*
import com.bot4vps.mobile.ui.components.*
import kotlinx.serialization.json.*

@Composable
fun XuiCertificatesCard(data: JsonObject, vm: ServiceDetailViewModel) {
    val cert = data["cert"] as? JsonObject ?: JsonObject(emptyMap())
    val certificates = xuiCertificates(data)
    val busy = vm.state.collectAsState().value.busy
    PanelCard("Сертификат HTTPS") {
        StatusBadge(if (data.text("panel_url").orEmpty().startsWith("https://")) "HTTPS" else "HTTP", if (data.text("panel_url").orEmpty().startsWith("https://")) StatusTone.GOOD else StatusTone.NEUTRAL)
        InfoRow("Сейчас панель", when (cert.text("panel_engine")) { "acme" -> "acme.sh"; "certbot" -> "certbot"; "other" -> "Свой сертификат"; else -> "Сертификат не назначен" })
        cert.text("panel_expires")?.let { InfoRow("Срок действия", it) }
        PanelActionLink("Выпустить Let's Encrypt", "По домену: acme.sh или certbot, автоматическое продление", Icons.Default.Lock,
            { vm.action("cert_issue_domain", "Сертификат для домена", locked = emptySet()) }, enabled = !busy)
        PanelActionLink("Выпустить для IP", "Короткоживущий сертификат (~6 дней), автоматическое продление", Icons.Default.Public,
            { vm.action("cert_issue_ip", "Сертификат для IP-адреса", mapOf("ip" to JsonPrimitive(listOfNotNull(vm.state.value.detail?.server?.hostIp, vm.state.value.detail?.server?.host).firstOrNull { host -> xuiFormError("cert_issue_ip", buildJsonObject { put("ip", host) }) == null }.orEmpty())), locked = emptySet()) }, enabled = !busy)
        PanelActionLink("Продлить принудительно", if (certificates.isEmpty()) "Нет выпущенных сертификатов" else "Выбрать сертификат для перевыпуска", Icons.Default.Autorenew,
            { vm.action("cert_renew", "Принудительное продление", locked = emptySet()) }, enabled = certificates.isNotEmpty() && !busy)
        PanelActionLink("Отозвать и удалить", if (certificates.isEmpty()) "Нет выпущенных сертификатов" else "Отзыв в Let's Encrypt и удаление файлов", Icons.Default.DeleteOutline,
            { vm.action("cert_remove", "Отозвать и удалить сертификат", locked = emptySet()) }, enabled = certificates.isNotEmpty() && !busy, iconColor = MaterialTheme.colorScheme.error)
    }
}

@Composable
fun XuiManagement(data: JsonObject, vm: ServiceDetailViewModel) {
    val state by vm.state.collectAsState()
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        XuiCertificatesCard(data, vm)
        PanelCard("Сервис") {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Автозапуск", Modifier.weight(1f), style = MaterialTheme.typography.titleSmall)
                Switch(data.flag("enabled"), { enabled -> vm.action("set_autostart", if (enabled) "Включить автозапуск?" else "Выключить автозапуск?", mapOf("enabled" to JsonPrimitive(enabled)), quick = true) }, enabled = !state.busy)
            }
        }
        PanelCard("Аккаунт панели") {
            listOf("change_username" to "Сменить логин", "change_password" to "Сменить пароль", "change_port" to "Изменить порт", "change_path" to "Изменить путь").forEach { (action, label) ->
                PanelActionLink(label, "Настройки доступа к 3x-ui", Icons.Default.ManageAccounts,
                    { vm.action(action, label, quick = true, locked = emptySet()) }, enabled = !state.busy)
            }
        }
        PanelCard("Система") {
            val bbr = data["bbr"] as? JsonObject
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Column(Modifier.weight(1f)) {
                    Text("BBR", style = MaterialTheme.typography.titleSmall)
                    Text(if (bbr == null) "Статус недоступен" else if (bbr.flag("enabled")) "Включён" else "Выключен", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                Switch(bbr?.flag("enabled") == true, { enabled -> vm.action("set_bbr", if (enabled) "Включить BBR?" else "Отключить BBR?", mapOf("enabled" to JsonPrimitive(enabled)), quick = true) }, enabled = bbr != null && !state.busy && !state.loading)
            }
            val geo = data["geo"] as? JsonObject
            listOf("geoip.dat", "geosite.dat").forEach { name -> InfoRow(name, geo?.text(name) ?: "Нет файла") }
            PanelActionLink("Обновить GeoIP и GeoSite", "Свежие базы маршрутизации", Icons.Default.Download,
                { vm.action("update_geo", "Обновление geo-файлов", quick = true, locked = emptySet()) }, enabled = !state.busy)
        }
        PanelCard("SelfSNI и восстановление") {
            PanelActionLink("Сайт-заглушка (SelfSNI)", "HTTPS-сайт для Reality Dest на 127.0.0.1:9000", Icons.Default.Language, vm::openSite, enabled = !state.busy && !state.siteLoading)
            if (state.siteLoading) LinearProgressIndicator(Modifier.fillMaxWidth())
            PanelActionLink("Сбросить настройки панели", "Логин и пароль станут admin/admin", Icons.Default.SettingsBackupRestore,
                { vm.action("reset_settings", "Сбросить настройки 3x-ui?", quick = true, locked = emptySet()) }, enabled = !state.busy, iconColor = MaterialTheme.colorScheme.error)
        }
    }
}

@Composable
fun XuiSiteDialog(state: ServiceDetailState, vm: ServiceDetailViewModel) {
    val site = state.site ?: return
    var usage by remember(site) { mutableStateOf(false) }
    var intro by remember(site) { mutableStateOf(false) }
    val present = site.flag("present")
    val clipboard = LocalClipboardManager.current
    val context = LocalContext.current
    AlertDialog(onDismissRequest = vm::dismissSite,
        title = { Text(if (usage) "Информация для использования" else "Сайт-заглушка (SelfSNI)") },
        text = { Column(Modifier.heightIn(max = 440.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            when {
                usage && present -> {
                    Text("В инбаунде Reality укажите значения вручную. Bot4VPS инбаунды не меняет.", style = MaterialTheme.typography.bodySmall)
                    listOf("Dest" to "dest", "SNI" to "sni", "Xver" to "xver", "Сертификат" to "certificate", "Ключ" to "certificate_key").forEach { (label, key) ->
                        val value = site.text(key) ?: "—"
                        Column {
                            Text(label, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text(value, Modifier.weight(1f), style = MaterialTheme.typography.bodySmall)
                                IconButton(enabled = value != "—", onClick = { clipboard.setText(AnnotatedString(value)); Toast.makeText(context, "Скопировано", Toast.LENGTH_SHORT).show() }) { Icon(Icons.Default.ContentCopy, "Копировать $label", Modifier.size(18.dp)) }
                            }
                        }
                    }
                }
                usage -> Text(site.text("message") ?: "SelfSNI ещё не установлен. Сначала установите сайт-заглушку.")
                intro -> {
                    Text("Создаёт обычный HTTPS-сайт для трафика, который не прошёл Reality handshake. Используется сертификат Let's Encrypt, шаблон сайта выбирается случайно.")
                    Text("После установки настройте Reality вручную:\nDest = 127.0.0.1:9000\nXver = 1\nSNI = ваш домен")
                    Text("Существующие инбаунды Reality не изменяются.")
                }
                else -> {
                    Text(site.text("message") ?: if (present) "SelfSNI установлен" else "SelfSNI не установлен", color = if (site.text("status") in setOf("unavailable", "incomplete")) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface)
                    PanelSecondaryButton(onClick = { intro = true }, enabled = !present, modifier = Modifier.fillMaxWidth()) { Text("Установить") }
                    PanelSecondaryButton(onClick = { usage = true }, modifier = Modifier.fillMaxWidth()) { Text("Информация для использования") }
                    PanelSecondaryButton(onClick = { vm.dismissSite(); vm.action("fakesite_remove", "Удалить заглушку?") }, enabled = site.flag("managed"), modifier = Modifier.fillMaxWidth()) { Text("Удалить заглушку", color = MaterialTheme.colorScheme.error) }
                }
            }
        } },
        confirmButton = { if (intro) TextButton(onClick = { vm.dismissSite(); vm.action("fakesite_install", "Установка SelfSNI", locked = emptySet()) }) { Text("Продолжить установку") } },
        dismissButton = { TextButton(onClick = vm::dismissSite) { Text(if (intro) "Отмена" else "Закрыть") } })
}
