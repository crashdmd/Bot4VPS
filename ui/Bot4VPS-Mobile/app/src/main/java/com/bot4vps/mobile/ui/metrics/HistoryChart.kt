package com.bot4vps.mobile.ui.metrics

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.*
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.*
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.clipRect
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.bot4vps.mobile.data.model.*
import com.bot4vps.mobile.ui.components.*
import kotlinx.serialization.json.JsonObject
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import kotlin.math.abs

private val HistoryColors = listOf(Color(0xFF60A5FA), Color(0xFFF472B6), Color(0xFFFB923C),
    Color(0xFF34D399), Color(0xFFA78BFA), Color(0xFFFBBF24))

@Composable
fun HistoryChart(history: MetricHistory, marks: List<JsonObject>, focused: String, context: String,
    onWindowChange: (HistoryWindow?) -> Unit) {
    var window by remember(context) { mutableStateOf<HistoryWindow?>(null) }
    var selected by remember(context) { mutableStateOf<Long?>(null) }
    val latestHistory by rememberUpdatedState(history)
    val notifyWindow by rememberUpdatedState(onWindowChange)
    val visible = window ?: history.window
    val lastTime = history.series.flatMap { it.points }.filter { it.time in visible.from..visible.to }.maxOfOrNull { it.time }
    val readingTime = selected ?: lastTime
    val loadCeiling = ((history.series.firstOrNull { !it.percent }?.points.orEmpty()
        .filter { it.time in visible.from..visible.to }.mapNotNull { it.value }.maxOrNull() ?: 1.0) * 1.1).coerceAtLeast(1.0)
    val loadMax by animateFloatAsState(loadCeiling.toFloat(), tween(180), label="load-axis")
    val grid = MaterialTheme.colorScheme.outlineVariant
    val focusColor = MaterialTheme.colorScheme.primary
    val gapColor = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha=.07f)
    fun move(zoom: Float) {
        window = visible.transform(zoom=zoom, now=Instant.now().epochSecond)
        onWindowChange(window)
    }
    PanelSurfaceCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement=Arrangement.spacedBy(10.dp)) {
            Text("История метрик", style=MaterialTheme.typography.titleMedium, fontWeight=FontWeight.SemiBold)
            Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), verticalAlignment=Alignment.CenterVertically) {
                TextButton(onClick={ move(.5f) }) { Text("−", style=MaterialTheme.typography.titleLarge) }
                TextButton(onClick={ move(2f) }) { Text("+", style=MaterialTheme.typography.titleLarge) }
                TextButton(onClick={ window=null; selected=null; onWindowChange(null) }) { Text("Весь диапазон") }
                TextButton(enabled=selected!=null, onClick={ selected=null }) { Text("Снять выбор") }
            }
            Row(Modifier.fillMaxWidth(), horizontalArrangement=Arrangement.SpaceBetween) {
                Text("Память / диски, %", style=MaterialTheme.typography.labelSmall, color=MaterialTheme.colorScheme.onSurfaceVariant)
                Text("Load 1", style=MaterialTheme.typography.labelSmall, color=HistoryColors[0])
            }
            Row(Modifier.fillMaxWidth(), horizontalArrangement=Arrangement.spacedBy(6.dp)) {
                Column(Modifier.width(32.dp).height(200.dp), verticalArrangement=Arrangement.SpaceBetween) {
                    repeat(5) { Text("${100-it*25}", style=MaterialTheme.typography.labelSmall, color=MaterialTheme.colorScheme.onSurfaceVariant) }
                }
                Canvas(Modifier.weight(1f).height(200.dp).pointerInput(context) {
                    awaitEachGesture {
                        val down = awaitFirstDown(requireUnconsumed=false)
                        var distance = Offset.Zero
                        var mode: String? = null
                        var changedWindow = false
                        do {
                            val event = awaitPointerEvent()
                            val active = event.changes.count { it.pressed }
                            val pan = event.calculatePan()
                            distance += pan
                            if (active > 1) mode="pan"
                            if (mode == null && distance.getDistance() > viewConfiguration.touchSlop) {
                                if (abs(distance.y) > abs(distance.x)) return@awaitEachGesture
                                mode = if (event.changes.first().uptimeMillis-down.uptimeMillis >= viewConfiguration.longPressTimeoutMillis) "read" else "pan"
                            }
                            val current = window ?: latestHistory.window
                            val position = event.changes.first().position.x.coerceIn(0f, size.width.toFloat())
                            if (mode == "read") {
                                val time = current.from + (position / size.width.coerceAtLeast(1) * current.span).toLong()
                                selected = latestHistory.nearestTime(time, current)
                                event.changes.forEach { it.consume() }
                            } else if (mode == "pan") {
                                val anchor = (event.calculateCentroid().x / size.width.coerceAtLeast(1)).takeIf { it.isFinite() } ?: .5f
                                window = current.transform(pan.x/size.width.coerceAtLeast(1), event.calculateZoom(), anchor, Instant.now().epochSecond)
                                changedWindow=true
                                event.changes.forEach { it.consume() }
                            } else if (active == 0 && event.changes.none { it.isConsumed }) {
                                val time = current.from + (position / size.width.coerceAtLeast(1) * current.span).toLong()
                                selected = latestHistory.nearestTime(time, current)
                                event.changes.forEach { it.consume() }
                            }
                        } while (event.changes.any { it.pressed })
                        if (changedWindow) notifyWindow(window)
                    }
                }) {
                    fun x(time: Long) = (time-visible.from).toFloat()/visible.span*size.width
                    repeat(5) { i ->
                        val y=size.height*i/4
                        drawLine(grid.copy(alpha=.6f), Offset(0f,y), Offset(size.width,y), 1f)
                    }
                    repeat(4) { i ->
                        val x=size.width*i/3
                        drawLine(grid.copy(alpha=.3f), Offset(x,0f), Offset(x,size.height), 1f,
                            pathEffect=PathEffect.dashPathEffect(floatArrayOf(3.dp.toPx(),4.dp.toPx())))
                    }
                    clipRect {
                        history.gaps.forEach { (from,to) ->
                            if (from < visible.to && to > visible.from) drawRect(gapColor,
                                Offset(x(from),0f), androidx.compose.ui.geometry.Size((x(to)-x(from)).coerceAtLeast(0f),size.height))
                        }
                        history.series.forEachIndexed { index, series ->
                            val color=HistoryColors[index%HistoryColors.size]
                            val missing=if(series.disk) history.diskGaps else history.gaps
                            var previous: HistoryPoint?=null
                            var path=Path()
                            fun paint() { drawPath(path,color,style=Stroke(1.8.dp.toPx(),cap=StrokeCap.Round,join=StrokeJoin.Round)); path=Path() }
                            series.points.forEach { point ->
                                val value=point.value
                                if(value==null || missing.any { point.time>it.first && point.time<it.second }) {
                                    paint(); previous=null
                                } else {
                                    val y=size.height*(1-value/(if(series.percent) 100.0 else loadMax.toDouble())).toFloat().coerceIn(0f,1f)
                                    val prior=previous
                                    val gap=prior!=null && missing.any { it.first<point.time && it.second>prior.time }
                                    if(prior==null || gap) { paint(); path.moveTo(x(point.time),y) } else path.lineTo(x(point.time),y)
                                    if(point.time==readingTime || series.points.size==1) {
                                        drawCircle(color.copy(alpha=.15f),5.dp.toPx(),Offset(x(point.time),y))
                                        drawCircle(color,2.5.dp.toPx(),Offset(x(point.time),y))
                                    }
                                    previous=point
                                }
                            }
                            paint()
                        }
                        marks.forEach { mark ->
                            val time=mark.number("ts")?.toLong() ?: return@forEach
                            if(time in visible.from..visible.to) {
                                val active=focused.isNotEmpty() && mark.text("audit_id")==focused
                                drawLine(if(active) focusColor else grid.copy(alpha=.7f),Offset(x(time),0f),Offset(x(time),size.height),
                                    if(active) 2.dp.toPx() else 1.dp.toPx(), pathEffect=PathEffect.dashPathEffect(floatArrayOf(3.dp.toPx(),3.dp.toPx())))
                            }
                        }
                        readingTime?.takeIf { it in visible.from..visible.to }?.let { time ->
                            drawLine(focusColor.copy(alpha=.7f),Offset(x(time),0f),Offset(x(time),size.height),1.dp.toPx())
                        }
                    }
                }
                Column(Modifier.width(32.dp).height(200.dp), verticalArrangement=Arrangement.SpaceBetween) {
                    repeat(5) { Text("%.1f".format(loadMax*(4-it)/4), style=MaterialTheme.typography.labelSmall, color=HistoryColors[0]) }
                }
            }
            Row(Modifier.fillMaxWidth(), horizontalArrangement=Arrangement.SpaceBetween) {
                Text(historyTime(visible.from,false), style=MaterialTheme.typography.labelSmall, color=MaterialTheme.colorScheme.onSurfaceVariant)
                Text(historyTime(visible.to,false), style=MaterialTheme.typography.labelSmall, color=MaterialTheme.colorScheme.onSurfaceVariant)
            }
            if (lastTime == null) Text("В этом окне нет проб", style=MaterialTheme.typography.bodySmall, color=MaterialTheme.colorScheme.onSurfaceVariant)
            HorizontalDivider(color=grid)
            Row(Modifier.fillMaxWidth(), horizontalArrangement=Arrangement.SpaceBetween) {
                Text(readingTime?.let { historyTime(it,true) } ?: "Выберите момент", style=MaterialTheme.typography.labelMedium)
                Text(if(history.hourly) "За час" else if(selected==null) "Последняя проба" else "Выбрано",
                    style=MaterialTheme.typography.labelSmall, color=MaterialTheme.colorScheme.onSurfaceVariant)
            }
            history.series.forEachIndexed { index, series ->
                Row(Modifier.fillMaxWidth(), verticalAlignment=Alignment.CenterVertically, horizontalArrangement=Arrangement.spacedBy(8.dp)) {
                    Box(Modifier.size(7.dp).background(HistoryColors[index%HistoryColors.size],CircleShape))
                    Text(series.label, Modifier.weight(1f), style=MaterialTheme.typography.bodySmall)
                    Text(readingTime?.let { historyValue(history,series,it) } ?: "—", Modifier.weight(1.1f),
                        style=MaterialTheme.typography.bodySmall, fontWeight=FontWeight.Medium)
                }
            }
            Text("Касание — все значения · удержание и движение — чтение · влево/вправо — время · щипок — масштаб. Вверх/вниз — прокрутка.",
                style=MaterialTheme.typography.labelSmall,color=MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

private fun historyTime(time: Long, seconds: Boolean) = DateTimeFormatter.ofPattern(if(seconds) "dd.MM HH:mm:ss" else "dd.MM HH:mm")
    .withZone(ZoneId.systemDefault()).format(Instant.ofEpochSecond(time))

private fun historyValue(data: MetricHistory, series: HistorySeries, time: Long): String {
    val value=data.value(series,time) ?: return "Нет пробы"
    val amount=if(series.percent) "%.1f%%".format(value) else "%.2f".format(value)
    val raw=data.rawValues[time]
    val detail=when {
        series.key=="ram_pct" -> {
            val used=raw?.number("ram_used_kb"); val total=raw?.number("ram_total_kb")
            if(used!=null && total!=null) "${displayBytes(used*1024)} / ${displayBytes(total*1024)}" else null
        }
        series.key.startsWith("disk:") -> {
            val disk=(raw?.get("disks") as? JsonObject)?.get(series.key.removePrefix("disk:")) as? JsonObject
            val used=disk?.number("used_kb"); val total=disk?.number("total_kb")
            if(used!=null && total!=null) "${displayBytes(used*1024)} / ${displayBytes(total*1024)}" else null
        }
        series.key=="disk_max_pct" -> data.diskLabels[time]
        else -> null
    }
    return if(detail!=null) "$amount\n$detail" else amount
}
