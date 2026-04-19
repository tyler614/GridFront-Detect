package io.gridfront.detect

import android.content.Context
import android.util.Log
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStream
import java.net.ServerSocket
import java.net.Socket

/**
 * Lightweight HTTP server that serves static files from assets/www/ and
 * exposes a thin /api/ surface sourced from the on-device UdpListener.
 *
 * Single origin (http://127.0.0.1:8080) keeps the WebView away from CORS
 * and avoids any cleartext-to-LAN traffic. When a Flask backend is
 * reachable on 127.0.0.1:5555 (developer laptop running the full pipeline
 * locally), unknown /api/ paths fall through to a proxy so the rest of
 * the settings UI still works.
 */
class LocalAssetServer(
    private val context: Context,
    private val udp: UdpListener,
    private val port: Int = 8080,
) {
    companion object {
        private const val TAG = "GF_Server"
        private const val FLASK_HOST = "127.0.0.1"
        private const val FLASK_PORT = 5555

        // Zone defaults mirror build_standalone.py defaults. The WebView
        // uses these for the DANGER/WARNING ring radii; the OAK standalone
        // bakes its own copy at flash time, so keep them in sync here.
        private const val DEFAULT_DANGER_M = 3.0
        private const val DEFAULT_WARNING_M = 6.0

        private const val STALE_AFTER_MS = 3_000L
    }

    @Volatile
    private var running = false
    private var serverSocket: ServerSocket? = null

    fun start() {
        if (running) return
        running = true
        Thread({
            try {
                serverSocket = ServerSocket(port)
                Log.i(TAG, "LocalAssetServer listening on port $port")
                while (running) {
                    try {
                        val client = serverSocket!!.accept()
                        Thread({ handleClient(client) }, "http-client").start()
                    } catch (e: Exception) {
                        if (running) Log.w(TAG, "Accept error: ${e.message}")
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "Server failed to start: ${e.message}")
            }
        }, "http-server").start()
    }

    fun stop() {
        running = false
        try { serverSocket?.close() } catch (_: Exception) {}
        serverSocket = null
        Log.i(TAG, "LocalAssetServer stopped")
    }

    private fun handleClient(socket: Socket) {
        try {
            socket.soTimeout = 15000
            val reader = BufferedReader(InputStreamReader(socket.getInputStream()))
            val requestLine = reader.readLine() ?: return

            val parts = requestLine.split(" ")
            if (parts.size < 2) return
            val path = parts[1].split("?")[0]

            // Drain remaining headers for non-proxy paths.
            if (path.startsWith("/api/")) {
                if (handleLocalApi(path, socket, reader)) return
                proxyToFlask(socket, requestLine, reader)
                return
            }

            var line = reader.readLine()
            while (line != null && line.isNotEmpty()) {
                line = reader.readLine()
            }

            val assetPath = if (path == "/") "www/index.html" else "www${path}"
            val mimeType = getMimeType(assetPath)

            // Live-reload override: check /data/local/tmp/gridfront_web/<rest>
            // first, and only fall back to bundled assets if the override is
            // missing. Lets us `adb push` HTML/JS changes and `webView.reload()`
            // without rebuilding or restarting the APK.
            val overridePath = "/data/local/tmp/gridfront_web/" +
                (if (path == "/") "index.html" else path.removePrefix("/"))
            val overrideFile = java.io.File(overridePath)

            try {
                val bytes = if (overrideFile.isFile && overrideFile.canRead())
                    overrideFile.readBytes()
                else
                    context.assets.open(assetPath).use { it.readBytes() }
                writeResponse(socket.getOutputStream(), 200, "OK", mimeType, bytes)
            } catch (e: java.io.FileNotFoundException) {
                val body = "404 Not Found: $path".toByteArray()
                writeResponse(socket.getOutputStream(), 404, "Not Found", "text/plain", body)
            }
        } catch (e: Exception) {
            Log.w(TAG, "Client handler error: ${e.message}")
        } finally {
            try { socket.close() } catch (_: Exception) {}
        }
    }

    /**
     * Handles endpoints we can satisfy from on-device state (UDP listener +
     * static config). Returns true if we owned the request.
     */
    private fun handleLocalApi(path: String, socket: Socket, reader: BufferedReader): Boolean {
        return when (path) {
            "/api/spatial"        -> { drainHeaders(reader); writeSpatial(socket); true }
            "/api/spatial/stream" -> { drainHeaders(reader); streamSpatial(socket); true }
            "/api/config"         -> { drainHeaders(reader); writeConfig(socket); true }
            "/api/system/health"  -> { drainHeaders(reader); writeHealth(socket); true }
            else -> false
        }
    }

    private fun writeSpatial(socket: Socket) {
        val payload = udp.latestPayload() ?: emptySpatialPayload()
        writeResponse(
            socket.getOutputStream(), 200, "OK",
            "application/json; charset=utf-8",
            payload.toByteArray(Charsets.UTF_8),
        )
    }

    private fun writeConfig(socket: Socket) {
        val body = """{"zones":{"danger_m":$DEFAULT_DANGER_M,"warning_m":$DEFAULT_WARNING_M}}"""
        writeResponse(
            socket.getOutputStream(), 200, "OK",
            "application/json; charset=utf-8",
            body.toByteArray(Charsets.UTF_8),
        )
    }

    private fun writeHealth(socket: Socket) {
        val age = System.currentTimeMillis() - udp.lastRxEpochMs()
        val status = if (udp.lastRxEpochMs() > 0 && age < STALE_AFTER_MS) "ok" else "stale"
        val body = """{"status":"$status","udp_age_ms":$age}"""
        writeResponse(
            socket.getOutputStream(), 200, "OK",
            "application/json; charset=utf-8",
            body.toByteArray(Charsets.UTF_8),
        )
    }

    /**
     * Long-lived SSE response. Writes an initial snapshot immediately, then
     * forwards every UDP packet as an event. Keep-alive comment every 15s
     * so intermediaries / the WebView don't close the socket during a
     * traffic lull.
     */
    private fun streamSpatial(socket: Socket) {
        val out = socket.getOutputStream()
        val header = ("HTTP/1.1 200 OK\r\n" +
            "Content-Type: text/event-stream; charset=utf-8\r\n" +
            "Cache-Control: no-cache\r\n" +
            "Connection: keep-alive\r\n" +
            "X-Accel-Buffering: no\r\n\r\n").toByteArray()
        out.write(header); out.flush()

        // Snapshot so the first frame arrives instantly even during a lull.
        val first = udp.latestPayload() ?: emptySpatialPayload()
        writeSseData(out, first)

        val sub = UdpListener.Subscriber { payload ->
            try { writeSseData(out, payload) } catch (e: Exception) {
                // Let the main loop below notice the closed socket.
            }
        }
        udp.subscribe(sub)

        try {
            // SSE needs the socket kept open; DatagramSocket -> Subscriber
            // writes happen from the UDP thread. This thread parks and
            // emits keep-alives until the WebView drops the connection.
            var lastKeepalive = System.currentTimeMillis()
            socket.soTimeout = 0
            while (!socket.isClosed) {
                Thread.sleep(1_000)
                val now = System.currentTimeMillis()
                if (now - lastKeepalive >= 15_000) {
                    try { out.write(": keepalive\n\n".toByteArray()); out.flush() }
                    catch (e: Exception) { break }
                    lastKeepalive = now
                }
            }
        } catch (_: InterruptedException) {
            // fallthrough to unsubscribe
        } finally {
            udp.unsubscribe(sub)
        }
    }

    private fun writeSseData(out: OutputStream, payload: String) {
        // Strip newlines from payload — SSE treats \n as record separator.
        val flat = payload.replace("\n", " ").replace("\r", " ")
        val frame = "data: $flat\n\n"
        synchronized(out) {
            out.write(frame.toByteArray(Charsets.UTF_8))
            out.flush()
        }
    }

    private fun emptySpatialPayload(): String =
        """{"detections":[],"summary":{"danger_count":0,"warning_count":0,"clear_count":0,"closest_m":null},"units":"m","link":"stale","ts":null}"""

    private fun drainHeaders(reader: BufferedReader) {
        var line = reader.readLine()
        while (line != null && line.isNotEmpty()) {
            line = reader.readLine()
        }
    }

    private fun writeResponse(
        out: OutputStream, code: Int, reason: String,
        contentType: String, body: ByteArray,
    ) {
        val header = "HTTP/1.1 $code $reason\r\n" +
            "Content-Type: $contentType\r\n" +
            "Content-Length: ${body.size}\r\n" +
            "Cache-Control: no-cache\r\n" +
            "Connection: close\r\n\r\n"
        out.write(header.toByteArray())
        out.write(body)
        out.flush()
    }

    /**
     * Proxies an HTTP request to the Flask backend. Only used for /api/
     * paths we didn't satisfy locally — lets a developer run the full
     * Flask stack on 127.0.0.1:5555 and exercise the settings UI.
     */
    private fun proxyToFlask(clientSocket: Socket, requestLine: String, clientReader: BufferedReader) {
        try {
            val headers = mutableListOf<String>()
            var contentLength = 0
            var line = clientReader.readLine()
            while (line != null && line.isNotEmpty()) {
                headers.add(line)
                if (line.lowercase().startsWith("content-length:")) {
                    contentLength = line.substringAfter(":").trim().toIntOrNull() ?: 0
                }
                line = clientReader.readLine()
            }

            val body = if (contentLength > 0) {
                val buf = CharArray(contentLength)
                var totalRead = 0
                while (totalRead < contentLength) {
                    val n = clientReader.read(buf, totalRead, contentLength - totalRead)
                    if (n == -1) break
                    totalRead += n
                }
                String(buf, 0, totalRead)
            } else null

            val flask = Socket(FLASK_HOST, FLASK_PORT)
            val flaskOut = flask.getOutputStream()
            val flaskIn = flask.getInputStream()

            flaskOut.write("$requestLine\r\n".toByteArray())
            for (h in headers) flaskOut.write("$h\r\n".toByteArray())
            flaskOut.write("\r\n".toByteArray())
            if (body != null) flaskOut.write(body.toByteArray())
            flaskOut.flush()

            val clientOut = clientSocket.getOutputStream()
            val buffer = ByteArray(8192)
            var bytesRead: Int
            while (flaskIn.read(buffer).also { bytesRead = it } != -1) {
                clientOut.write(buffer, 0, bytesRead)
                clientOut.flush()
            }
            flask.close()
        } catch (e: Exception) {
            Log.d(TAG, "Proxy fallthrough failed (expected when no Flask): ${e.message}")
            try {
                val errBody = """{"error":"not_available","detail":"no backend"}"""
                writeResponse(
                    clientSocket.getOutputStream(), 503, "Service Unavailable",
                    "application/json", errBody.toByteArray(),
                )
            } catch (_: Exception) {}
        }
    }

    private fun getMimeType(path: String): String = when {
        path.endsWith(".html") -> "text/html; charset=utf-8"
        path.endsWith(".js") -> "application/javascript; charset=utf-8"
        path.endsWith(".css") -> "text/css; charset=utf-8"
        path.endsWith(".json") -> "application/json; charset=utf-8"
        path.endsWith(".png") -> "image/png"
        path.endsWith(".jpg") || path.endsWith(".jpeg") -> "image/jpeg"
        path.endsWith(".svg") -> "image/svg+xml"
        path.endsWith(".gif") -> "image/gif"
        path.endsWith(".ico") -> "image/x-icon"
        path.endsWith(".woff2") -> "font/woff2"
        path.endsWith(".woff") -> "font/woff"
        path.endsWith(".ttf") -> "font/ttf"
        path.endsWith(".otf") -> "font/otf"
        path.endsWith(".mp3") -> "audio/mpeg"
        path.endsWith(".wav") -> "audio/wav"
        path.endsWith(".mp4") -> "video/mp4"
        path.endsWith(".webm") -> "video/webm"
        path.endsWith(".webp") -> "image/webp"
        path.endsWith(".glb") -> "model/gltf-binary"
        path.endsWith(".gltf") -> "model/gltf+json"
        else -> "application/octet-stream"
    }
}
