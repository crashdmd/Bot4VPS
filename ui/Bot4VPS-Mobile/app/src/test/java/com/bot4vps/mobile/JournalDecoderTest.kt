package com.bot4vps.mobile

import com.bot4vps.mobile.data.model.*
import org.junit.Assert.*
import org.junit.Test

class JournalDecoderTest {
    @Test fun journalLinesAreTextAndKeepMultilineData() {
        val decoder=JournalDecoder()
        decoder.line("event: line"); decoder.line("data: ERROR первая строка"); decoder.line("data:   отступ")
        assertEquals(JournalFrame("line","ERROR первая строка\n  отступ"),decoder.line(""))
    }
    @Test fun pingsNeverBecomeJournalEntries() {
        val decoder=JournalDecoder()
        assertNull(decoder.line(": ping")); assertNull(decoder.line(""))
        decoder.line("event: hello"); decoder.line("data: ok")
        assertEquals(JournalFrame("hello","ok"),decoder.line(""))
    }
    @Test fun endAndFailureAreDistinctFromJournalLines() {
        val decoder=JournalDecoder()
        decoder.line("event: end"); decoder.line("data: 0")
        assertEquals(JournalFrame("end","0"),decoder.line(""))
        decoder.line("event: fail"); decoder.line("data: journalctl не найден")
        assertEquals(JournalFrame("fail","journalctl не найден"),decoder.line(""))
    }
}
