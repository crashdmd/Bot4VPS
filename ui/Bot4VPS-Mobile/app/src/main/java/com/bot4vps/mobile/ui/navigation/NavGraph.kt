package com.bot4vps.mobile.ui.navigation

import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.core.tween

import android.net.Uri
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavType
import androidx.navigation.compose.*
import androidx.navigation.navArgument
import com.bot4vps.mobile.ui.auth.*
import com.bot4vps.mobile.ui.audit.AuditScreen
import com.bot4vps.mobile.ui.backups.BackupsScreen
import com.bot4vps.mobile.ui.control.*
import com.bot4vps.mobile.ui.dashboard.DashboardScreen
import com.bot4vps.mobile.ui.dashboard.HostMonitorScreen
import com.bot4vps.mobile.ui.dashboard.ServiceJournalScreen
import com.bot4vps.mobile.ui.metrics.MetricsScreen
import com.bot4vps.mobile.ui.scripts.ScriptsScreen
import com.bot4vps.mobile.ui.servers.*
import com.bot4vps.mobile.data.model.ServiceKind
import com.bot4vps.mobile.ui.services.*
import com.bot4vps.mobile.ui.settings.SettingsScreen
import com.bot4vps.mobile.ui.settings.PanelSettingsScreen
import com.bot4vps.mobile.ui.settings.UpdatesContent
import com.bot4vps.mobile.ui.components.PanelScaffold
import com.bot4vps.mobile.ui.components.PanelTopBar
import com.bot4vps.mobile.ui.tasks.TasksScreen
import com.bot4vps.mobile.ui.terminal.TerminalScreen
import com.bot4vps.mobile.ui.theme.*

object Routes {
    const val SETUP_URL = "setup_url"
    const val LOGIN = "login"
    const val MAIN = "main"
    const val SERVERS = "servers"
    const val DASHBOARD = "dashboard"
    const val TASKS = "tasks"
    const val EVENTS = "history/events"
    const val SCRIPTS = "scripts"
    const val SERVICES = "services"
    const val SERVER_SCRIPTS = "server/{serverId}/scripts"
    const val SERVICE_ACTIONS = "service/{serviceId}/{serverId}/actions"
    const val SERVICE_DETAIL = "service/{serviceId}/{serverId}"
    const val HISTORY_DETAIL = "history/detail?serverId={serverId}&taskId={taskId}"
    const val SETTINGS = "settings"
    const val SERVER_DETAIL = "server/{serverId}"
    const val SERVER_SETTINGS = "server/{serverId}/settings?page={page}"
    const val SECTION = "section/{section}?serverId={serverId}&view={view}&recordId={recordId}"
    const val OPERATION = "operation/{operationId}?serverId={serverId}"
    const val ROOT_OPERATION = "root-operation/{operationId}"
    const val METRICS = "metrics?serverId={serverId}&ts={ts}&recordId={recordId}"
    const val TERMINAL = "terminal/{serverId}"
    fun serviceDetail(kind: ServiceKind, id: String) = "service/${Uri.encode(kind.id)}/${Uri.encode(id)}"
    fun history(serverId: String? = null, taskId: String? = null) = "history/detail?serverId=${Uri.encode(serverId.orEmpty())}&taskId=${Uri.encode(taskId.orEmpty())}"
    fun serverSettings(id: String, page: String = "") = "server/${Uri.encode(id)}/settings?page=${Uri.encode(page)}"
    fun serverDetail(id: String) = "server/${Uri.encode(id)}"
    fun section(section: String, serverId: String? = null, view:String="") = "section/${Uri.encode(section)}?serverId=${Uri.encode(serverId.orEmpty())}&view=${Uri.encode(view)}"
    fun operation(id: String, serverId: String? = null) = "operation/${Uri.encode(id)}?serverId=${Uri.encode(serverId.orEmpty())}"
    fun audit(id: String, serverId: String?) = section("audit",serverId)+"&recordId=${Uri.encode(id)}"
    fun metrics(id: String, ts: Long, recordId: String) = "metrics?serverId=${Uri.encode(id)}&ts=$ts&recordId=${Uri.encode(recordId)}"
}
private data class Tab(val route: String, val label: String, val icon: ImageVector)
private val tabs = listOf(Tab(Routes.DASHBOARD,"Обзор",Icons.Default.Dashboard),Tab(Routes.SERVERS,"Серверы",Icons.Default.Dns),Tab(Routes.SERVICES,"Сервисы",Icons.Default.Widgets),Tab(Routes.EVENTS,"История",Icons.Default.History),Tab(Routes.SETTINGS,"Ещё",Icons.Default.Apps))

@Composable
fun Bot4VpsNavHost(eventId: String? = null, onEventConsumed: () -> Unit = {}) {
    val auth: AuthViewModel = hiltViewModel()
    val destination by auth.startDestination.collectAsState()
    val first = destination
    if (first == null) { Box(Modifier.fillMaxSize(),contentAlignment=Alignment.Center) { CircularProgressIndicator() }; return }
    val root = rememberNavController()
    fun login() { root.navigate(Routes.LOGIN) { popUpTo(root.graph.id) { inclusive = true }; launchSingleTop = true } }
    var editingAddress by remember { mutableStateOf(false) }
    fun changeUrl() { editingAddress = true }
    if (editingAddress) PanelAddressDialog(onDismiss = { editingAddress = false }, onSaved = { editingAddress = false; login() })
    NavHost(root,startDestination=first,
        enterTransition = { fadeIn(tween(150)) }, exitTransition = { fadeOut(tween(150)) },
        popEnterTransition = { fadeIn(tween(150)) }, popExitTransition = { fadeOut(tween(150)) }) {
        composable(Routes.SETUP_URL) { SetupUrlScreen(onUrlSaved = { root.navigate(Routes.LOGIN) { popUpTo(Routes.SETUP_URL) { inclusive=true } } }) }
        composable(Routes.LOGIN) {
            LoginScreen(onLoggedIn = { root.navigate(Routes.MAIN) { popUpTo(Routes.LOGIN) { inclusive=true } } },onChangeUrl=::changeUrl,
                onRecovery = { root.navigate("root-operation/${Uri.encode("POST /api/auth/recover")}") })
        }
        composable(Routes.ROOT_OPERATION,arguments=listOf(navArgument("operationId") { type=NavType.StringType })) {
            NativeActionScreen(onBack={ root.popBackStack() },onLogin=::login,onOperation={ root.navigate("root-operation/${Uri.encode(it)}") })
        }
        composable(Routes.MAIN) { MainShell(onLogout=::login,onChangeUrl=::changeUrl,eventId=eventId,onEventConsumed=onEventConsumed) }
    }
}

@Composable
private fun MainShell(onLogout: () -> Unit,onChangeUrl: () -> Unit, eventId: String?, onEventConsumed: () -> Unit) {
    val nav=rememberNavController()
    var activeTab by rememberSaveable { mutableStateOf(Routes.DASHBOARD) }
    fun openTab(route: String) {
        activeTab=route
        nav.navigate(route) { popUpTo(nav.graph.findStartDestination().id) { saveState=true }; launchSingleTop=true; restoreState=false }
    }
    LaunchedEffect(eventId) {
        if (eventId != null) {
            activeTab = Routes.EVENTS
            nav.navigate(Routes.section("events") + "&recordId=${Uri.encode(eventId)}")
            onEventConsumed()
        }
    }
    val backStack by nav.currentBackStackEntryAsState()
    val current=backStack?.destination?.route
    LaunchedEffect(current) { if(tabs.any { it.route == current }) activeTab=current!! }
    val terminalKeyboard = current == "terminal/{serverId}" && WindowInsets.ime.getBottom(androidx.compose.ui.platform.LocalDensity.current) > 0
    Scaffold(containerColor=Background,contentWindowInsets=WindowInsets(0,0,0,0),bottomBar={
        if (!terminalKeyboard) NavigationBar(containerColor=Surface) {
            tabs.forEach { tab -> NavigationBarItem(selected=activeTab==tab.route,onClick={ openTab(tab.route) },
                icon={ Icon(tab.icon,tab.label) },label={ Text(tab.label,fontSize=11.sp) }) }
        }
    }) { padding ->
        NavHost(nav,startDestination=Routes.DASHBOARD,modifier=Modifier.padding(padding).consumeWindowInsets(padding),
            enterTransition = { fadeIn(tween(150)) }, exitTransition = { fadeOut(tween(150)) },
            popEnterTransition = { fadeIn(tween(150)) }, popExitTransition = { fadeOut(tween(150)) }) {
            composable(Routes.SERVERS) { ServersScreen(onOpenServer={ nav.navigate(Routes.serverDetail(it)) },
                onCreate={ nav.navigate(Routes.operation("POST /api/servers")) },onGroups={ nav.navigate(Routes.section("groups")) }) }
            composable(Routes.DASHBOARD) {
                DashboardScreen(onServer={ nav.navigate(Routes.serverDetail(it)) },
                    onServers={ openTab(Routes.SERVERS) }, onAddServer={ nav.navigate(Routes.operation("POST /api/servers")) },
                    onMonitor={ nav.navigate(Routes.section("monitor")) }, onLogin=onLogout,
                    onEvents={ openTab(Routes.EVENTS) }, onEvent={ nav.navigate(Routes.section("events") + "&recordId=${Uri.encode(it)}") })
            }
            composable(Routes.EVENTS, arguments=listOf(navArgument("section") { type=NavType.StringType; defaultValue="events" })) {
                NativeSectionScreen("events", onOperation={ nav.navigate(Routes.operation(it)) }, onHistory={ nav.navigate(Routes.TASKS) })
            }
            composable(Routes.TASKS) { TasksScreen(onBack={ nav.popBackStack() }, onEvents={ nav.navigate(Routes.section("events")) }) }
            composable(Routes.HISTORY_DETAIL, arguments=listOf(navArgument("serverId") { type=NavType.StringType; nullable=true; defaultValue=null }, navArgument("taskId") { type=NavType.StringType; nullable=true; defaultValue=null })) { entry ->
                TasksScreen(onBack={ nav.popBackStack() }, onEvents={ nav.navigate(Routes.section("events")) })
            }
            composable(Routes.SERVICES) { ServicesScreen(onServer={ kind, id -> nav.navigate(Routes.serviceDetail(kind,id)) }, onFiles={ nav.navigate(Routes.section("files")) }, onScriptsFiles={ nav.navigate(Routes.section("files",view="scripts")) }, onOperation={ nav.navigate(Routes.operation(it)) },onHistory={ nav.navigate(Routes.history(taskId=it)) },onQueues={ nav.navigate(Routes.section("queues")) },onBackups={ nav.navigate(Routes.section("backups")) }) }
            composable(Routes.SERVICE_DETAIL, arguments=listOf(navArgument("serviceId") { type=NavType.StringType }, navArgument("serverId") { type=NavType.StringType })) { entry ->
                val id=entry.arguments?.getString("serverId") ?: return@composable
                val kind=ServiceKind.find(entry.arguments?.getString("serviceId")) ?: return@composable
                ServiceDetailScreen(onBack={ nav.popBackStack() }, onOperation={ nav.navigate(Routes.operation(it,id)) },
                    onAdvanced={ nav.navigate(Routes.serviceDetail(kind,id) + "/actions") }, onHistory={ nav.navigate(Routes.history(id,it)) })
            }
            composable(Routes.SERVICE_ACTIONS, arguments=listOf(navArgument("serviceId") { type=NavType.StringType }, navArgument("serverId") { type=NavType.StringType })) { entry ->
                val id=entry.arguments?.getString("serverId") ?: return@composable
                if (entry.arguments?.getString("serviceId") == "3x-ui") ServiceDetailScreen(onBack={ nav.popBackStack() }, onOperation={ nav.navigate(Routes.operation(it,id)) }, onAdvanced={}, onHistory={ nav.navigate(Routes.history(id,it)) }, )
                else ServiceActionsScreen(onBack={ nav.popBackStack() }, onOperation={ nav.navigate(Routes.operation(it,id)) })
            }
            composable(Routes.SERVER_SCRIPTS, arguments=listOf(navArgument("serverId") { type=NavType.StringType })) {
                ScriptsScreen(onBack={ nav.popBackStack() }, onFiles={ nav.navigate(Routes.section("files",view="scripts")) }, onOperation={ nav.navigate(Routes.operation(it)) }, onHistory={ nav.navigate(Routes.history(taskId=it)) })
            }
            composable(Routes.SCRIPTS) { ScriptsScreen(onFiles={ nav.navigate(Routes.section("files",view="scripts")) },onOperation={ nav.navigate(Routes.operation(it)) },onHistory={ nav.navigate(Routes.history(taskId=it)) }) }
            composable(Routes.SETTINGS) { SettingsScreen(onLogout=onLogout,onChangeUrl=onChangeUrl,onSection={ section ->
                if (section=="dashboard") nav.navigate(Routes.DASHBOARD) else if (section=="metrics") nav.navigate("metrics") else nav.navigate(Routes.section(section))
            }) }
            composable(Routes.SERVER_DETAIL,arguments=listOf(navArgument("serverId") { type=NavType.StringType })) { entry ->
                val id=entry.arguments?.getString("serverId") ?: return@composable
                ServerDetailScreen(serverId=id,onBack={ nav.popBackStack() },
                    onTerminal={ nav.navigate("terminal/${Uri.encode(id)}") },onMetrics={ nav.navigate("metrics?serverId=${Uri.encode(id)}") },
                    onEdit={ nav.navigate(Routes.serverSettings(id,"connection")) },
                    onAcceptHostKey={ nav.navigate(Routes.operation("POST /api/servers/{server_id}/quick-setup/ssh/hostkey/accept",id)) },
                    onSection={ if (it == "quick_setup") nav.navigate(Routes.serverSettings(id)) else nav.navigate(Routes.section(it,id)) },
                    onService={ nav.navigate(Routes.serviceDetail(it,id)) }, onScripts={ nav.navigate("server/${Uri.encode(id)}/scripts") }, onHistory={ nav.navigate(Routes.history(id,it)) })
            }
            composable(Routes.SERVER_SETTINGS, arguments=listOf(navArgument("serverId") { type=NavType.StringType }, navArgument("page") { type=NavType.StringType; defaultValue="" })) { entry ->
                val id = entry.arguments?.getString("serverId") ?: return@composable
                ServerSettingsScreen(onBack={ nav.popBackStack() })
            }
            composable(Routes.SECTION,arguments=listOf(navArgument("section") { type=NavType.StringType },navArgument("serverId") { type=NavType.StringType; nullable=true; defaultValue=null },navArgument("view") { type=NavType.StringType; defaultValue="" },navArgument("recordId") { type=NavType.StringType; defaultValue="" })) { entry ->
                val section=entry.arguments?.getString("section") ?: return@composable
                val id=entry.arguments?.getString("serverId")
                if (section == "quick_setup") {
                    if (id.isNullOrBlank()) ServerSettingsPickerScreen(onBack={ nav.popBackStack() }, onServer={ nav.navigate(Routes.serverSettings(it)) })
                    else ServerSettingsScreen(onBack={ nav.popBackStack() })
                } else if (section == "monitor") {
                    HostMonitorScreen(onBack = { nav.popBackStack() }, onTelegram = { nav.navigate(Routes.section("telegram")) }, onJournal = { nav.navigate("service-journal") }, onLogin = onLogout)
                } else if (section == "groups") GroupsScreen(onBack={ nav.popBackStack() })
                else if (section in setOf("settings", "security", "telegram", "update", "notifications")) PanelSettingsScreen(onBack={ nav.popBackStack() }, onOperation={ nav.navigate(Routes.operation(it,id)) }, onLogin=onLogout)
                else if (section == "backups") BackupsScreen(onBack={ nav.popBackStack() },onOperation={ nav.navigate(Routes.operation(it,id)) })
                else if (section == "audit") AuditScreen(onBack={ nav.popBackStack() },onTask={ nav.navigate(Routes.history(taskId=it)) },onGraph={ server,ts,record -> nav.navigate(Routes.metrics(server,ts,record)) })
                else if (section == "metrics") MetricsScreen(onBack={ nav.popBackStack() }, onAdvanced={ server -> nav.navigate(Routes.section("audit", server)) },onAudit={ server,record -> nav.navigate(Routes.audit(record,server)) })
                else NativeSectionScreen(section,onBack={ nav.popBackStack() },onOperation={ nav.navigate(Routes.operation(it,id)) }, onHistory=if(section == "events") ({ nav.navigate(Routes.TASKS) }) else null)
            }
            composable("service-journal") { ServiceJournalScreen(onBack={ nav.popBackStack() }, onLogin=onLogout) }
            composable(Routes.OPERATION,arguments=listOf(navArgument("operationId") { type=NavType.StringType },navArgument("serverId") { type=NavType.StringType; nullable=true; defaultValue=null })) {
                val id=it.arguments?.getString("serverId")
                if(it.arguments?.getString("operationId") == "POST /api/system/restart") HostMonitorScreen(onBack = { nav.popBackStack() },
                    onTelegram = { nav.navigate(Routes.section("telegram")) }, onJournal = { nav.navigate("service-journal") }, onLogin = onLogout, promptRestart = true)
                else NativeActionScreen(onBack={ nav.popBackStack() },onLogin=onLogout,onOperation={ next -> nav.navigate(Routes.operation(next,id)) })
            }
            composable(Routes.METRICS,arguments=listOf(navArgument("serverId") { type=NavType.StringType; nullable=true; defaultValue=null },navArgument("ts") { type=NavType.StringType; defaultValue="" },navArgument("recordId") { type=NavType.StringType; defaultValue="" })) {
                MetricsScreen(onBack={ nav.popBackStack() }, onAdvanced={ server -> nav.navigate(Routes.section("audit", server)) },onAudit={ server,record -> nav.navigate(Routes.audit(record,server)) })
            }
            composable(Routes.TERMINAL,arguments=listOf(navArgument("serverId") { type=NavType.StringType })) { TerminalScreen(onBack={ nav.popBackStack() }) }
        }
    }
}
