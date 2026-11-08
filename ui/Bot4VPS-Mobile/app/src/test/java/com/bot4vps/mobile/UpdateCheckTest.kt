package com.bot4vps.mobile

import com.bot4vps.mobile.data.api.ApiError
import com.bot4vps.mobile.data.repository.checkPanelUpdate
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class UpdateCheckTest {
    @Test fun successfulCheckDoesNotNeedTheMaintenanceRoute() = runBlocking {
        val calls = mutableListOf<String>()
        val result = checkPanelUpdate { method, path ->
            calls += "$method $path"
            when(path) {
                "/api/update/check" -> buildJsonObject { put("update_available", false) }
                "/api/update/state" -> buildJsonObject { put("status", "idle"); put("available", JsonNull) }
                else -> throw ApiError(404, "Not Found")
            }
        }
        assertEquals(listOf("POST /api/update/check", "GET /api/update/state"), calls)
        assertNull(result.error)
        assertEquals("Установлена актуальная версия", result.message)
    }
    @Test fun aFailedCheckWithHttp200IsNeverPresentedAsUpToDate() = runBlocking {
        val result = checkPanelUpdate { method, _ ->
            if(method == "POST") buildJsonObject { put("error", "Нет соединения") }
            else buildJsonObject { put("available", JsonNull) }
        }
        assertEquals("Нет соединения", result.error)
        assertNull(result.message)
    }
    @Test fun stateCarriesTheCheckFailureOrTheAvailableVersion() = runBlocking {
        val failed = checkPanelUpdate { method, _ -> if(method == "POST") JsonObject(emptyMap()) else buildJsonObject { put("last_check_error", "Ошибка загрузки") } }
        assertEquals("Ошибка загрузки", failed.error)
        assertNull(failed.message)
        val found = checkPanelUpdate { method, _ -> if(method == "POST") JsonObject(emptyMap()) else buildJsonObject { put("available", buildJsonObject { put("version", "6.4.0") }) } }
        assertNull(found.error)
        assertEquals("Найдено обновление", found.message)
    }
}
