package com.bot4vps.mobile

import com.bot4vps.mobile.data.model.*
import com.bot4vps.mobile.ui.servers.SettingEditor
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class ServerSettingsDraftTest {
    private fun obj(value: String) = Json.parseToJsonElement(value).jsonObject
    private val saved = obj("""{"name":"VPN","group":"vps","host":"vpn.example.org","port":22,"user":"root","auth_type":"key","key_path":"/keys/a","certificate_check":true,"ssl_host":"vpn.example.org"}""")

    @Test fun renamingDoesNotTouchCredentials() {
        val draft = ServerSettingsDraft.from(saved).copy(name = "New VPN")
        assertEquals(obj("""{"name":"New VPN"}"""), draft.generalPatch(saved))
        assertTrue(draft.connectionPatch(saved).isEmpty())
    }
    @Test fun emptyPasswordKeepsExistingSecret() {
        val draft = ServerSettingsDraft.from(saved).copy(host = "new.example.org", password = "")
        assertFalse("password" in draft.connectionPatch(saved))
        assertEquals(obj("""{"host":"new.example.org"}"""), draft.connectionPatch(saved))
    }
    @Test fun newSudoPasswordIsIncludedForKeyAuthentication() {
        val draft = ServerSettingsDraft.from(saved).copy(user = "admin", password = "new secret")
        assertEquals(JsonPrimitive("new secret"), draft.connectionPatch(saved)["password"])
        assertFalse("key_path" in draft.connectionPatch(saved))
    }
    @Test fun changingGroupPreservesUserSslPreference() {
        val draft = ServerSettingsDraft.from(saved).copy(group = "home", sslEnabled = false)
        assertEquals(JsonPrimitive(false), draft.generalPatch(saved)["certificate_check"])
        assertEquals(JsonPrimitive("vpn.example.org"), draft.generalPatch(saved)["ssl_host"])
    }
    @Test fun clearingSslDomainUsesExplicitEmptyString() {
        assertEquals(JsonPrimitive(""), ServerSettingsDraft.from(saved).copy(sslHost = "").generalPatch(saved)["ssl_host"])
    }
    @Test fun invalidPortCannotBeSaved() {
        for (port in listOf("", "abc", "0", "65536")) assertNotNull(ServerSettingsDraft.from(saved).copy(port = port).connectionError())
        assertNull(ServerSettingsDraft.from(saved).copy(port = "2222").connectionError())
    }
    @Test fun firewallContinuationRequiresServerTokenAndVerifiedRollback() {
        assertNull(ServerFirewallDecision.from(obj("""{"data":{"decision_required":"skip_ambiguous_rules"}}""")))
        assertNull(ServerFirewallDecision.from(obj("""{"data":{"decision_required":"skip_failed_rules","continue_with":{"token":"t"},"rollback":{"verified":false}}}""")))
        assertNotNull(ServerFirewallDecision.from(obj("""{"data":{"decision_required":"skip_failed_rules","continue_with":{"token":"t"},"rollback":{"verified":true}}}""")))
    }
    @Test fun firewallChoiceSendsOnlySelectedRuleIdentity() {
        val result = obj("""{"data":{"decision_required":"skip_ambiguous_rules","continue_with":{"token":"server-issued"},"migratable_rules":[{"port":80,"protocol":"tcp","source":"","from":["ufw"]},{"port":443,"protocol":"tcp","source":""}]}}""")
        val decision = ServerFirewallDecision.from(result)!!
        val body = decision.body(obj("""{"target":"nftables","confirm":true}"""), setOf(1))
        assertEquals(obj("""{"token":"server-issued"}"""), body["continuation"])
        assertEquals(Json.parseToJsonElement("""[{"port":443,"protocol":"tcp","source":""}]"""), body["selected_rules"])
        assertEquals(JsonArray(emptyList()), decision.body(obj("""{"target":"nftables","confirm":true}"""), emptySet())["selected_rules"])
    }
    @Test fun clearingExistingConfigurationIsAnExplicitEdit() {
        val editor = SettingEditor("jail", "custom.local", content = "[sshd]", original = "[sshd]")
        assertFalse(editor.dirty)
        assertTrue(editor.copy(content = "").dirty)
    }
    @Test fun untouchedNewConfigurationDoesNotPromptToDiscard() {
        val editor = SettingEditor("jail", "", create = true)
        assertFalse(editor.dirty)
        assertTrue(editor.copy(filename = "custom.local").dirty)
    }

}
