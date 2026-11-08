package com.bot4vps.mobile

import com.bot4vps.mobile.data.model.connectionTarget
import kotlinx.serialization.json.*
import org.junit.Assert.assertEquals
import org.junit.Test

class ApiConnectionTargetTest {
    @Test fun privateWebChangesKeepThePublicApiAddress() {
        val base = "https://bot.example.com:8444/"
        assertEquals(base, connectionTarget(base, "POST /api/settings/web/port", buildJsonObject { put("port", 8081) }, mobileApi = true))
        assertEquals(base, connectionTarget(base, "POST /api/settings/web/tls/off", JsonObject(emptyMap()), mobileApi = true))
        assertEquals("http://bot.example.com:8080/", connectionTarget("https://bot.example.com:8080/", "POST /api/settings/web/tls/off", JsonObject(emptyMap())))
    }
}
