package com.bot4vps.mobile

import com.bot4vps.mobile.data.model.*
import org.junit.Assert.*
import org.junit.Test

class ScriptValuesTest {
    @Test fun switchingOffAnOptionDoesNotSendItsPreviouslyEnteredPassword() {
        val script=ScriptInfo("baseconf.sh",params=listOf(ScriptParam("CREATE_ADMIN","bool"),ScriptParam("ADMIN_PASS","password",condition="CREATE_ADMIN:true")))
        val values=mapOf("CREATE_ADMIN" to "false","ADMIN_PASS" to "previous-password")
        assertEquals(mapOf("CREATE_ADMIN" to "false"),scriptRunValues(script,values))
        assertEquals("previous-password",scriptRunValues(script,values+("CREATE_ADMIN" to "TRUE"))["ADMIN_PASS"])
    }
    @Test fun blankParametersAreOmittedAsInTheWebForm() {
        val script=ScriptInfo("cert.sh",params=listOf(ScriptParam("MODE","select"),ScriptParam("DOMAINS",condition="MODE:issue")))
        assertEquals(mapOf("MODE" to "issue"),scriptRunValues(script,mapOf("MODE" to "issue","DOMAINS" to "")))
        assertTrue(ScriptParam("other",condition="malformed").visible(emptyMap()))
    }
}
