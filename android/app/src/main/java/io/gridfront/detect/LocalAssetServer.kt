package io.gridfront.detect

import android.content.Context
import android.util.Log
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.PrintWriter
import java.net.ServerSocket
import java.net.Socket

/**
 * Minimal HTTP server that serves files from assets/www/ on localhost:8080.
 * This bypasses the WebView sandbox "process is bad" bug on MediaTek devices.
 */
class LocalAssetServer(private val context: Context, private val port: Int = 8080) {

    companion object {
        private const val TAG = "GF_Server"
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
                Log.i(TAG, "Asset server started on port $port")
                while (running) {
                    try {
                        val client = serverSocket?.accept() ?: break
                        Thread { handleClient(client) }.start()
                    } catch (e: Exception) {
                        if (running) Log.w(TAG, "Accept error: ${e.message}")
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "Server failed: ${e.message}")
            }
        }.start()
    }

    fun stop() {
        running = false
        try { serverSocket?.close() } catch (_: Exception) {}
    }

    private fun handleClient(socket: Socket) {
        try {
            socket.soTimeout = 5000
            val reader = BufferedReader(InputStreamReader(socket.getInputStream()))
            val requestLine = reader.readLine() ?: return
            // Parse "GET /path HTTP/1.1"
            val parts = requestLine.split(" ")
            if (parts.size < 2) return

            var path = parts[1]
            if (path == "/") path = "/index.html"
            // Remove leading slash
            val assetPath = "www${path}"

            val contentType = when {
                path.endsWith(".html") -> "text/html; charset=utf-8"
                path.endsWith(".js") -> "application/javascript; charset=utf-8"
                path.endsWith(".css") -> "text/css; charset=utf-8"
                path.endsWith(".json") -> "application/json; charset=utf-8"
                path.endsWith(".png") -> "image/png"
                path.endsWith(".jpg") || path.endsWith(".jpeg") -> "image/jpeg"
                path.endsWith(".svg") -> "image/svg+xml"
                path.endsWith(".glb") -> "model/gltf-binary"
                path.endsWith(".gltf") -> "model/gltf+json"
                else -> "application/octet-stream"
            }

            try {
                val input = context.assets.open(assetPath)
                val bytes = input.readBytes()
                input.close()

                val out = socket.getOutputStream()
                val header = "HTTP/1.1 200 OK\r\n" +
                    "Content-Type: $contentType\r\n" +
                    "Content-Length: ${bytes.size}\r\n" +
                    "Access-Control-Allow-Origin: *\r\n" +
                    "Cache-Control: no-cache\r\n" +
                    "Connection: close\r\n\r\n"
                out.write(header.toByteArray())
                out.write(bytes)
                out.flush()
            } catch (e: java.io.FileNotFoundException) {
                val out = socket.getOutputStream()
                val body = "404 Not Found: $assetPath"
                val header = "HTTP/1.1 404 Not Found\r\n" +
                    "Content-Type: text/plain\r\n" +
                    "Content-Length: ${body.length}\r\n" +
                    "Connection: close\r\n\r\n"
                out.write(header.toByteArray())
                out.write(body.toByteArray())
                out.flush()
                Log.w(TAG, "404: $assetPath")
            }
        } catch (e: Exception) {
            Log.w(TAG, "Client error: ${e.message}")
        } finally {
            try { socket.close() } catch (_: Exception) {}
        }
    }
}
