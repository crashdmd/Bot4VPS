package com.bot4vps.mobile.ui.components

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.bot4vps.mobile.ui.theme.LocalPanelPalette
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

enum class StatusTone { GOOD, BAD, WARNING, NEUTRAL }

@Composable
fun StatusBadge(text: String, tone: StatusTone = StatusTone.NEUTRAL) {
    val color = when (tone) {
        StatusTone.GOOD -> MaterialTheme.colorScheme.secondary
        StatusTone.BAD -> MaterialTheme.colorScheme.error
        StatusTone.WARNING -> LocalPanelPalette.current.warning
        StatusTone.NEUTRAL -> MaterialTheme.colorScheme.onSurfaceVariant
    }
    Surface(color = color.copy(alpha = .15f), shape = CircleShape, border = BorderStroke(1.dp, color.copy(alpha = .2f))) {
        Row(Modifier.padding(horizontal = 8.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(5.dp)) {
            Box(Modifier.size(6.dp).background(color, CircleShape))
            Text(text, color = color, style = MaterialTheme.typography.labelSmall, maxLines = 2, overflow = TextOverflow.Ellipsis)
        }
    }
}

@Composable
fun PanelCard(title: String? = null, modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    PanelSurfaceCard(modifier.fillMaxWidth()) {
        Column(Modifier.padding(13.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            title?.let { Text(it, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold) }
            content()
        }
    }
}

@Composable
fun ActionRow(title: String, subtitle: String, icon: ImageVector, onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true, danger: Boolean = false, iconColor: Color? = null) {
    val color = if (danger) MaterialTheme.colorScheme.error else iconColor ?: MaterialTheme.colorScheme.primary
    PanelSurfaceCard(onClick = onClick, enabled = enabled, modifier = modifier.fillMaxWidth()) {
        Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Icon(icon, null, Modifier.size(20.dp), tint = color.copy(alpha = if (enabled) 1f else .4f))
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                Text(title, style = MaterialTheme.typography.titleSmall, color = if (danger) color else MaterialTheme.colorScheme.onSurface)
                if (subtitle.isNotBlank()) Text(subtitle, maxLines = 2, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null, tint = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.size(20.dp))
        }
    }
}

@Composable
fun InfoRow(label: String, value: String) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.Top) {
        Text(label, Modifier.weight(.42f), color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodyMedium)
        Text(value.ifBlank { "—" }, Modifier.weight(.58f), style = MaterialTheme.typography.bodyMedium)
    }
}

@Composable
fun PanelActionLink(title: String, subtitle: String, icon: ImageVector, onClick: () -> Unit, enabled: Boolean = true, iconColor: Color? = null) {
    Row(Modifier.fillMaxWidth().clickable(enabled = enabled, onClick = onClick).padding(vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Icon(icon, null, Modifier.size(20.dp), tint = (iconColor ?: MaterialTheme.colorScheme.primary).copy(alpha = if (enabled) 1f else .4f))
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.titleSmall)
            if (subtitle.isNotBlank()) Text(subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null, Modifier.size(18.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
fun StatTile(label: String, value: String, modifier: Modifier = Modifier, progress: Double? = null, detail: String? = null) {
    PanelSurfaceCard(modifier) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(label, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(value, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
            detail?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis) }
            Box(Modifier.fillMaxWidth().height(4.dp)) {
                if (progress != null) LinearProgressIndicator(progress = { (progress / 100).toFloat().coerceIn(0f, 1f) }, modifier = Modifier.fillMaxWidth().height(4.dp),
                    color = when (label) { "CPU" -> Color(0xFF60A5FA); "Память" -> Color(0xFFF472B6); "Диск" -> Color(0xFFFB923C); else -> MaterialTheme.colorScheme.primary })
            }
        }
    }
}

@Composable
fun ErrorCard(message: String, onRetry: (() -> Unit)? = null) {
    PanelSurfaceCard(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer), modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(message, color = MaterialTheme.colorScheme.onErrorContainer)
            onRetry?.let { TextButton(onClick = it) { Text("Повторить") } }
        }
    }
}

fun displayTime(value: String?): String = value?.let { raw ->
    val format = DateTimeFormatter.ofPattern("dd.MM HH:mm")
    runCatching { format.withZone(ZoneId.systemDefault()).format(Instant.parse(raw)) }
        .getOrElse { runCatching { format.format(LocalDateTime.parse(raw)) }.getOrDefault(raw) }
} ?: "—"

fun displayBytes(bytes: Double?): String {
    if (bytes == null) return "—"
    var amount = bytes
    val units = listOf("Б", "КБ", "МБ", "ГБ", "ТБ")
    var unit = 0
    while (amount >= 1024 && unit < units.lastIndex) { amount /= 1024; unit++ }
    return if (unit == 0) "${amount.toLong()} Б" else "%.1f %s".format(amount, units[unit])
}
