package io.gridfront.scout

import android.util.Log
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.SocketException
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference

/**
 * UDP receiver for the standalone OAK-D pipeline.
 *
 * The OAK broadcasts JSON detection packets on port 5556 (see
 * pipeline/standalone/script_runtime.py). This listener stores the most
 * recent payload and fans it out to any SSE subscribers registered by
 * LocalAssetServer.
 *
 * Topology today: OAK PoE -> PoE injector -> USB-C Ethernet -> tablet.
 * The OAK target IP is baked at flash time; if the target matches the
 * tablet's USB-C interface IP, packets land here. If it doesn't, this
 * listener sits idle and the WebView falls back to mock mode.
 */
class UdpListener(private val port: Int = 5556) {

    companion object {
        private const val TAG = "GF_Udp"
        private const val MAX_PACKET_BYTES = 2048
    }

    fun interface Subscriber {
        fun onPacket(payload: String)
    }

    private val latest = AtomicReference<String?>(null)
    private val lastRxMs = AtomicLong(0L)
    private val subscribers = CopyOnWriteArrayList<Subscriber>()

    @Volatile
    private var running = false
    private var socket: DatagramSocket? = null
    private var thread: Thread? = null

    fun start() {
        if (running) return
        running = true
        thread = Thread({
            try {
                val sock = DatagramSocket(port).also { it.reuseAddress = true }
                // Broadcast reception — in case the OAK sends to 255.255.255.255
                sock.broadcast = true
                socket = sock
                Log.i(TAG, "UDP listener bound to *:$port")

                val buf = ByteArray(MAX_PACKET_BYTES)
                val pkt = DatagramPacket(buf, buf.size)

                while (running) {
                    try {
                        sock.receive(pkt)
                        val payload = String(pkt.data, 0, pkt.length, Charsets.UTF_8)
                        latest.set(payload)
                        lastRxMs.set(System.currentTimeMillis())
                        // Fan out — swallow per-subscriber errors so one bad
                        // consumer doesn't starve the rest.
                        for (sub in subscribers) {
                            try { sub.onPacket(payload) } catch (e: Exception) {
                                Log.w(TAG, "subscriber threw: ${e.message}")
                            }
                        }
                    } catch (e: SocketException) {
                        if (running) Log.w(TAG, "socket error: ${e.message}")
                    } catch (e: Exception) {
                        Log.w(TAG, "recv failed: ${e.message}")
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "listener thread failed: ${e.message}")
            }
        }, "udp-listener-$port").also { it.isDaemon = true; it.start() }
    }

    fun stop() {
        running = false
        try { socket?.close() } catch (_: Exception) {}
        socket = null
        thread = null
    }

    /** Most recent JSON payload, or null if nothing received yet. */
    fun latestPayload(): String? = latest.get()

    /** Epoch millis when the last packet arrived, or 0 if none. */
    fun lastRxEpochMs(): Long = lastRxMs.get()

    fun subscribe(sub: Subscriber) { subscribers.add(sub) }
    fun unsubscribe(sub: Subscriber) { subscribers.remove(sub) }
}
