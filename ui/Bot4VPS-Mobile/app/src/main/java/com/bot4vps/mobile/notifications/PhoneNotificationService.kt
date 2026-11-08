package com.bot4vps.mobile.notifications

import android.app.*
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.bot4vps.mobile.MainActivity
import com.bot4vps.mobile.R
import com.bot4vps.mobile.data.api.*
import com.bot4vps.mobile.data.local.PreferencesManager
import com.bot4vps.mobile.data.local.AppLockManager
import com.bot4vps.mobile.data.model.*
import com.bot4vps.mobile.data.repository.checkedObject
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import kotlinx.serialization.json.*
import javax.inject.Inject

@AndroidEntryPoint
class PhoneNotificationService : Service() {
    @Inject lateinit var prefs: PreferencesManager
    @Inject lateinit var appLock: AppLockManager
    @Inject lateinit var panel: NativePanelClient
    @Inject lateinit var realtime: RealtimeHub
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val restarts = MutableStateFlow(0)
    private val manager get() = getSystemService(NotificationManager::class.java)

    override fun onCreate() {
        super.onCreate()
        manager.createNotificationChannel(NotificationChannel(EVENTS, "События Bot4VPS", NotificationManager.IMPORTANCE_DEFAULT))
        manager.createNotificationChannel(NotificationChannel(CONNECTION, "Подключение к панели", NotificationManager.IMPORTANCE_LOW))
        val notification = connection("Подключение к панели…")
        if (Build.VERSION.SDK_INT >= 34) startForeground(FOREGROUND_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        else startForeground(FOREGROUND_ID, notification)
        scope.launch {
            appLock.state.filter { it.phase != LockPhase.LOADING }.map { it.protectsContent }.distinctUntilChanged().collect { protected ->
                if (protected) manager.activeNotifications.filter { it.notification.channelId == EVENTS }.forEach { manager.cancel(it.tag, it.id) }
            }
        }
        scope.launch {
            combine(prefs.phoneNotifications.distinctUntilChanged(), prefs.baseUrl.distinctUntilChanged(), prefs.username.distinctUntilChanged()) { enabled, url, user -> Triple(enabled, url, user) }
                .distinctUntilChanged().combine(restarts) { config, _ -> config }.collectLatest { (enabled, url, user) ->
                    if (!enabled || url == null || user == null || !NotificationManagerCompat.from(this@PhoneNotificationService).areNotificationsEnabled()) {
                        stopSelf(); return@collectLatest
                    }
                    val tracker = PhoneEventTracker(prefs.phoneSeen.first())
                    while (currentCoroutineContext().isActive) {
                        try {
                            fetch(tracker)
                            realtime.reconnecting.collect { event ->
                                if (event.type == "snapshot") {
                                    val snapshot = event.data as? JsonObject ?: return@collect
                                    if (snapshot.objects("events").any { it.text("id")?.let { id -> !tracker.knows(id) } == true }) fetch(tracker)
                                    manager.notify(FOREGROUND_ID, connection("Получение событий включено"))
                                }
                            }
                        } catch (e: CancellationException) { throw e }
                        catch (e: ApiError) {
                            if (e.status == 401) {
                                manager.notify(FOREGROUND_ID, connection("Сессия истекла — войдите в панель"))
                                return@collectLatest
                            }
                            manager.notify(FOREGROUND_ID, connection("Нет связи с панелью. Ожидаем подключения…"))
                        } catch (_: Exception) {
                            manager.notify(FOREGROUND_ID, connection("Нет связи с панелью. Ожидаем подключения…"))
                        }
                        delay(15000)
                    }
                }
        }
    }

    private suspend fun fetch(tracker: PhoneEventTracker) {
        if (!NotificationManagerCompat.from(this).areNotificationsEnabled()) { stopSelf(); return }
        val events = panel.checkedObject("GET", "/api/events", query = mapOf("limit" to listOf("1000"))).objects("events")
        val categories = prefs.phoneCategories.first()
        val fresh = tracker.accept(events)
        fresh.filter { phoneEventCategory(it) in categories }.forEach(::showEvent)
        prefs.rememberPhoneSeen(tracker.checkpoint(events))
    }

    @Suppress("MissingPermission")
    private fun showEvent(event: JsonObject) {
        val id = event.text("id") ?: return
        val preview = phoneEventPreview(event, appLock.state.value.protectsContent)
        val notification = NotificationCompat.Builder(this, EVENTS).setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(preview.first)
            .setContentText(preview.second)
            .setStyle(NotificationCompat.BigTextStyle().bigText(preview.second))
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
            .setPublicVersion(NotificationCompat.Builder(this, EVENTS).setSmallIcon(R.drawable.ic_notification)
                .setContentTitle("Новое событие Bot4VPS").setContentText("Откройте приложение для просмотра").build())
            .setContentIntent(openPanel(id)).setAutoCancel(true).build()
        manager.notify(id, 1, notification)
    }
    private fun connection(message: String) = NotificationCompat.Builder(this, CONNECTION)
        .setSmallIcon(R.drawable.ic_notification).setContentTitle("Bot4VPS · уведомления")
        .setContentText(message).setContentIntent(openPanel(null)).setOngoing(true).setOnlyAlertOnce(true).build()
    private fun openPanel(id: String?): PendingIntent {
        val intent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
            id?.let { putExtra("event_id", it); data = android.net.Uri.parse("bot4vps://event/$it") }
        }
        return PendingIntent.getActivity(this, 0, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    }
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int { restarts.value += 1; return START_STICKY }
    override fun onBind(intent: Intent?): IBinder? = null
    override fun onDestroy() { scope.cancel(); super.onDestroy() }

    companion object {
        private const val EVENTS = "bot4vps_events"
        private const val CONNECTION = "bot4vps_connection"
        private const val FOREGROUND_ID = 9001
        fun start(context: Context) { ContextCompat.startForegroundService(context, Intent(context, PhoneNotificationService::class.java)) }
        fun stop(context: Context) { context.stopService(Intent(context, PhoneNotificationService::class.java)) }
    }
}
