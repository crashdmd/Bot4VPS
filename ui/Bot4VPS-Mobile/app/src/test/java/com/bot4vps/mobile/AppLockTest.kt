package com.bot4vps.mobile

import com.bot4vps.mobile.data.local.AppLockState
import com.bot4vps.mobile.data.model.*
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.*
import org.junit.Test
import javax.crypto.Cipher
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

class AppLockTest {
    private val fixture = LockPin("00".repeat(32), "11".repeat(32))
    @Test fun coldStartDoesNotExposeContent() {
        assertFalse(AppLockState().allowsContent)
        assertTrue(AppLockState().protectsContent)
        assertNull(LockSession().ticket())
    }
    @Test fun configuredColdStartNeedsAuthentication() {
        val session = LockSession(); session.foreground(); session.loaded(true)
        assertEquals(LockPhase.LOCKED, session.phase)
        assertTrue(session.unlock(session.ticket()!!))
        assertEquals(LockPhase.UNLOCKED, session.phase)
    }
    @Test fun backgroundInvalidatesAnInFlightAuthentication() {
        val session = LockSession(); session.foreground(); session.loaded(true)
        val old = session.ticket()!!
        session.background(); session.foreground()
        assertFalse(session.unlock(old))
        assertEquals(LockPhase.LOCKED, session.phase)
        assertTrue(session.unlock(session.ticket()!!))
    }
    @Test fun successfulProofCannotBeReused() {
        val session = LockSession(); session.foreground(); session.loaded(true)
        val old = session.ticket()!!
        assertTrue(session.unlock(old)); session.lock()
        assertFalse(session.unlock(old))
    }
    @Test fun changingProtectionInvalidatesOldProofs() {
        val session = LockSession(); session.foreground(); session.loaded(true)
        val old = session.ticket()!!
        session.configured(true); session.lock()
        assertFalse(session.unlock(old))
    }
    @Test fun damagedConfigurationCannotUnlock() {
        val session = LockSession(); session.foreground(); session.loaded(true)
        val old = session.ticket()!!; session.unavailable()
        assertFalse(session.valid(old)); assertFalse(session.unlock(old))
        assertFalse(AppLockState(phase = LockPhase.UNAVAILABLE).allowsContent)
        assertTrue(AppLockState(phase = LockPhase.UNAVAILABLE).protectsContent)
    }
    @Test fun backgroundAlwaysLocksAnAuthenticatedSession() {
        val session = LockSession(); session.foreground(); session.loaded(true)
        session.unlock(session.ticket()!!); session.background()
        assertEquals(LockPhase.LOCKED, session.phase)
        assertNull(session.ticket())
    }
    @Test fun disabledProtectionRemainsDisabled() {
        val session = LockSession(); session.foreground(); session.loaded(false); session.background(); session.foreground()
        assertEquals(LockPhase.DISABLED, session.phase)
        assertTrue(AppLockState(phase = LockPhase.DISABLED).allowsContent)
        assertFalse(AppLockState(phase = LockPhase.DISABLED).protectsContent)
    }
    @Test fun fiveWrongAttemptsRequireWaiting() {
        var record = AppLockRecord(fixture)
        repeat(4) { record = record.failed(10_000); assertEquals(0L, record.retryAt) }
        record = record.failed(10_000)
        assertEquals(30_000L, record.remainingMillis(10_000))
        assertEquals(0L, record.remainingMillis(40_000))
    }
    @Test fun attemptDelayEscalatesAndIsBounded() {
        var record = AppLockRecord(fixture)
        repeat(10) { record = record.failed(100_000) }
        assertEquals(60_000L, record.remainingMillis(100_000))
        repeat(100) { record = record.failed(100_000) }
        assertEquals(300_000L, record.remainingMillis(100_000))
    }
    @Test fun retryStateSurvivesSerializationAndResetsOnSuccess() {
        val locked = AppLockRecord(fixture, failedAttempts = 5, retryAt = 50_000)
        val restored = Json.decodeFromString<AppLockRecord>(Json.encodeToString(locked))
        assertEquals(30_000L, restored.remainingMillis(20_000))
        assertEquals(0, restored.successful().failedAttempts)
        assertEquals(0L, restored.successful().retryAt)
    }
    @Test fun missingOrUnsupportedRecordsAreRejected() {
        assertThrows(Exception::class.java) { decodeAppLockRecord("{}") }
        assertThrows(IllegalArgumentException::class.java) { AppLockRecord(fixture, version = 3).validate() }
        assertThrows(IllegalArgumentException::class.java) { fixture.copy(iterations = 1).validate() }
        assertThrows(IllegalArgumentException::class.java) { fixture.copy(digest = "bad").validate() }
    }
    @Test fun unsafeBiometricRecordsAreRejected() {
        assertThrows(IllegalArgumentException::class.java) { LockBiometricSeal("bot4vps-session", "00".repeat(12), "11".repeat(32)).validate() }
        assertThrows(IllegalArgumentException::class.java) { LockBiometricSeal("bot4vps-lock-12345678", "00", "11".repeat(32)).validate() }
    }
    @Test fun pinHasIndependentRandomSaltAndNoPlaintextRecord() {
        val secret = "0123"
        val first = LockPin.create(secret.toCharArray()); val second = LockPin.create(secret.toCharArray())
        assertNotEquals(first.salt, second.salt); assertNotEquals(first.digest, second.digest)
        assertTrue(first.verify(secret.toCharArray()))
        assertFalse(first.verify("4321".toCharArray()))
        assertFalse(Json.encodeToString(first).contains("\"$secret\""))
    }
    @Test fun pinKeepsLeadingZeros() {
        val digest = LockPin.create("0123".toCharArray())
        assertTrue(digest.verify("0123".toCharArray()))
        assertFalse(digest.verify("123".toCharArray()))
        assertFalse(digest.verify("1123".toCharArray()))
    }
    @Test fun pbkdf2MatchesIndependentUtf8Vector() {
        val expected = LockPin(ByteArray(32) { it.toByte() }.lockHex(), "28dc0c5be25afde12deb89e429164dec83e8ed670cff04fb0ffc4565e0c70782")
        assertTrue(expected.verify("Bot4VPS пароль".toCharArray()))
    }
    @Test fun settingSavedAfterBackgroundDoesNotReopenTheApp() {
        val session = LockSession(); session.foreground(); session.loaded(true)
        session.unlock(session.ticket()!!)
        val settingTicket = session.ticket()!!
        session.background(); session.foreground()
        session.configured(true, settingTicket)
        assertEquals(LockPhase.LOCKED, session.phase)
    }
    @Test fun onlyFourAsciiDigitsCanBeUsedForNewPin() {
        listOf("", "123", "12345", "12a4", " 123", "١٢٣٤", "１２３４").forEach { password ->
            assertThrows(IllegalArgumentException::class.java) { LockPin.create(password.toCharArray()) }
        }
    }
    @Test fun legacyRecordWithoutVersionStillRequiresMigration() {
        val raw = """{"password":{"salt":"${fixture.salt}","digest":"${fixture.digest}"},"failedAttempts":5,"retryAt":50000}"""
        val saved = decodeAppLockRecord(raw)
        assertTrue(saved.needsPin)
        assertEquals(1, saved.version)
        assertNull(saved.pin)
        assertEquals(fixture, saved.credential)
        assertEquals(30_000L, saved.remainingMillis(20_000))
    }
    @Test fun legacyRecordWithExplicitVersionRemainsProtected() {
        val saved = decodeAppLockRecord(Json.encodeToString(AppLockRecord(password = fixture, version = 1)))
        assertTrue(saved.needsPin)
        assertFalse(AppLockState(phase = LockPhase.LOCKED, legacyPassword = true, needsPinSetup = true).allowsContent)
    }
    @Test fun newPinRecordDiscardsOldPassword() {
        val saved = AppLockRecord(pin = fixture)
        val raw = Json.encodeToString(saved)
        assertFalse(raw.contains("password"))
        val decoded = decodeAppLockRecord(raw)
        assertFalse(decoded.needsPin)
        assertEquals(2, decoded.version)
        assertNull(decoded.password)
    }
    @Test fun ambiguousOrMissingCredentialsAreRejected() {
        listOf(AppLockRecord(), AppLockRecord(pin = fixture, password = fixture),
            AppLockRecord(pin = fixture, version = 1)).forEach { saved ->
            assertThrows(IllegalArgumentException::class.java) { decodeAppLockRecord(Json.encodeToString(saved)) }
        }
        assertThrows(IllegalArgumentException::class.java) {
            decodeAppLockRecord("""{"version":2,"password":{"salt":"${fixture.salt}","digest":"${fixture.digest}"}}""")
        }
    }
    @Test fun fourDigitPinMatchesIndependentPbkdf2Vector() {
        val expected = LockPin(ByteArray(32) { it.toByte() }.lockHex(), "d7ebc688905c80a0da69967d6d3f7a93dc8978468ebfe75a66bfaf306c47a48f")
        assertTrue(expected.verify("0123".toCharArray()))
        assertFalse(expected.verify("3210".toCharArray()))
    }
    @Test fun protectedNotificationContainsNoEventDetails() {
        val event = buildJsonObject { put("title", "secret.example.com 10.0.0.1"); put("message", "Private server error") }
        val preview = phoneEventPreview(event, true)
        assertEquals("Новое событие Bot4VPS", preview.first)
        assertFalse(preview.toString().contains("secret.example.com"))
        assertFalse(preview.toString().contains("Private server error"))
        assertEquals("Private server error", phoneEventPreview(event, false).second)
    }
    @Test fun biometricPayloadIsAuthenticatedWithTheExistingAlias() {
        val key = SecretKeySpec(ByteArray(32) { it.toByte() }, "AES")
        val alias = "bot4vps-lock-test-biometric-payload"
        val encrypt = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key) }
        val seal = LockBiometricCipher.seal(alias, encrypt)
        val decrypt = Cipher.getInstance("AES/GCM/NoPadding").apply {
            init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(128, seal.iv.lockBytes()))
        }
        assertTrue(LockBiometricCipher.verify(seal, decrypt))
        val wrongAlias = seal.copy(alias = "bot4vps-lock-another-biometric-payload")
        val wrong = Cipher.getInstance("AES/GCM/NoPadding").apply {
            init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(128, seal.iv.lockBytes()))
        }
        assertThrows(Exception::class.java) { LockBiometricCipher.verify(wrongAlias, wrong) }
    }
    @Test fun existingBiometricPayloadRemainsReadableAfterAuthTimingFix() {
        val key = SecretKeySpec(ByteArray(32) { it.toByte() }, "AES")
        val alias = "bot4vps-lock-existing-biometric-payload"
        val old = Cipher.getInstance("AES/GCM/NoPadding").apply {
            init(Cipher.ENCRYPT_MODE, key)
            updateAAD(alias.toByteArray(Charsets.UTF_8))
        }
        val payload = LockBiometricSeal(alias, old.iv.lockHex(), old.doFinal("Bot4VPS local biometric unlock v1".toByteArray(Charsets.UTF_8)).lockHex())
        val current = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(128, payload.iv.lockBytes())) }
        assertTrue(LockBiometricCipher.verify(payload, current))
    }
}
