package io.gridfront.scout

import android.content.Context
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStream
import java.net.NetworkInterface
import java.net.ServerSocket
import java.net.Socket

/**
 * Lightweight HTTP server that serves static files from assets/www/ and
 * exposes a thin /api/ surface. All endpoints are satisfied on-device —
 * detections come from UdpListener (port 5556), config state lives in
 * ConfigStore, and edits are pushed to cameras by ConfigSync (port 5557).
 *
 * Single origin (http://127.0.0.1:8080) keeps the WebView away from CORS
 * and avoids any cleartext-to-LAN traffic. Unknown /api/ paths proxy to
 * 127.0.0.1:5555 only in the rare case a developer runs a Flask stack
 * locally for debugging.
 */
class LocalAssetServer(
    private val context: Context,
    private val udp: UdpListener,
    private val configStore: ConfigStore,
    private val configSync: ConfigSync,
    private val port: Int = 8080,
) {
    companion object {
        private const val TAG = "GF_Server"
        private const val FLASK_HOST = "127.0.0.1"
        private const val FLASK_PORT = 5555
        // Drop from 3s to 1s — 1s is still 10x the OAK's normal 100ms inter-
        // packet gap (10 fps target), so we won't false-positive on a slow
        // frame, but disconnect feels nearly instant to the operator.
        private const val STALE_AFTER_MS = 1_000L
        private const val ETH_IFACE = "eth0"
    }

    @Volatile
    private var running = false
    @Volatile
    private var adbKeyInstallUsed = false
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
            if (parts.size < 3) return
            val method = parts[0]
            val path = parts[1].split("?")[0]

            if (path.startsWith("/api/")) {
                if (handleLocalApi(method, path, socket, reader)) return
                proxyToFlask(socket, requestLine, reader)
                return
            }

            drainHeaders(reader)

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
     * Handles endpoints we can satisfy from on-device state. Returns true
     * if we owned the request.
     */
    private fun handleLocalApi(
        method: String, path: String, socket: Socket, reader: BufferedReader,
    ): Boolean {
        // Per-camera pose: /api/cameras/{id}/pose
        val poseMatch = Regex("^/api/cameras/([^/]+)/pose$").matchEntire(path)
        if (poseMatch != null && method == "POST") {
            val body = readBody(reader) ?: ""
            writePoseUpdate(socket, poseMatch.groupValues[1], body); return true
        }

        return when (path) {
            "/api/spatial" -> {
                drainHeaders(reader); writeSpatial(socket); true
            }
            "/api/spatial/stream" -> {
                drainHeaders(reader); streamSpatial(socket); true
            }
            "/api/config" -> when (method) {
                "GET"  -> { drainHeaders(reader); writeConfig(socket); true }
                "POST" -> { writeConfigReplace(socket, readBody(reader) ?: ""); true }
                else   -> false
            }
            "/api/config/push" -> {
                drainHeaders(reader); writePushAll(socket); true
            }
            "/api/zones" -> when (method) {
                "POST" -> { writeZonesUpdate(socket, readBody(reader) ?: ""); true }
                else   -> false
            }
            "/api/machine" -> when (method) {
                "POST" -> { writeMachineUpdate(socket, readBody(reader) ?: ""); true }
                else   -> false
            }
            "/api/runtime" -> when (method) {
                "POST" -> { writeRuntimeUpdate(socket, readBody(reader) ?: ""); true }
                else   -> false
            }
            "/api/models" -> when (method) {
                "GET"  -> { drainHeaders(reader); writeModels(socket); true }
                else   -> false
            }
            "/api/models/active" -> when (method) {
                "POST" -> { writeModelActive(socket, readBody(reader) ?: ""); true }
                else   -> false
            }
            "/api/cameras" -> when (method) {
                "POST" -> { writeCamerasReplace(socket, readBody(reader) ?: ""); true }
                else   -> false
            }
            "/api/camera/status" -> {
                // Stub so the tablet UI stops spinning on "connecting" when
                // no camera is configured yet. Real liveness comes from the
                // UDP detection stream age.
                drainHeaders(reader); writeCameraStatus(socket); true
            }
            "/api/system/health" -> {
                drainHeaders(reader); writeHealth(socket); true
            }
            "/api/debug/adb-key",
            "/api/debug/adb_key" -> when (method) {
                "POST" -> { writeAdbKeyInstall(socket, readBody(reader) ?: ""); true }
                else   -> false
            }
            else -> false
        }
    }

    private fun writeSpatial(socket: Socket) {
        val payload = udp.latestPayload() ?: emptySpatialPayload()
        writeJson(socket, 200, "OK", payload)
    }

    private fun writeConfig(socket: Socket) {
        writeJson(socket, 200, "OK", configStore.read().toString())
    }

    private fun writeConfigReplace(socket: Socket, body: String) {
        val doc = parseJsonObject(body) ?: return writeJson(
            socket, 400, "Bad Request",
            """{"error":"invalid_json"}""",
        )
        configStore.write(doc)
        configSync.pushAll()
        writeJson(socket, 200, "OK", """{"ok":true}""")
    }

    private fun writePushAll(socket: Socket) {
        configSync.pushAll()
        writeJson(socket, 200, "OK", """{"ok":true,"cameras":${configStore.installedCameras().size}}""")
    }

    private fun writeZonesUpdate(socket: Socket, body: String) {
        val doc = parseJsonObject(body) ?: return writeJson(
            socket, 400, "Bad Request",
            """{"error":"invalid_json"}""",
        )
        val zones = doc.optJSONArray("zones") ?: return writeJson(
            socket, 400, "Bad Request",
            """{"error":"missing_zones_array"}""",
        )
        configStore.mutate { it.put("zones", zones) }
        configSync.pushAll()
        writeJson(socket, 200, "OK", """{"ok":true,"zones":${zones.length()}}""")
    }

    private fun writeModels(socket: Socket) {
        val cfg = configStore.read()
        val active = cfg.optString("active_model", ModelRegistry.DEFAULT_MODEL_ID)
        val pending = cfg.optString("pending_model", "")
        val models = JSONArray()
        ModelRegistry.MODELS.forEach { models.put(it.toJson()) }
        val out = JSONObject().apply {
            put("models", models)
            put("active_model", active)
            put("pending_model", pending)
        }
        writeJson(socket, 200, "OK", out.toString())
    }

    private fun writeModelActive(socket: Socket, body: String) {
        val doc = parseJsonObject(body) ?: return writeJson(
            socket, 400, "Bad Request",
            """{"error":"invalid_json"}""",
        )
        val modelId = doc.optString("model_id", "")
        val model = ModelRegistry.byId(modelId) ?: return writeJson(
            socket, 400, "Bad Request",
            """{"error":"unknown_model","model_id":"$modelId"}""",
        )
        // The OAK firmware has the model BAKED IN at flash time, so picking
        // a new one here doesn't change what the camera runs. We persist
        // the choice as `pending_model` and let the build host pick it up
        // when the operator (or a watcher daemon) reflashes. The tablet UI
        // surfaces the pending state until reflash completes.
        configStore.mutate {
            it.put("pending_model", model.id)
            // active_model isn't updated until the camera comes back online
            // running the new firmware. For now we leave it as-is so the
            // detection-class panel keeps showing the running vocabulary.
        }
        writeJson(socket, 200, "OK", """{"status":"pending","model_id":"${model.id}"}""")
    }

    private fun writeRuntimeUpdate(socket: Socket, body: String) {
        val doc = parseJsonObject(body) ?: return writeJson(
            socket, 400, "Bad Request",
            """{"error":"invalid_json"}""",
        )
        var fps: Double? = null
        if (doc.has("target_fps")) {
            val raw = doc.optDouble("target_fps", Double.NaN)
            if (raw.isNaN() || raw < 0 || raw > 60) {
                return writeJson(socket, 400, "Bad Request",
                    """{"error":"target_fps_out_of_range"}""")
            }
            fps = raw
        }
        configStore.mutate {
            if (fps != null) it.put("target_fps", fps)
        }
        // Send the new rate to every registered camera so it takes effect
        // without waiting for the next 30s config_request.
        if (fps != null) configSync.pushAll()
        writeJson(socket, 200, "OK", """{"ok":true}""")
    }

    private fun writeMachineUpdate(socket: Socket, body: String) {
        val doc = parseJsonObject(body) ?: return writeJson(
            socket, 400, "Bad Request",
            """{"error":"invalid_json"}""",
        )
        configStore.mutate {
            if (doc.has("machine_name")) it.put("machine_name", doc.optString("machine_name"))
            if (doc.has("machine_type")) it.put("machine_type", doc.optString("machine_type"))
            if (doc.has("machine_footprint_m"))
                it.put("machine_footprint_m", doc.optJSONObject("machine_footprint_m") ?: JSONObject())
        }
        // Machine footprint doesn't change what the camera sees, so no push.
        writeJson(socket, 200, "OK", """{"ok":true}""")
    }

    private fun writeCamerasReplace(socket: Socket, body: String) {
        val doc = parseJsonObject(body) ?: return writeJson(
            socket, 400, "Bad Request",
            """{"error":"invalid_json"}""",
        )
        val cams = doc.optJSONArray("installed_cameras") ?: return writeJson(
            socket, 400, "Bad Request",
            """{"error":"missing_installed_cameras"}""",
        )
        configStore.mutate { it.put("installed_cameras", cams) }
        configSync.pushAll()
        writeJson(socket, 200, "OK", """{"ok":true,"cameras":${cams.length()}}""")
    }

    private fun writePoseUpdate(socket: Socket, cameraId: String, body: String) {
        val doc = parseJsonObject(body) ?: return writeJson(
            socket, 400, "Bad Request",
            """{"error":"invalid_json"}""",
        )
        var matched = false
        configStore.mutate {
            val arr = it.optJSONArray("installed_cameras") ?: JSONArray().also { a ->
                it.put("installed_cameras", a)
            }
            for (i in 0 until arr.length()) {
                val c = arr.optJSONObject(i) ?: continue
                if (c.optString("id") != cameraId) continue
                matched = true
                if (doc.has("position_m")) c.put("position_m", doc.optJSONArray("position_m"))
                if (doc.has("yaw_deg"))    c.put("yaw_deg",    doc.optDouble("yaw_deg"))
                if (doc.has("pitch_deg"))  c.put("pitch_deg",  doc.optDouble("pitch_deg"))
                if (doc.has("roll_deg"))   c.put("roll_deg",   doc.optDouble("roll_deg"))
                if (doc.has("hfov_deg"))   c.put("hfov_deg",   doc.optDouble("hfov_deg"))
                if (doc.has("max_range_m")) c.put("max_range_m", doc.optDouble("max_range_m"))
                if (doc.has("label"))      c.put("label",      doc.optString("label"))
                if (doc.has("device_id"))  c.put("device_id",  doc.optString("device_id"))
            }
        }
        if (!matched) return writeJson(
            socket, 404, "Not Found",
            """{"error":"unknown_camera","camera_id":"$cameraId"}""",
        )
        val cam = configStore.installedCameras().firstOrNull { it.id == cameraId }
        if (cam != null) configSync.pushTo(cam.id, cam.ip)
        writeJson(socket, 200, "OK", """{"ok":true,"camera_id":"$cameraId"}""")
    }

    private fun writeCameraStatus(socket: Socket) {
        val cams = configStore.installedCameras()
        val lastRx = udp.lastRxEpochMs()
        val age = if (lastRx > 0) System.currentTimeMillis() - lastRx else Long.MAX_VALUE
        // Fast-path disconnect: when the USB-C ethernet drops, the kernel
        // knows within ~100ms. Skip the UDP staleness wait — if eth0 isn't
        // up, the OAK can't be reaching us regardless of cached payloads.
        // Fail open if the NetworkInterface query throws (don't break the
        // status endpoint just because we couldn't read interface state).
        val ethUp = try {
            NetworkInterface.getByName(ETH_IFACE)?.isUp ?: false
        } catch (_: Exception) { true }
        val state = when {
            cams.isEmpty()            -> "no_camera"
            !ethUp && lastRx > 0      -> "error"
            age < STALE_AFTER_MS      -> "connected"
            lastRx == 0L              -> "connecting"
            else                      -> "error"
        }
        writeJson(socket, 200, "OK",
            """{"state":"$state","cameras":${cams.size},"udp_age_ms":${if (age == Long.MAX_VALUE) -1 else age},"eth_up":$ethUp}""")
    }

    private fun writeHealth(socket: Socket) {
        val age = System.currentTimeMillis() - udp.lastRxEpochMs()
        val status = if (udp.lastRxEpochMs() > 0 && age < STALE_AFTER_MS) "ok" else "stale"
        writeJson(socket, 200, "OK", """{"status":"$status","udp_age_ms":$age}""")
    }

    private fun writeAdbKeyInstall(socket: Socket, body: String) {
        if (adbKeyInstallUsed) {
            return writeJson(socket, 409, "Conflict", """{"error":"already_used"}""")
        }

        val pubkey = extractAdbPubkey(body)
        if (pubkey == null) {
            return writeJson(socket, 400, "Bad Request", """{"error":"invalid_pubkey"}""")
        }

        val tmp = java.io.File(context.cacheDir, "adbkey-${System.currentTimeMillis()}.pub")
        try {
            tmp.writeText("$pubkey\n", Charsets.UTF_8)
            val tmpPath = shellQuote(tmp.absolutePath)
            val cmd = """
                set -e
                mkdir -p /data/misc/adb
                touch /data/misc/adb/adb_keys
                key="${'$'}(cat $tmpPath)"
                grep -Fqx "${'$'}key" /data/misc/adb/adb_keys || printf '%s\n' "${'$'}key" >> /data/misc/adb/adb_keys
                chown system:shell /data/misc/adb/adb_keys
                chmod 640 /data/misc/adb/adb_keys
                restorecon /data/misc/adb /data/misc/adb/adb_keys 2>/dev/null || true
                settings put global development_settings_enabled 1
                settings put global adb_enabled 1
                setprop service.adb.tcp.port 5555
                stop adbd 2>/dev/null || true
                start adbd
                echo GF_ADB_KEY_OK
            """.trimIndent()

            val out = RootShell.run(cmd) ?: ""
            if (!out.contains("GF_ADB_KEY_OK")) {
                return writeJson(socket, 500, "Internal Server Error",
                    JSONObject().put("error", "root_install_failed").put("out", out.take(500)).toString())
            }
            adbKeyInstallUsed = true
            writeJson(socket, 200, "OK", """{"ok":true,"port":5555}""")
        } finally {
            try { tmp.delete() } catch (_: Exception) {}
        }
    }

    private fun extractAdbPubkey(body: String): String? {
        val raw = body.trim()
        if (raw.isBlank()) return null
        val candidate = try {
            JSONObject(raw).optString("pubkey", raw)
        } catch (_: Exception) {
            raw
        }.trim().replace("\r", "").replace("\n", "")

        if (candidate.length !in 120..4096) return null
        val parts = candidate.split(Regex("\\s+"), limit = 2)
        val keyBlob = parts.firstOrNull() ?: return null
        if (!Regex("^[A-Za-z0-9+/=]+$").matches(keyBlob)) return null
        if (parts.size > 1 && !Regex("^[A-Za-z0-9_.@+=:-]+$").matches(parts[1])) return null
        return candidate
    }

    private fun shellQuote(s: String): String =
        "'" + s.replace("'", "'\\''") + "'"

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

        val first = udp.latestPayload() ?: emptySpatialPayload()
        writeSseData(out, first)

        val sub = UdpListener.Subscriber { payload ->
            try { writeSseData(out, payload) } catch (_: Exception) { /* main loop notices */ }
        }
        udp.subscribe(sub)

        try {
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
        } finally {
            udp.unsubscribe(sub)
        }
    }

    private fun writeSseData(out: OutputStream, payload: String) {
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

    /** Reads headers + body. Returns body string, or null if no Content-Length. */
    private fun readBody(reader: BufferedReader): String? {
        var contentLength = 0
        var line = reader.readLine()
        while (line != null && line.isNotEmpty()) {
            if (line.lowercase().startsWith("content-length:")) {
                contentLength = line.substringAfter(":").trim().toIntOrNull() ?: 0
            }
            line = reader.readLine()
        }
        if (contentLength <= 0) return ""
        val buf = CharArray(contentLength)
        var total = 0
        while (total < contentLength) {
            val n = reader.read(buf, total, contentLength - total)
            if (n == -1) break
            total += n
        }
        return String(buf, 0, total)
    }

    private fun parseJsonObject(body: String): JSONObject? = try {
        JSONObject(body)
    } catch (e: Exception) {
        Log.w(TAG, "bad JSON body: ${e.message}")
        null
    }

    private fun writeJson(socket: Socket, code: Int, reason: String, json: String) {
        writeResponse(
            socket.getOutputStream(), code, reason,
            "application/json; charset=utf-8",
            json.toByteArray(Charsets.UTF_8),
        )
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
     * Proxies an HTTP request to a Flask backend. Only used for /api/ paths
     * we didn't satisfy locally — lets a developer run the full Flask stack
     * on 127.0.0.1:5555 for debugging older endpoints.
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
                val errBody = """{"error":"not_available","state":"no_backend"}"""
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
        path.endsWith(".webp") -> "image/webp"
        else -> "application/octet-stream"
    }
}
