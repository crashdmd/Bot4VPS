package com.bot4vps.mobile.ui.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.bot4vps.mobile.BuildConfig
import com.bot4vps.mobile.ui.components.*

@Composable
fun PanelAboutCard(panelVersion: String?, onVersion: () -> Unit, enabled: Boolean) {
    val uri = LocalUriHandler.current
    PanelCard {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            Box(Modifier.size(64.dp).background(MaterialTheme.colorScheme.primaryContainer, RoundedCornerShape(18.dp)),
                contentAlignment = Alignment.Center) {
                androidx.compose.foundation.Image(androidx.compose.ui.res.painterResource(com.bot4vps.mobile.R.drawable.web_logo_foreground), contentDescription="Логотип Bot4VPS", modifier=Modifier.size(60.dp))
            }
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text("УПРАВЛЕНИЕ СЕРВЕРАМИ", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text("Bot4VPS", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.SemiBold)
            }
        }
        Text("Telegram-бот и Web UI для управления VPS и домашними серверами через SSH.")
        InfoRow("Версия панели", panelVersion ?: "—")
        InfoRow("Версия приложения", BuildConfig.VERSION_NAME)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            PanelSecondaryButton(onClick = onVersion, enabled = enabled, modifier=Modifier.weight(1f)) { Text("Описание версии") }
            PanelSecondaryButton(onClick = { uri.openUri("https://github.com/crashdmd/Bot4VPS") },modifier=Modifier.weight(1f)) { Text("GitHub ↗") }
        }
        HorizontalDivider()
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Автор —", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            TextButton(onClick = { uri.openUri("https://github.com/crashdmd") }) { Text("crashdmd") }
        }
    }
}
