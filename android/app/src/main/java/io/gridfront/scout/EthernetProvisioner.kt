package io.gridfront.scout

import android.util.Log
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.NetworkInterface

/**
 * Auto-provisions the USB-C Ethernet dongle so the OAK-D camera can reach
 * the tablet over link-local IPv4.
 *
 * Android's netd does not manage USB-C Ethernet on this Oukitel build — the
 * kernel sees eth0 but netd never assigns an IP, never registers it in the
 * `local` routing table, and never answers ARP for any IP we assign. Without
 * intervention, plugging in the OAK chain gets you a link-up eth0 with zero
 * packet flow.
 *
 * The OAK firmware is flashed to send detections to 169.254.1.56:5556. This
 * class watches for eth0 to appear and applies (via `su`) the minimum setup
 * needed to make that address work:
 *
 *   ip addr add 169.254.1.56/16 dev eth0
 *   ip link set eth0 up
 *   ip route replace local 169.254.1.56/32 dev eth0 table local \
 *       proto kernel scope host src 169.254.1.56
 *   ip rule add to 169.254.0.0/16 lookup main pref 500
 *
 * The `local` table entry is the load-bearing one — without it the kernel
 * treats 169.254.1.56 as remote and falls through to wlan0, which is why
 * `ip addr add` alone looks like it works but actually doesn't.
 */
class EthernetProvisioner {

    companion object {
        private const val TAG = "GF_EthProv"
        private const val TABLET_IP = "169.254.1.56"
        private const val POLL_INTERVAL_MS = 2_000L
        private const val IFACE = "eth0"
    }

    @Volatile private var running = false
    private var thread: Thread? = null
    @Volatile private var lastAppliedIdx: Int = -1

    fun start() {
        if (running) return
        running = true
        thread = Thread({
            Log.i(TAG, "watcher started")
            while (running) {
                try {
                    val idx = ethIndex()
                    if (idx > 0 && idx != lastAppliedIdx) {
                        // Fresh eth0 appearance (or re-plug with new kernel idx).
                        Log.i(TAG, "$IFACE appeared (idx=$idx) — provisioning")
                        if (provision()) {
                            lastAppliedIdx = idx
                        }
                    } else if (idx < 0) {
                        if (lastAppliedIdx >= 0) Log.i(TAG, "$IFACE gone — will re-provision on next appearance")
                        lastAppliedIdx = -1
                    }
                } catch (e: Exception) {
                    Log.w(TAG, "watcher iter failed: ${e.message}")
                }
                try { Thread.sleep(POLL_INTERVAL_MS) } catch (_: InterruptedException) { break }
            }
            Log.i(TAG, "watcher stopped")
        }, "eth-provisioner").also { it.isDaemon = true; it.start() }
    }

    fun stop() {
        running = false
        thread?.interrupt()
        thread = null
    }

    private fun ethIndex(): Int {
        return try {
            val nif = NetworkInterface.getByName(IFACE) ?: return -1
            if (!nif.isUp) -1 else nif.index
        } catch (_: Exception) { -1 }
    }

    private fun provision(): Boolean {
        // Idempotent: each command is allowed to fail (e.g. address already
        // set after a transient unplug) without aborting the sequence.
        val script = """
            ip addr add $TABLET_IP/16 dev $IFACE 2>/dev/null
            ip link set $IFACE up
            ip route replace local $TABLET_IP/32 dev $IFACE table local proto kernel scope host src $TABLET_IP
            ip rule add to 169.254.0.0/16 lookup main pref 500 2>/dev/null
            ip -4 addr show $IFACE | grep $TABLET_IP >/dev/null && ip route show table local | grep "local $TABLET_IP" >/dev/null && echo OK
        """.trimIndent()
        val out = runAsRoot(script) ?: run {
            Log.w(TAG, "su invocation failed")
            return false
        }
        val ok = out.contains("OK")
        Log.i(TAG, if (ok) "provisioned $IFACE=$TABLET_IP" else "provision verify failed: $out")
        return ok
    }

    private fun runAsRoot(cmd: String): String? {
        return try {
            val p = ProcessBuilder("su", "-c", cmd)
                .redirectErrorStream(true)
                .start()
            val reader = BufferedReader(InputStreamReader(p.inputStream))
            val sb = StringBuilder()
            var line: String?
            while (reader.readLine().also { line = it } != null) sb.append(line).append('\n')
            p.waitFor()
            sb.toString()
        } catch (e: Exception) {
            Log.w(TAG, "su failed: ${e.message}")
            null
        }
    }
}
