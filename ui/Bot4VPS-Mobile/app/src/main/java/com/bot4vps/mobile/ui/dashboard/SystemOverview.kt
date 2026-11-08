package com.bot4vps.mobile.ui.dashboard

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.bot4vps.mobile.data.model.*
import com.bot4vps.mobile.ui.components.*
import kotlinx.serialization.json.*

@Composable
fun SystemOverview(system: JsonObject?, samples: List<SystemSample>, error: String?, onTelegram: () -> Unit, onJournal: () -> Unit) {
    val data = system ?: JsonObject(emptyMap())
    val cpu = data.number("cpu")
    val ram = data.number("ram_pct")
    val disk = data.number("disk_pct")
    Column(verticalArrangement = refreshArrangement(12.dp)) {
        Text("Хост Bot4VPS", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
        Text(listOfNotNull(data.text("hostname"), data.text("os"), data.text("os_version")).joinToString(" · ").ifBlank { "Загрузка сведений о хосте…" },
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 2)
        Text("Измерения за время открытого экрана · время устройства", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        PanelCard("Нагрузка") {
            LoadChart(cpu, ram, samples)
            InfoRow("Память", data.text("ram") ?: "—")
            data.text("temp")?.takeUnless { it == "N/A" }?.let { InfoRow("Температура", it) }
        }
        PanelCard("Диск") {
            InfoRow(percent(disk), data.text("disk") ?: "—")
            if (disk != null) LinearProgressIndicator(progress = { (disk / 100).toFloat().coerceIn(0f, 1f) }, modifier = Modifier.fillMaxWidth())
        }
        PanelCard("Сеть") {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("↓ ${displayRate(data.number("net_rx"))}", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary)
                Text("↑ ${displayRate(data.number("net_tx"))}", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.tertiary)
            }
            MiniChart(samples.map { it.rx }, samples.map { it.tx }, modifier = Modifier.fillMaxWidth().height(38.dp))
            Text("↓ Входящий · ↑ Исходящий", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        PanelCard {
            ComponentStatus("Web-панель", data["web"] as? JsonObject, error, null)
            HorizontalDivider()
            SimpleComponentStatus("Telegram-бот", data["bot"] as? JsonObject)
            HorizontalDivider()
            InfoRow("Хост работает", displayDuration(data.number("uptime_seconds")))
            InfoRow("Bot4VPS работает", displayDuration(data.number("service_uptime_seconds")))
            TextButton(onClick = onJournal, modifier = Modifier.fillMaxWidth()) { Text("Журнал службы") }
            Text(error?.let { "Не удалось обновить данные: $it" } ?: " ", modifier = Modifier.heightIn(min = 32.dp), maxLines = 2, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
        }
        PanelCard("Система") {
            InfoRow("Адрес", data.text("ip") ?: "—")
            InfoRow("Ядро", data.text("kernel") ?: "—")
            InfoRow("Часовой пояс", data.text("timezone") ?: "—")
            InfoRow("Время на хосте", displayTime(data.text("server_time")))
        }
    }
}

private fun percent(value: Double?) = value?.let { "%.1f%%".format(it) } ?: "—"
private fun displayRate(value: Double?) = value?.let { "${displayBytes(it)}/с" } ?: "—"
fun displayDuration(value: Double?): String {
    if (value == null || value < 0) return "—"
    val seconds = value.toLong()
    val days = seconds / 86400
    val hours = seconds % 86400 / 3600
    val minutes = seconds % 3600 / 60
    return if (days > 0) "$days д. $hours ч." else if (hours > 0) "$hours ч. $minutes мин." else "$minutes мин."
}

@Composable
private fun ComponentStatus(title: String, status: JsonObject?, error: String?, onClick: (() -> Unit)?) {
    val running = status?.text("state") == "running" && status?.flag("ok") == true
    val disabled = status?.text("state") == "disabled"
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.titleSmall)
            Text(error ?: status?.text("error") ?: status?.text("detail") ?: "Нет данных", style = MaterialTheme.typography.bodySmall,
                modifier = Modifier.heightIn(min = 32.dp), maxLines = 2, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        StatusBadge(when { error != null -> "Нет связи"; running -> "Работает"; disabled -> "Выключен"; status != null -> "Ошибка"; else -> "—" },
            when { error != null -> StatusTone.BAD; running -> StatusTone.GOOD; disabled || status == null -> StatusTone.NEUTRAL; else -> StatusTone.BAD })
        onClick?.let { IconButton(onClick = it) { Icon(Icons.Default.ChevronRight, "Настроить $title") } }
    }
}

@Composable
fun LoadChart(cpu: Double?, ram: Double?, samples: List<SystemSample>) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text("CPU ${cpu?.let { "%.0f%%".format(it) } ?: "—"}", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary)
            Text("RAM ${ram?.let { "%.0f%%".format(it) } ?: "—"}", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.tertiary)
        }
        MiniChart(samples.map { it.cpu }, samples.map { it.ram }, maximum = 100.0, modifier = Modifier.fillMaxWidth().height(38.dp))
    }
}

@Composable
fun MiniChart(values: List<Double?>, secondary: List<Double?> = emptyList(), maximum: Double? = null, modifier: Modifier = Modifier) {
    val primary = MaterialTheme.colorScheme.primary
    val other = MaterialTheme.colorScheme.tertiary
    val grid = MaterialTheme.colorScheme.outlineVariant
    Canvas(modifier) {
        val ceiling = maximum ?: ((values + secondary).filterNotNull().maxOrNull() ?: 1.0).coerceAtLeast(1.0)
        repeat(3) { i -> val y = size.height * i / 2; drawLine(grid, Offset(0f, y), Offset(size.width, y), 1f) }
        fun series(data: List<Double?>, tint: Color) {
            fun point(i: Int, value: Double) = Offset(size.width * i / (data.size - 1).coerceAtLeast(1), size.height * (1 - (value / ceiling).toFloat().coerceIn(0f, 1f)))
            data.zipWithNext().forEachIndexed { i, (a, b) -> if (a != null && b != null) drawLine(tint, point(i, a), point(i+1, b), 2.dp.toPx()) }
            data.lastOrNull()?.let { drawCircle(tint, 2.dp.toPx(), point(data.lastIndex, it)) }
        }
        series(values, primary); series(secondary, other)
    }
}

@Composable
fun DashboardSystem(system: JsonObject?, samples: List<SystemSample>) {
    val data = system ?: JsonObject(emptyMap())
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        DashboardMetric("CPU", percent(data.number("cpu")), data.text("temp")?.takeUnless { it == "N/A" }.orEmpty(), samples.map { it.cpu }, maximum = 100.0, modifier = Modifier.weight(1f))
        DashboardMetric("RAM", percent(data.number("ram_pct")), data.text("ram").orEmpty(), samples.map { it.ram }, maximum = 100.0, modifier = Modifier.weight(1f))
        DashboardMetric("Сеть", "↓ ${displayRate(data.number("net_rx"))}", "↑ ${displayRate(data.number("net_tx"))}", samples.map { it.rx }, samples.map { it.tx }, modifier = Modifier.weight(1f))
    }
    SimpleComponentStatus("Web", data["web"] as? JsonObject)
    SimpleComponentStatus("Telegram-бот", data["bot"] as? JsonObject)
}

@Composable
private fun DashboardMetric(title: String, value: String, detail: String, values: List<Double?>, secondary: List<Double?> = emptyList(), maximum: Double? = null, modifier: Modifier) {
    PanelSurfaceCard(modifier) {
        Column(Modifier.padding(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(title, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(value, style = MaterialTheme.typography.titleSmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
            MiniChart(values, secondary, maximum, Modifier.fillMaxWidth().height(38.dp))
            Text(detail.ifBlank { " " }, style = MaterialTheme.typography.labelSmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
    }
}

@Composable
fun SimpleComponentStatus(title: String, status: JsonObject?) {
    val running = status?.flag("ok") == true || status?.text("state") == "running"
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween) {
        Text(title, style = MaterialTheme.typography.bodyMedium)
        StatusBadge(if (status == null) "—" else if (running) "Работает" else "Не работает", if (status == null) StatusTone.NEUTRAL else if (running) StatusTone.GOOD else StatusTone.BAD)
    }
}
