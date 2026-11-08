package com.bot4vps.mobile

import com.bot4vps.mobile.data.api.*
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import okhttp3.*
import okhttp3.mockwebserver.*
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import org.junit.Assert.*
import org.junit.Test
import java.security.KeyPairGenerator
import java.security.Signature
import java.security.MessageDigest
import java.security.spec.ECGenParameterSpec
import java.util.Base64
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class MobileAccessClientTest {
    private fun invitation(server: MockWebServer, cert: HeldCertificate, code: String = "i".repeat(43)): String {
        val pin = "sha256/" + Base64.getEncoder().encodeToString(MessageDigest.getInstance("SHA-256").digest(cert.certificate.publicKey.encoded))
        val value = "{\"version\":1,\"url\":\"${server.url("/")}\",\"code\":\"$code\",\"server_pin\":\"$pin\"}"
        return "b4vps:" + Base64.getUrlEncoder().withoutPadding().encodeToString(value.toByteArray())
    }
    private class Keys : MobileDeviceKeys {
        val key = KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec("secp256r1")) }.generateKeyPair()
        val devices = mutableMapOf<String, PairedMobileDevice>()
        override fun device(origin: String) = devices[origin]
        override fun publicKey(origin: String) = "phone-key" to key.public.encoded
        override fun remember(origin: String, device: PairedMobileDevice) { devices[origin] = device }
        override fun sign(alias: String, message: ByteArray): ByteArray = Signature.getInstance("SHA256withECDSA").run {
            initSign(key.private); update(message); sign()
        }
    }
    private class Api(private val keys: Keys) : okhttp3.mockwebserver.Dispatcher() {
        val device = "00000000-0000-0000-0000-000000000001"
        var session: String? = null
        var handshakes = 0
        var writes = 0
        var revoked = false
        override fun dispatch(request: RecordedRequest): MockResponse {
            assertEquals("phone", request.getHeader("X-Bot4VPS-Client"))
            val body = runCatching { Json.parseToJsonElement(request.body.readUtf8()).toString() }.getOrNull().orEmpty()
            when (request.path) {
                "/api/mobile/pair" -> {
                    assertNull(request.getHeader("X-Bot4VPS-Mobile-Session"))
                    assertTrue(body.contains(Base64.getEncoder().encodeToString(keys.key.public.encoded)))
                    return MockResponse().setBody("{\"device_id\":\"$device\"}")
                }
                "/api/mobile/challenge" -> return MockResponse().setBody("{\"challenge_id\":\"challenge\",\"nonce\":\"nonce\"}")
                "/api/mobile/handshake" -> {
                    if (revoked) return MockResponse().setResponseCode(403).setBody("{\"detail\":\"Телефон отозван\"}")
                    val value = Json.parseToJsonElement(body).let { it as kotlinx.serialization.json.JsonObject }
                    val signature = (value["signature"] as kotlinx.serialization.json.JsonPrimitive).content
                    val valid = Signature.getInstance("SHA256withECDSA").run {
                        initVerify(keys.key.public); update(mobileChallengeMessage(device, "challenge", "nonce")); verify(Base64.getDecoder().decode(signature))
                    }
                    assertTrue(valid)
                    handshakes++
                    session = (if (handshakes == 1) "a" else "b").repeat(43)
                    return MockResponse().setBody("{\"session\":\"$session\",\"expires_in\":900}")
                }
                else -> {
                    if (request.getHeader("X-Bot4VPS-Mobile-Session") != session || session == null) return MockResponse()
                        .setResponseCode(401).setHeader("X-Bot4VPS-Mobile-Error", "session")
                    if (request.method == "POST") writes++
                    if (request.path == "/api/shell/ws") return MockResponse().withWebSocketUpgrade(object : WebSocketListener() {
                        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                            webSocket.close(code, reason)
                        }
                    })
                    return MockResponse().setBody("{\"ok\":true}")
                }
            }
        }
    }
    @Test fun localHttpRequestsAreMarkedPhoneWithoutClaimingAPairing(): Unit = runBlocking {
        val server = MockWebServer()
        server.start()
        try {
            server.enqueue(MockResponse().setBody("{}"))
            val mobile = MobileAccessClient(Keys(), Json)
            val client = OkHttpClient.Builder().addInterceptor(MobileAccessInterceptor(mobile)).build()
            client.newCall(Request.Builder().url(server.url("/api/me"))
                .header("X-Bot4VPS-Mobile-Session", "untrusted-session").build()).execute().close()
            val request = server.takeRequest()
            assertEquals("phone", request.getHeader("X-Bot4VPS-Client"))
            assertNull(request.getHeader("X-Bot4VPS-Mobile-Session"))
        } finally { server.shutdown() }
    }
    private fun tls(cert: HeldCertificate = HeldCertificate.Builder().addSubjectAlternativeName("localhost").build()): Pair<MockWebServer, OkHttpClient> {
        val server = MockWebServer()
        val serverTls = HandshakeCertificates.Builder().heldCertificate(cert).build()
        server.useHttps(serverTls.sslSocketFactory(), false)
        server.start()
        val clientTls = HandshakeCertificates.Builder().addTrustedCertificate(cert.certificate).build()
        val client = OkHttpClient.Builder().sslSocketFactory(clientTls.sslSocketFactory(), clientTls.trustManager)
            .followRedirects(false).followSslRedirects(false).build()
        return server to client
    }
    @Test fun pairedDeviceProvesKeyOnceAndUsesTheSessionForApiRequests() = runBlocking {
        val (server, transport) = tls()
        try {
            val keys = Keys(); val api = Api(keys); server.dispatcher = api
            val mobile = MobileAccessClient(keys, Json, transport)
            mobile.pair(server.url("/").toString(), "one-time-invitation")
            val client = transport.newBuilder().addInterceptor(MobileAccessInterceptor(mobile)).build()
            repeat(2) { client.newCall(Request.Builder().url(server.url("/api/servers")).build()).execute().use { assertEquals(200, it.code) } }
            assertEquals(1, api.handshakes)
        } finally { server.shutdown() }
    }
    @Test fun lostSessionAfterServerRestartIsRenewedBeforeOneWrite() = runBlocking {
        val (server, transport) = tls()
        try {
            val keys = Keys(); val api = Api(keys); server.dispatcher = api
            val mobile = MobileAccessClient(keys, Json, transport); mobile.pair(server.url("/").toString(), "invitation")
            val client = transport.newBuilder().addInterceptor(MobileAccessInterceptor(mobile)).build()
            val url = server.url("/api/servers")
            client.newCall(Request.Builder().url(url).build()).execute().close()
            api.session = null
            client.newCall(Request.Builder().url(url).post(RequestBody.create(null, "{}")).build()).execute().use { assertEquals(200, it.code) }
            assertEquals(2, api.handshakes); assertEquals(1, api.writes)
        } finally { server.shutdown() }
    }
    @Test fun deviceHeadersAreNeverSentToAnotherOrigin() = runBlocking {
        val cert = HeldCertificate.Builder().addSubjectAlternativeName("localhost").build()
        val (server, transport) = tls(cert)
        val (other, _) = tls(cert)
        try {
            val keys = Keys(); server.dispatcher = Api(keys)
            val mobile = MobileAccessClient(keys, Json, transport); mobile.pair(server.url("/").toString(), "invitation")
            other.enqueue(MockResponse().setBody("{}"))
            transport.newBuilder().addInterceptor(MobileAccessInterceptor(mobile)).build()
                .newCall(Request.Builder().url(other.url("/api/me")).build()).execute().close()
            assertNull(other.takeRequest().getHeader("X-Bot4VPS-Mobile-Session"))
        } finally { server.shutdown(); other.shutdown() }
    }
    @Test fun revokedKeyRequiresPairingInsteadOfSendingTheOperation() = runBlocking {
        val (server, transport) = tls()
        try {
            val keys = Keys(); val api = Api(keys); server.dispatcher = api
            val mobile = MobileAccessClient(keys, Json, transport); mobile.pair(server.url("/").toString(), "invitation")
            val client = transport.newBuilder().addInterceptor(MobileAccessInterceptor(mobile)).build()
            val url = server.url("/api/servers")
            client.newCall(Request.Builder().url(url).build()).execute().close()
            api.session = null; api.revoked = true
            val error = runCatching { client.newCall(Request.Builder().url(url).post(RequestBody.create(null, "{}")).build()).execute().close() }.exceptionOrNull()
            assertTrue(error is MobilePairingRequired); assertEquals(0, api.writes)
        } finally { server.shutdown() }
    }
    @Test fun terminalGetsAFreshDeviceProofAfterServerRestart(): Unit = runBlocking {
        val (server, transport) = tls()
        try {
            val keys = Keys(); val api = Api(keys); server.dispatcher = api
            val mobile = MobileAccessClient(keys, Json, transport); mobile.pair(server.url("/").toString(), "invitation")
            val client = transport.newBuilder().addInterceptor(MobileAccessInterceptor(mobile)).build()
            client.newCall(Request.Builder().url(server.url("/api/servers")).build()).execute().close()
            api.session = null
            val opened = CountDownLatch(1)
            val closed = CountDownLatch(1)
            val ws = client.newWebSocket(Request.Builder().url(server.url("/api/shell/ws")).build(), object : WebSocketListener() {
                override fun onOpen(webSocket: WebSocket, response: Response) { opened.countDown() }
                override fun onClosed(webSocket: WebSocket, code: Int, reason: String) { closed.countDown() }
            })
            try {
                assertTrue(opened.await(5, TimeUnit.SECONDS))
                assertEquals(2, api.handshakes)
                ws.close(1000, "Готово")
                assertTrue(closed.await(5, TimeUnit.SECONDS))
            } finally { ws.cancel() }
        } finally { server.shutdown() }
    }
    @Test fun pairingRefusesHttpAndNeverFollowsRedirects() = runBlocking {
        val (server, transport) = tls()
        try {
            val mobile = MobileAccessClient(Keys(), Json, transport)
            val insecure = server.url("/").newBuilder().scheme("http").build().toString()
            assertTrue(runCatching { mobile.pair(insecure, "invitation") }.exceptionOrNull() is MobilePairingRequired)
            assertEquals(0, server.requestCount)
            server.enqueue(MockResponse().setResponseCode(302).setHeader("Location", "https://untrusted.example/api/mobile/pair"))
            assertTrue(runCatching { mobile.pair(server.url("/").toString(), "invitation") }.exceptionOrNull() is ApiError)
            assertEquals(1, server.requestCount)
        } finally { server.shutdown() }
    }

    @Test fun selfSignedIdentityIsLearnedFromWebAndSurvivesClientRecreation(): Unit = runBlocking {
        val cert = HeldCertificate.Builder().addSubjectAlternativeName("localhost").build()
        val (server, _) = tls(cert)
        try {
            val keys = Keys(); val api = Api(keys); server.dispatcher = api
            val transport = OkHttpClient.Builder().build()
            val first = MobileAccessClient(keys, Json, transport)
            first.pair("http://unused-private-web", invitation(server, cert))
            assertNotNull(keys.devices.values.single().serverPin)
            val next = MobileAccessClient(keys, Json, transport)
            val base = transport.newBuilder().addInterceptor(MobileAccessInterceptor(next)).build()
            val client = next.clientFor(base, server.url("/api/servers"))
            client.newCall(Request.Builder().url(server.url("/api/servers")).build()).execute().use { assertEquals(200, it.code) }
            assertEquals(1, api.handshakes)
            // A raw retry must retain the learned server key as well.
            next.pair(server.url("/").toString(), "i".repeat(43))
            assertNotNull(keys.devices.values.single().serverPin)
        } finally { server.shutdown() }
    }

    @Test fun wrongServerKeyIsRejectedBeforeInvitationOrDeviceKeyIsSent(): Unit = runBlocking {
        val cert = HeldCertificate.Builder().addSubjectAlternativeName("localhost").build()
        val other = HeldCertificate.Builder().addSubjectAlternativeName("localhost").build()
        val (server, _) = tls(cert)
        try {
            val keys = Keys(); server.dispatcher = Api(keys)
            val mobile = MobileAccessClient(keys, Json)
            val error = runCatching { mobile.pair(server.url("/").toString(), invitation(server, other)) }.exceptionOrNull()
            assertTrue(error is javax.net.ssl.SSLHandshakeException)
            assertEquals(0, server.requestCount); assertTrue(keys.devices.isEmpty())
        } finally { server.shutdown() }
    }

    @Test fun renewedCertificateWithSameKeyWorksButChangedKeyDoesNot(): Unit = runBlocking {
        val cert = HeldCertificate.Builder().addSubjectAlternativeName("localhost").build()
        val renewed = HeldCertificate.Builder().keyPair(cert.keyPair).addSubjectAlternativeName("localhost").build()
        val changed = HeldCertificate.Builder().addSubjectAlternativeName("localhost").build()
        val (server, _) = tls(cert)
        try {
            val keys = Keys(); server.dispatcher = Api(keys)
            val mobile = MobileAccessClient(keys, Json)
            mobile.pair(server.url("/").toString(), invitation(server, cert))
            val base = OkHttpClient.Builder().addInterceptor(MobileAccessInterceptor(mobile)).build()
            val client = mobile.clientFor(base, server.url("/api/servers"))
            val request = Request.Builder().url(server.url("/api/servers")).build()
            server.useHttps(HandshakeCertificates.Builder().heldCertificate(renewed).build().sslSocketFactory(), false)
            client.newCall(request).execute().use { assertEquals(200, it.code) }
            client.connectionPool.evictAll()
            server.useHttps(HandshakeCertificates.Builder().heldCertificate(changed).build().sslSocketFactory(), false)
            val before = server.requestCount
            assertTrue(runCatching { client.newCall(request).execute().close() }.exceptionOrNull() is javax.net.ssl.SSLHandshakeException)
            assertEquals(before, server.requestCount)
        } finally { server.shutdown() }
    }

    @Test fun pinnedClientCannotBeReusedForAnotherPort(): Unit = runBlocking {
        val cert = HeldCertificate.Builder().addSubjectAlternativeName("localhost").build()
        val (server, _) = tls(cert); val (other, _) = tls(cert)
        try {
            val keys = Keys(); server.dispatcher = Api(keys)
            val mobile = MobileAccessClient(keys, Json); mobile.pair(server.url("/").toString(), invitation(server, cert))
            val client = mobile.clientFor(OkHttpClient(), server.url("/api/me"))
            assertTrue(runCatching { client.newCall(Request.Builder().url(other.url("/api/me")).build()).execute().close() }.exceptionOrNull() is MobilePairingRequired)
            assertEquals(0, other.requestCount)
        } finally { server.shutdown(); other.shutdown() }
    }

    @Test fun malformedWebInvitationsDoNotEnableTrust(): Unit = runBlocking {
        assertNull(readMobileInvitation("ordinary-cli-code"))
        for (value in listOf("b4vps:!", "b4vps:" + "x".repeat(4097), "b4vps:" + Base64.getUrlEncoder().encodeToString("{}".toByteArray()))) {
            assertTrue(runCatching { readMobileInvitation(value) }.exceptionOrNull() is MobilePairingRequired)
        }
        val insecure = "{\"version\":1,\"url\":\"http://home:8444\",\"code\":\"${"i".repeat(43)}\",\"server_pin\":\"sha256/${Base64.getEncoder().encodeToString(ByteArray(32))}\"}"
        assertTrue(runCatching { readMobileInvitation("b4vps:" + Base64.getUrlEncoder().encodeToString(insecure.toByteArray())) }.exceptionOrNull() is MobilePairingRequired)
    }
}
