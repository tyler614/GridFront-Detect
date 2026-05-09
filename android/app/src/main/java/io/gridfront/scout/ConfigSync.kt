package io.gridfront.scout

import android.util.Log
import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress

/**
 * Bidirectional config channel between the tablet and each OAK-D camera.
 *
 * Wire format is plain UDP JSON on port 5557 in both directions:
 *   camera → tablet : {"type":"config_request","camera_id":"cam-0"}
 *   tablet → camera : {"type":"config","camera_id":"cam-0",
 *                      "pose":{...}, "zones":[...]}
 *
 * Cameras send a config_request on boot (and every 30s) so the tablet
 * re-seeds them even if the tablet restarted. The tablet also pushes
 * unsolicited on every zone/pose/machine edit.
 */
class ConfigSync(
    private val store: ConfigStore,
    private val port: Int = 5557,
) {
    companion object {
        private const val TAG = "GF_CfgSync"
        private const val MAX_PACKET_BYTES = 4096
    }

    @Volatile private var running = false
    private var socket: DatagramSocket? = null
    private var thread: Thread? = null

    fun start() {
        if (running) return
        running = true
        thread = Thread({
            try {
                // Bind directly with the DatagramSocket(int) constructor.
                // The earlier DatagramSocket(null) + setReuseAddress dance
                // throws "port out of range:-1" on Android when the option
                // is set before bind; no one else shares :5557 so we don't
                // actually need SO_REUSEADDR.
                val sock = DatagramSocket(port)
                sock.broadcast = true
                socket = sock
                Log.i(TAG, "ConfigSync bound to *:$port")

                val buf = ByteArray(MAX_PACKET_BYTES)
                val pkt = DatagramPacket(buf, buf.size)

                while (running) {
                    try {
                        sock.receive(pkt)
                        val body = String(pkt.data, 0, pkt.length, Charsets.UTF_8)
                        handleRequest(body, pkt.address.hostAddress ?: "")
                    } catch (e: Exception) {
                        if (running) Log.w(TAG, "recv failed: ${e.message}")
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "listener thread failed: ${e.message}")
            }
        }, "config-sync-$port").also { it.isDaemon = true; it.start() }
    }

    fun stop() {
        running = false
        try { socket?.close() } catch (_: Exception) {}
        socket = null
        thread = null
    }

    /** Push the current config to every known camera. Called on edits. */
    fun pushAll() {
        for (cam in store.installedCameras()) pushTo(cam.id, cam.ip)
    }

    fun pushTo(cameraId: String, cameraIp: String) {
        val msg = store.messageForCamera(cameraId)
        if (msg == null) {
            Log.w(TAG, "no config for camera_id=$cameraId — skipping push")
            return
        }
        sendJson(cameraIp, msg)
    }

    private fun handleRequest(body: String, senderIp: String) {
        val doc = try { JSONObject(body) } catch (e: Exception) {
            Log.w(TAG, "bad JSON from $senderIp: ${e.message}"); return
        }
        when (doc.optString("type")) {
            "config_request" -> {
                val cameraId = doc.optString("camera_id", "")
                Log.i(TAG, "config_request from $senderIp camera_id=$cameraId")
                val msg = store.messageForCamera(cameraId)
                // Prefer the camera's configured device_id (stable), fall
                // back to the sender's IP if the camera isn't known yet.
                val cams = store.installedCameras().firstOrNull { it.id == cameraId }
                val targetIp = cams?.ip ?: senderIp
                if (msg != null) sendJson(targetIp, msg)
                else Log.w(TAG, "no stored config for $cameraId — reply suppressed")
            }
            else -> Log.d(TAG, "ignored packet from $senderIp: ${body.take(120)}")
        }
    }

    private fun sendJson(ip: String, doc: JSONObject) {
        val sock = socket ?: return
        val payload = doc.toString().toByteArray(Charsets.UTF_8)
        try {
            val addr = InetAddress.getByName(ip)
            sock.send(DatagramPacket(payload, payload.size, addr, port))
        } catch (e: Exception) {
            Log.w(TAG, "sendJson to $ip failed: ${e.message}")
        }
    }
}
