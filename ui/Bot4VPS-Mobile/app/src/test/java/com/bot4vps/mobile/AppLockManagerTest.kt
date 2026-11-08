package com.bot4vps.mobile

import com.bot4vps.mobile.data.local.*
import com.bot4vps.mobile.data.model.*
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.*
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import org.junit.Assert.*
import org.junit.Test
import java.util.UUID
import javax.crypto.Cipher
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

@OptIn(ExperimentalCoroutinesApi::class)
class AppLockManagerTest {
    private val digest = LockPin(ByteArray(32) { it.toByte() }.lockHex(), "d7ebc688905c80a0da69967d6d3f7a93dc8978468ebfe75a66bfaf306c47a48f")
    private class MemoryStorage(var value: String?) : AppLockStorage {
        override fun read() = value
        override fun write(value: String?) { this.value = value }
        val record get() = value?.let(::decodeAppLockRecord)
    }
    private class Biometrics : AppLockBiometricOperations {
        val key = SecretKeySpec(ByteArray(32) { it.toByte() }, "AES")
        var enrollments = 0
        var sealCalls = 0
        var authorized = false
        var enrollmentError: Exception? = null
        var onEnrolled: (() -> Unit)? = null
        val removed = mutableListOf<String>()
        override fun enrollment(): Pair<String, Cipher> {
            enrollments++
            enrollmentError?.let { throw it }
            val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key) }
            onEnrolled?.invoke()
            return "bot4vps-lock-${UUID.randomUUID()}" to cipher
        }
        override fun seal(alias: String, cipher: Cipher): LockBiometricSeal {
            check(authorized) { "Authentication must precede any payload operation" }
            sealCalls++
            return LockBiometricCipher.seal(alias, cipher)
        }
        override fun decrypt(seal: LockBiometricSeal): Cipher = Cipher.getInstance("AES/GCM/NoPadding").apply {
            init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(128, seal.iv.lockBytes()))
        }
        override fun verify(seal: LockBiometricSeal, cipher: Cipher): Boolean {
            check(authorized)
            return LockBiometricCipher.verify(seal, cipher)
        }
        override fun remove(alias: String?) { if (alias != null) removed += alias }
    }
    private data class Fixture(val manager: AppLockManager, val storage: MemoryStorage, val biometrics: Biometrics)
    private fun TestScope.fixture(record: AppLockRecord? = AppLockRecord(pin = digest)): Fixture {
        val storage = MemoryStorage(record?.let { Json.encodeToString(it) })
        val biometrics = Biometrics()
        val dispatcher = StandardTestDispatcher(testScheduler)
        val manager = AppLockManager(storage, biometrics, backgroundScope, dispatcher, dispatcher)
        manager.foreground(); runCurrent()
        return Fixture(manager, storage, biometrics)
    }
    private fun TestScope.unlock(fixture: Fixture) {
        fixture.manager.unlock("0123"); runCurrent()
        assertTrue(fixture.manager.state.value.allowsContent)
    }
    @Test fun samePinUnlocksEnablesBiometricsAndDisablesLock() = runTest {
        val f = fixture(); unlock(f)
        f.manager.setBiometric(true, "0123"); runCurrent()
        val pending = f.manager.prompt.value!!
        assertNull(f.manager.state.value.error)
        assertEquals(0, f.storage.record!!.failedAttempts)
        assertEquals(0, f.biometrics.sealCalls)
        assertFalse(f.manager.state.value.biometricEnabled)
        f.biometrics.authorized = true
        f.manager.biometricResult(pending.cipher); runCurrent()
        assertTrue(f.manager.state.value.biometricEnabled)
        assertTrue(f.storage.record!!.credential.verify("0123".toCharArray()))
        assertEquals(1, f.biometrics.sealCalls)
        f.manager.disable("0123"); runCurrent()
        assertNull(f.storage.value)
        assertEquals(LockPhase.DISABLED, f.manager.state.value.phase)
    }
    @Test fun wrongPinNeverStartsBiometricEnrollment() = runTest {
        val f = fixture(); unlock(f)
        f.manager.setBiometric(true, "3210"); runCurrent()
        assertEquals("Неверный PIN-код", f.manager.state.value.error)
        assertEquals(1, f.storage.record!!.failedAttempts)
        assertEquals(0, f.biometrics.enrollments)
        assertNull(f.manager.prompt.value)
    }
    @Test fun keyPreparationFailureIsNotReportedAsWrongPin() = runTest {
        val f = fixture(); unlock(f)
        f.biometrics.enrollmentError = IllegalStateException("Неверный PIN-код")
        f.manager.setBiometric(true, "0123"); runCurrent()
        assertTrue(f.manager.state.value.error!!.startsWith("Не удалось подготовить биометрию"))
        assertEquals(0, f.storage.record!!.failedAttempts)
        assertFalse(f.manager.state.value.biometricEnabled)
        f.manager.disable("0123"); runCurrent()
        assertEquals(LockPhase.DISABLED, f.manager.state.value.phase)
    }
    @Test fun canceledBiometricsCanBeEnabledOnNextAttempt() = runTest {
        val f = fixture(); unlock(f)
        f.manager.setBiometric(true, "0123"); runCurrent()
        val old = f.manager.prompt.value!!
        f.manager.biometricError(old.cipher, null); runCurrent()
        assertTrue(f.biometrics.removed.contains(old.enrollmentAlias))
        assertNull(f.storage.record!!.biometric)
        f.manager.setBiometric(true, "0123"); runCurrent()
        val current = f.manager.prompt.value!!
        f.manager.biometricError(old.cipher, "late cancellation")
        f.manager.biometricResult(old.cipher); runCurrent()
        assertSame(current, f.manager.prompt.value)
        assertNull(f.manager.state.value.error)
        f.biometrics.authorized = true
        f.manager.biometricResult(current.cipher); runCurrent()
        assertTrue(f.manager.state.value.biometricEnabled)
    }
    @Test fun backgroundDuringKeyPreparationRemovesUnusedKey() = runTest {
        val f = fixture(); unlock(f)
        f.biometrics.onEnrolled = f.manager::background
        f.manager.setBiometric(true, "0123"); runCurrent()
        assertNull(f.manager.prompt.value)
        assertFalse(f.manager.state.value.allowsContent)
        assertNull(f.storage.record!!.biometric)
        assertEquals(1, f.biometrics.removed.size)
    }
    @Test fun successfulEnrollmentAllowsBiometricUnlock() = runTest {
        val f = fixture(); unlock(f)
        f.manager.setBiometric(true, "0123"); runCurrent()
        f.biometrics.authorized = true
        f.manager.biometricResult(f.manager.prompt.value!!.cipher); runCurrent()
        f.manager.lock()
        f.manager.biometricUnlock(); runCurrent()
        assertFalse(f.manager.state.value.allowsContent)
        f.manager.biometricResult(f.manager.prompt.value!!.cipher); runCurrent()
        assertTrue(f.manager.state.value.allowsContent)
        assertEquals(0, f.storage.record!!.failedAttempts)
    }
    @Test fun newPinNeedsCurrentAuthenticationAndProofExpiresInBackground() = runTest {
        val f = fixture(); unlock(f)
        f.manager.setPin(null, "3456", "3456"); runCurrent()
        assertEquals("Введите текущий PIN-код", f.manager.state.value.error)
        f.manager.authorizePinChange("3210"); runCurrent()
        assertFalse(f.manager.state.value.pinChangeAuthorized)
        f.manager.authorizePinChange("0123"); runCurrent()
        assertTrue(f.manager.state.value.pinChangeAuthorized)
        f.manager.background(); f.manager.foreground()
        f.manager.setPin(null, "3456", "3456"); runCurrent()
        assertEquals("Введите текущий PIN-код", f.manager.state.value.error)
        assertFalse(f.manager.state.value.allowsContent)
        assertTrue(f.storage.record!!.credential.verify("0123".toCharArray()))
    }
    @Test fun newPinIsSavedOnlyAfterCurrentPinAndMatchingRepeat() = runTest {
        val f = fixture(); unlock(f)
        f.manager.authorizePinChange("0123"); runCurrent()
        f.manager.setPin(null, "3456", "3457"); runCurrent()
        assertEquals("PIN-коды не совпадают", f.manager.state.value.error)
        assertTrue(f.storage.record!!.credential.verify("0123".toCharArray()))
        f.manager.setPin(null, "3456", "3456"); runCurrent()
        assertFalse(f.manager.state.value.pinChangeAuthorized)
        assertTrue(f.storage.record!!.credential.verify("3456".toCharArray()))
        f.manager.lock(); f.manager.unlock("3456"); runCurrent()
        assertTrue(f.manager.state.value.allowsContent)
    }
    @Test fun pinChangeProofDoesNotAuthorizeBiometricChanges() = runTest {
        val f = fixture(); unlock(f)
        f.manager.authorizePinChange("0123"); runCurrent()
        f.manager.setBiometric(true, "3210"); runCurrent()
        assertEquals("Неверный PIN-код", f.manager.state.value.error)
        assertEquals(0, f.biometrics.enrollments)
    }
    @Test fun canceledPinChangeCannotSaveNewPin() = runTest {
        val f = fixture(); unlock(f)
        f.manager.authorizePinChange("0123"); runCurrent()
        f.manager.cancelPinChange()
        f.manager.setPin(null, "3456", "3456"); runCurrent()
        assertEquals("Введите текущий PIN-код", f.manager.state.value.error)
        assertTrue(f.storage.record!!.credential.verify("0123".toCharArray()))
    }
    @Test fun initialPinRequiresMatchingRepeatAndSurvivesReload() = runTest {
        val f = fixture(null)
        f.manager.setPin(null, "0123", "0124"); runCurrent()
        assertNull(f.storage.value)
        f.manager.setPin(null, "0123", "0123"); runCurrent()
        assertTrue(f.manager.state.value.allowsContent)
        f.manager.reload(); runCurrent()
        assertEquals(LockPhase.LOCKED, f.manager.state.value.phase)
        unlock(f)
    }
    @Test fun legacyCredentialMustBeConfirmedBeforeNewPinIsSaved() = runTest {
        val f = fixture(AppLockRecord(password = digest, version = 1))
        f.manager.setPin(null, "3456", "3456"); runCurrent()
        assertTrue(f.storage.record!!.needsPin)
        f.manager.unlock("0123"); runCurrent()
        assertTrue(f.manager.state.value.needsPinSetup)
        assertFalse(f.manager.state.value.allowsContent)
        f.manager.setPin(null, "3456", "3456"); runCurrent()
        assertFalse(f.storage.record!!.needsPin)
        assertNull(f.storage.record!!.password)
        assertTrue(f.storage.record!!.credential.verify("3456".toCharArray()))
        assertTrue(f.manager.state.value.allowsContent)
    }
    @Test fun disposingPinEntryDoesNotEraseBiometricFailure() = runTest {
        val f = fixture(); unlock(f)
        f.manager.setBiometric(true, "0123"); runCurrent()
        f.manager.biometricResult(f.manager.prompt.value!!.cipher); runCurrent()
        val error = f.manager.state.value.error
        assertTrue(error!!.startsWith("Не удалось включить биометрию"))
        f.manager.cancelPinChange()
        assertEquals(error, f.manager.state.value.error)
        assertNull(f.storage.record!!.biometric)
        assertEquals(0, f.storage.record!!.failedAttempts)
    }
}
