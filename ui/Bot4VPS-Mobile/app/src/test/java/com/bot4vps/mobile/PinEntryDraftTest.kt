package com.bot4vps.mobile

import com.bot4vps.mobile.data.model.*
import org.junit.Assert.*
import org.junit.Test

class PinEntryDraftTest {
    @Test fun keypadPreservesZeroAndStopsAtFourDigits() {
        val draft = listOf(0, 1, 2, 3, 4).fold(PinEntryDraft(PinEntryStage.NEW)) { state, digit -> state.digit(digit) }
        assertEquals("0123", draft.digits)
        assertTrue(draft.complete)
        assertEquals("012", draft.delete().digits)
        assertEquals("0129", draft.delete().digit(9).digits)
    }
    @Test fun repeatUsesSecondEmptyRowAndComparesExactly() {
        val first = listOf(0, 1, 2, 3).fold(PinEntryDraft(PinEntryStage.NEW)) { state, digit -> state.digit(digit) }
        val repeat = first.repeat()
        assertEquals(PinEntryStage.REPEAT, repeat.stage)
        assertEquals("", repeat.digits)
        assertEquals("0123", repeat.firstPin)
        assertTrue(listOf(0, 1, 2, 3).fold(repeat) { state, digit -> state.digit(digit) }.matches)
        assertFalse(listOf(0, 1, 2, 4).fold(repeat) { state, digit -> state.digit(digit) }.matches)
    }
    @Test fun incompleteEntryCannotAdvanceAndEmptyDeleteIsSafe() {
        val draft = PinEntryDraft(PinEntryStage.NEW).digit(1).digit(2)
        assertThrows(IllegalStateException::class.java) { draft.repeat() }
        assertEquals("", PinEntryDraft(PinEntryStage.CURRENT).delete().digits)
        assertEquals(draft, draft.digit(12))
    }
}
