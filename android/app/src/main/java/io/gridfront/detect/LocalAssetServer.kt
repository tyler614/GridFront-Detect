package io.gridfront.detect

import android.content.Context
import android.util.Log
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.ServerSocket
import java.net.Socket

/**
 * Lightweight HTTP server that serves static files from assets/www/ and proxies
 * /api/* requests to the Flask backend on port 5555.
 *
 * This lets the WebView load everything from a single origin (http://127.0.0.1:8080),
 * avoiding cross-origin issues between the static UI and the Python API.
 */
class LocalAssetServer(private val context: Context, private val port: Int = 8080) {
    companion object {
        private const val TAG = "GF_Server"
        private const val FLASK_HOST = "127.0.0.1"
        private const val FLASK_PORT = 5555
    }

    @Volatile
    private var running = false
    private var serverSocket: ServerSocket? = null

    fun start() {
        if (running) return
        running = true
        Thread {
            try {
                serverSocket = ServerSocket(port)
                Log.i(TAG, "LocalAssetServer listening on port $port")
                while (running) {
                    try {
                        val client = serverSocket!!.accept()
                        Thread { handleClient(client) }.start()
                    } catch (e: Exception) {
                        if (running) Log.w(TAG, "Accept error: ${e.message}")
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "Server failed to start: ${e.message}")
            }
        }.start()
    }

    fun stop() {
        running = false
        try {
            serverSocket?.close()
        } catch (_: Exception) {}
        serverSocket = null
        Log.i(TAG, "LocalAssetServer stopped")
    }

    private fun handleClient(socket: Socket) {
        try {
            socket.soTimeout = 15000
            val reader = BufferedReader(InputStreamReader(socket.getInputStream()))
            val requestLine = reader.readLine() ?: return

            // Parse method and path
            val parts = requestLine.split(" ")
            if (parts.size < 2) return
            val path = parts[1].split("?")[0]  // Strip query string for asset lookup

            // Proxy /api/* to Flask backend
            if (path.startsWith("/api/")) {
                proxyToFlask(socket, requestLine, reader)
                return
            }

            // Read and discard remaining headers
            var line = reader.readLine()
            while (line != null && line.isNotEmpty()) {
                line = reader.readLine()
            }

            // Serve static file from assets/www/
            val assetPath = if (path == "/") "www/index.html" else "www${path}"
            val mimeType = getMimeType(assetPath)

            try {
                val inputStream = context.assets.open(assetPath)
                val bytes = inputStream.readBytes()
                inputStream.close()

                val header = "HTTP/1.1 200 OK\r\n" +
                    "Content-Type: $mimeType\r\n" +
                    "Content-Length: ${bytes.size}\r\n" +
                    "Cache-Control: no-cache\r\n" +
                    "Connection: close\r\n\r\n"

                val out = socket.getOutputStream()
                out.write(header.toByteArray())
                out.write(bytes)
                out.flush()
            } catch (e: java.io.FileNotFoundException) {
                val body = "404 Not Found: $path"
                val header = "HTTP/1.1 404 Not Found\r\n" +
                    "Content-Type: text/plain\r\n" +
                    "Content-Length: ${body.length}\r\n" +
                    "Connection: close\r\n\r\n"
                val out = socket.getOutputStream()
                out.write(header.toByteArray())
                out.write(body.toByteArray())
                out.flush()
            }
        } catch (e: Exception) {
            Log.w(TAG, "Client handler error: ${e.message}")
        } finally {
            try { socket.close() } catch (_: Exception) {}
        }
    }

    /**
     * Proxies an HTTP request to the Flask backend. Streams the response back
     * to the client, which is important for SSE (Server-Sent Events) endpoints.
     */
    private fun proxyToFlask(clientSocket: Socket, requestLine: String, clientReader: BufferedReader) {
        try {
            // Read remaining headers from client
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

            // Read body if present (POST/PATCH/DELETE with body)
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

            // Connect to Flask
            val flask = Socket(FLASK_HOST, FLASK_PORT)
            // No soTimeout here — SSE streams are long-lived
            val flaskOut = flask.getOutputStream()
            val flaskIn = flask.getInputStream()

            // Forward the request
            flaskOut.write("$requestLine\r\n".toByteArray())
            for (h in headers) {
                flaskOut.write("$h\r\n".toByteArray())
            }
            flaskOut.write("\r\n".toByteArray())
            if (body != null) {
                flaskOut.write(body.toByteArray())
            }
            flaskOut.flush()

            // Stream response back to client byte-by-byte for SSE support.
            // We read in chunks and write immediately — no buffering the whole response.
            val clientOut = clientSocket.getOutputStream()
            val buffer = ByteArray(8192)
            var bytesRead: Int
            while (flaskIn.read(buffer).also { bytesRead = it } != -1) {
                clientOut.write(buffer, 0, bytesRead)
                clientOut.flush()  // Flush each chunk for SSE
            }

            flask.close()
        } catch (e: Exception) {
            Log.w(TAG, "Proxy error: ${e.message}")
            // Return 502 Bad Gateway
            try {
                val out = clientSocket.getOutputStream()
                val errBody = """{"error":"502 Bad Gateway","detail":"Flask backend unavailable"}"""
                val header = "HTTP/1.1 502 Bad Gateway\r\n" +
                    "Content-Type: application/json\r\n" +
                    "Content-Length: ${errBody.length}\r\n" +
                    "Connection: close\r\n\r\n"
                out.write(header.toByteArray())
                out.write(errBody.toByteArray())
                out.flush()
            } catch (_: Exception) {}
        }
    }

    private fun getMimeType(path: String): String {
        return when {
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
}
