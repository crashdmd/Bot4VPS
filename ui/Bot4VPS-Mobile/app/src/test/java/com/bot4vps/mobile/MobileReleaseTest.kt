package com.bot4vps.mobile

import com.bot4vps.mobile.data.model.*
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class MobileReleaseTest {
    private fun manifest(vararg overrides: Pair<String, JsonElement>) = JsonObject(buildJsonObject {
        put("version", "1.2"); put("versionCode", 17); put("filename", "Bot4VPS-Mobile-1.2-release.apk")
        put("size", 3_000_000); put("sha256", "a".repeat(64)); put("changelog", "Новые возможности")
    } + overrides)
    @Test fun directoryDoesNotDependOnPanelOrReleaseTags() {
        val update = mobileReleaseFromDirectory(manifest(), "1.1", 16)!!
        assertEquals("https://raw.githubusercontent.com/crashdmd/Bot4VPS/main/ui/mobile/Bot4VPS-Mobile-1.2-release.apk", update.apkUrl)
        assertEquals("Новые возможности", update.notes)
    }
    @Test fun comparesNumbersInsteadOfStrings() {
        assertTrue(newerMobileVersion("1.10", "1.9"))
        assertTrue(newerMobileVersion("1.1.1", "1.1"))
        assertFalse(newerMobileVersion("1.1.0", "1.1"))
    }
    @Test fun installedOrOlderCodeCannotDowngrade() {
        assertNull(mobileReleaseFromDirectory(manifest(), "1.2", 17))
        assertNull(mobileReleaseFromDirectory(manifest(), "1.3", 18))
        assertNull(mobileReleaseFromDirectory(manifest("versionCode" to JsonPrimitive(16)), "1.1", 16))
    }
    @Test fun untrustedUrlIsIgnoredAndPathCannotEscape() {
        assertTrue(mobileReleaseFromDirectory(manifest("apkUrl" to JsonPrimitive("http://evil/apk")), "1.1", 16)!!.apkUrl.startsWith(MobileReleaseSource.DIRECTORY))
        assertThrows(IllegalArgumentException::class.java) { mobileReleaseFromDirectory(manifest("filename" to JsonPrimitive("../../secret")), "1.1", 16) }
    }
    @Test fun invalidHashAndUnboundedDownloadAreRejected() {
        for ((key, value) in listOf("sha256" to JsonPrimitive("z".repeat(64)), "size" to JsonPrimitive(0), "size" to JsonPrimitive(49_000_001))) {
            assertThrows(IllegalArgumentException::class.java) { mobileReleaseFromDirectory(manifest(key to value), "1.1", 16) }
        }
    }
    @Test fun missingFieldsDoNotBecomeAnUpdate() {
        assertThrows(IllegalArgumentException::class.java) { mobileReleaseFromDirectory(JsonObject(manifest().filterKeys { it != "versionCode" }), "1.1", 16) }
    }
    @Test fun arbitraryVersionNamesAreRejected() {
        assertThrows(IllegalArgumentException::class.java) { newerMobileVersion("../1.2", "1.1") }
        assertThrows(IllegalArgumentException::class.java) { newerMobileVersion("1.2-debug", "1.1") }
    }
    @Test fun releaseNotesAreBounded() {
        assertEquals(30_000, mobileReleaseFromDirectory(manifest("changelog" to JsonPrimitive("x".repeat(100_000))), "1.1", 16)!!.notes.length)
    }
}
