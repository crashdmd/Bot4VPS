package com.bot4vps.mobile

import com.bot4vps.mobile.data.model.*
import org.junit.Assert.*
import org.junit.Test

class ServerListDetailTest {
    @Test fun certificateDisplayDistinguishesMissingExpiredAndDisabled() {
        assertEquals("SSL: нет данных о сроке", serverListDetail(ServerSummary("a"),ServerListSort.SSL))
        assertEquals("SSL: осталось 7 дн.", serverListDetail(ServerSummary("a",sslDaysLeft=7),ServerListSort.SSL))
        assertEquals("SSL: истекает сегодня", serverListDetail(ServerSummary("a",sslDaysLeft=0),ServerListSort.SSL))
        assertEquals("SSL: истёк 2 дн. назад", serverListDetail(ServerSummary("a",sslDaysLeft=-2),ServerListSort.SSL))
        assertEquals("SSL: проверка выключена", serverListDetail(ServerSummary("a",certificateCheck=false,sslDaysLeft=7),ServerListSort.SSL))
    }
    @Test fun uptimeUsesSecondsAndDoesNotTurnMissingDataIntoZero() {
        assertEquals("Время работы: 2 д. 3 ч.",serverListDetail(ServerSummary("a",uptimeSeconds=183600.5,uptime="old"),ServerListSort.UPTIME))
        assertEquals("Время работы: меньше минуты",serverListDetail(ServerSummary("a",uptimeSeconds=0.0),ServerListSort.UPTIME))
        assertEquals("Время работы: нет данных",serverListDetail(ServerSummary("a",uptimeSeconds=Double.NaN),ServerListSort.UPTIME))
        assertEquals("Время работы: 9 ч.",serverListDetail(ServerSummary("a",uptime="9 ч."),ServerListSort.UPTIME))
    }
    @Test fun groupAndConnectionModesShowTheirOwnData() {
        assertEquals("Без группы",serverListDetail(ServerSummary("a",group="—"),ServerListSort.GROUP))
        assertEquals("Группа: Дом",serverListDetail(ServerSummary("a",group="Дом"),ServerListSort.GROUP))
        assertEquals("В сети · ошибка SSH",serverListDetail(ServerSummary("a",online=true,sshError="Нет ключа"),ServerListSort.STATUS))
    }
}
