package com.bot4vps.mobile

import com.bot4vps.mobile.data.model.*
import kotlinx.coroutines.*
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class MasterKeyViewTest {
    private fun response(vararg fields: Pair<String, String>) = buildJsonObject { put("ok", true); fields.forEach { (key, value) -> put(key, value) } }
    @Test fun passwordStepReplacesItselfWithOtpWithoutKeepingCredentials() = runBlocking {
        val calls = mutableListOf<Pair<String, JsonObject>>()
        val viewer = MasterKeyViewer({ path, body -> calls += path to body; response("channel" to "totp") })
        viewer.begin("panel-password")
        assertEquals(MasterKeyStep.CODE, viewer.state.value.step)
        assertEquals("totp", viewer.state.value.channel)
        assertNull(viewer.state.value.key)
        assertFalse(viewer.state.value.toString().contains("panel-password"))
        assertEquals("/api/masterkey/view", calls.single().first)
    }
    @Test fun keyRequiresBothStepsAndReplacesCodeActions() = runBlocking {
        val calls = mutableListOf<String>()
        val viewer = MasterKeyViewer({ path, _ -> calls += path; if (path.endsWith("/confirm")) response("key" to "master-secret") else response("channel" to "totp") })
        viewer.confirm("123456"); assertTrue(calls.isEmpty())
        viewer.begin("password"); viewer.confirm("123456")
        assertEquals(MasterKeyStep.KEY, viewer.state.value.step)
        assertEquals("master-secret", viewer.state.value.key)
        assertNull(viewer.state.value.channel)
        viewer.close(); assertNull(viewer.state.value.key)
        assertEquals(MasterKeyStep.PASSWORD, viewer.state.value.step)
    }
    @Test fun wrongPasswordNeverAdvances() = runBlocking {
        val viewer = MasterKeyViewer({ _, _ -> error("Неверный пароль") })
        viewer.begin("wrong")
        assertEquals(MasterKeyStep.PASSWORD, viewer.state.value.step)
        assertEquals("Неверный пароль", viewer.state.value.error)
        assertNull(viewer.state.value.key)
    }
    @Test fun wrongCodeKeepsOnlyTheCodeStep() = runBlocking {
        val viewer = MasterKeyViewer({ path, _ -> if (path.endsWith("/confirm")) error("Неверный код") else response("channel" to "totp") })
        viewer.begin("password"); viewer.confirm("123456")
        assertEquals(MasterKeyStep.CODE, viewer.state.value.step)
        assertEquals("Неверный код", viewer.state.value.error)
        assertNull(viewer.state.value.key)
    }
    @Test fun resendIsOnlyForTelegramAfterCooldown() = runBlocking {
        var now = 100_000L; val calls = mutableListOf<String>()
        val viewer = MasterKeyViewer({ path, _ -> calls += path; response("channel" to "telegram") }, { now })
        viewer.begin("password"); viewer.resend(); assertEquals(1, calls.size)
        now += 120_000; viewer.resend(); assertEquals(2, calls.size)
        assertEquals("/api/masterkey/view/resend", calls.last())
        assertEquals(now + 120_000, viewer.state.value.resendAt)
    }
    @Test fun totpHasNoResendAction() = runBlocking {
        val calls = mutableListOf<String>()
        val viewer = MasterKeyViewer({ path, _ -> calls += path; response("channel" to "totp") })
        viewer.begin("password"); viewer.resend(); assertEquals(1, calls.size)
    }
    @Test fun unexpectedChannelDoesNotSkipOwnerConfirmation() = runBlocking {
        val viewer = MasterKeyViewer({ _, _ -> response("channel" to "none", "key" to "unexpected-secret") })
        viewer.begin("password")
        assertEquals(MasterKeyStep.PASSWORD, viewer.state.value.step)
        assertNull(viewer.state.value.key)
    }
    @Test fun closingDialogDiscardsALateKeyResponse() = runBlocking {
        val entered = CompletableDeferred<Unit>(); val finish = CompletableDeferred<JsonObject>()
        val viewer = MasterKeyViewer({ path, _ -> if (path.endsWith("/confirm")) { entered.complete(Unit); finish.await() } else response("channel" to "totp") })
        viewer.begin("password")
        val job = launch { viewer.confirm("123456") }
        entered.await(); viewer.close(); finish.complete(response("key" to "late-secret")); job.join()
        assertEquals(MasterKeyStep.PASSWORD, viewer.state.value.step)
        assertNull(viewer.state.value.key)
    }
    @Test fun malformedCodeDoesNotReachTheServer() = runBlocking {
        val calls = mutableListOf<String>()
        val viewer = MasterKeyViewer({ path, _ -> calls += path; response("channel" to "totp") })
        viewer.begin("password"); viewer.confirm("12345"); viewer.confirm("12345x")
        assertEquals(1, calls.size)
    }
}
