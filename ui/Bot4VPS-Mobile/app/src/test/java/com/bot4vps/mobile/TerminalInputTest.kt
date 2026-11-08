package com.bot4vps.mobile

import com.bot4vps.mobile.ui.terminal.TerminalInput
import org.junit.Assert.*
import org.junit.Test

class TerminalInputTest {
    @Test fun nanoSaveAndExitWithOneShotCtrl() {
        val input = TerminalInput()
        input.toggleCtrl()
        assertEquals("\u000f", input.text("o"))
        assertFalse(input.ctrl)
        assertEquals("file.txt", input.text("file.txt"))
        input.toggleCtrl()
        assertEquals("\u0018", input.text("X"))
    }
    @Test fun ctrlPunctuationAndHardwareKeys() {
        val input = TerminalInput()
        assertEquals("\u0003", input.text("c", hardwareCtrl = true))
        assertEquals("\u001b", input.text("[", hardwareCtrl = true))
        assertEquals("\u0000", input.text(" ", hardwareCtrl = true))
        assertEquals("\u007f", input.text("?", hardwareCtrl = true))
        assertEquals("я", input.text("я", hardwareCtrl = true))
    }
    @Test fun cancelledModifierAndEmptyComposition() {
        val input = TerminalInput()
        input.toggleCtrl()
        assertEquals("", input.text(""))
        assertTrue(input.ctrl)
        input.toggleCtrl()
        assertEquals("x", input.text("x"))
    }
}
