package com.bot4vps.mobile

import com.bot4vps.mobile.data.model.JournalFrame
import com.bot4vps.mobile.data.repository.JournalRepository
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.launch
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.delay
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.take
import kotlinx.coroutines.flow.toList
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.TimeUnit
import com.bot4vps.mobile.ui.dashboard.ServiceJournalViewModel

class JournalStreamTest {
    @Test fun pauseStopsTheConnectionAndResumeOpensANewStream() = runBlocking {
        val server = MockWebServer()
        server.start()
        val response = "event: hello\ndata: ok\n\n" + (1..500).joinToString("") { "event: line\ndata: line$it\n\n" }
        server.enqueue(MockResponse().setBody(response).throttleBody(64, 50, TimeUnit.MILLISECONDS))
        val vm = ServiceJournalViewModel(JournalRepository(OkHttpClient(), server.url("/api/system/journal")))
        val observer = launch { vm.observe() }
        try {
            withTimeout(5000) { vm.state.first { it.lines.isNotEmpty() } }
            vm.toggle()
            val retained = vm.state.value.lines
            delay(200)
            assertTrue(vm.state.value.paused)
            assertFalse(vm.state.value.live)
            assertEquals(retained, vm.state.value.lines)
            assertEquals(1, server.requestCount)
            server.enqueue(MockResponse().setBody("event: hello\ndata: ok\n\nevent: line\ndata: resumed\n\n" + response).throttleBody(64, 50, TimeUnit.MILLISECONDS))
            vm.toggle()
            withTimeout(5000) { vm.state.first { "resumed" in it.lines } }
            assertFalse(vm.state.value.paused)
            assertEquals(2, server.requestCount)
        } finally { observer.cancelAndJoin(); server.shutdown() }
    }

    @Test fun delayedJournalLinesArriveWithoutARefreshRequest() = runBlocking {
        val server = MockWebServer()
        server.start()
        try {
            server.enqueue(MockResponse().setHeader("Content-Type", "text/event-stream")
                .setBody("event: hello\ndata: ok\n\nevent: line\ndata: first\n\n: ping\n\nevent: line\ndata: second\n\n")
                .throttleBody(16, 30, TimeUnit.MILLISECONDS))
            val frames = withTimeout(5000) { JournalRepository(OkHttpClient(), server.url("/api/system/journal")).frames().take(3).toList() }
            assertEquals(listOf(JournalFrame("hello", "ok"), JournalFrame("line", "first"), JournalFrame("line", "second")), frames)
            assertEquals(1, server.requestCount)
            assertEquals("text/event-stream", server.takeRequest().getHeader("Accept"))
        } finally { server.shutdown() }
    }
}
