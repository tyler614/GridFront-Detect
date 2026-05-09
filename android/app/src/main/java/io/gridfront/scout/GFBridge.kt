package io.gridfront.scout

import android.app.Activity
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioManager
import android.net.wifi.WifiManager
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.telephony.TelephonyManager
import android.util.Log
import android.webkit.JavascriptInterface
import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest
import kotlin.math.roundToInt

/**
 * JavaScript bridge exposed to the WebView as `GFAndroid`.
 * All UI-affecting methods marshal to the main thread.
 */
class GFBridge(private val activity: Activity) {

    companion object {
        private const val TAG = "GF_Bridge"
        private const val PREFS = "gridfront_settings"
    }

    private val main = Handler(Looper.getMainLooper())
    private val prefs by lazy { activity.getSharedPreferences(PREFS, Context.MODE_PRIVATE) }
    private val audio by lazy { activity.getSystemService(Context.AUDIO_SERVICE) as AudioManager }
    private val wifi by lazy {
        activity.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
    }
    private val telephony by lazy {
        activity.getSystemService(Context.TELEPHONY_SERVICE) as TelephonyManager
    }

    // ---------- Brightness ----------

    @JavascriptInterface
    fun setBrightness(pct: Int) {
        val clamped = pct.coerceIn(5, 100)
        prefs.edit().putInt("brightness", clamped).apply()
        main.post {
            val lp = activity.window.attributes
            lp.screenBrightness = clamped / 100f
            activity.window.attributes = lp
        }
    }

    @JavascriptInterface
    fun getBrightness(): Int = prefs.getInt("brightness", 80)

    // ---------- Volume ----------

    @JavascriptInterface
    fun setVolume(pct: Int) {
        val clamped = pct.coerceIn(0, 100)
        val max = audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC)
        val v = (clamped / 100f * max).roundToInt()
        audio.setStreamVolume(AudioManager.STREAM_MUSIC, v, 0)
        audio.setStreamVolume(AudioManager.STREAM_NOTIFICATION, v, 0)
        audio.setStreamVolume(AudioManager.STREAM_ALARM, v, 0)
        prefs.edit().putInt("volume", clamped).apply()
    }

    @JavascriptInterface
    fun getVolume(): Int {
        val max = audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC)
        if (max <= 0) return 0
        val cur = audio.getStreamVolume(AudioManager.STREAM_MUSIC)
        return (cur * 100f / max).roundToInt()
    }

    // ---------- Device identity ----------

    @JavascriptInterface
    fun getSerial(): String {
        @Suppress("HardwareIds")
        val android = Settings.Secure.getString(
            activity.contentResolver,
            Settings.Secure.ANDROID_ID
        ) ?: "unknown"
        val digest = MessageDigest.getInstance("SHA-256").digest(android.toByteArray())
        // Take first 3 bytes → 0..16777215 → modulo 1M → zero-pad to 6 digits.
        val n = ((digest[0].toInt() and 0xFF) shl 16) or
                ((digest[1].toInt() and 0xFF) shl 8) or
                (digest[2].toInt() and 0xFF)
        return String.format("%06d", n % 1_000_000)
    }

    @JavascriptInterface
    fun getVersion(): String {
        return try {
            activity.packageManager.getPackageInfo(activity.packageName, 0).versionName ?: "?"
        } catch (e: PackageManager.NameNotFoundException) {
            "?"
        }
    }

    // ---------- Power / reset ----------

    @JavascriptInterface
    fun reboot() {
        Log.i(TAG, "reboot requested")
        // su reboot — works reliably on the rooted kiosk; DPM reboot requires
        // strict conditions we don't always meet when lock task is active.
        runAsRoot("sync; setprop sys.powerctl reboot") ?: runAsRoot("reboot")
    }

    @JavascriptInterface
    fun resetSettings() {
        Log.i(TAG, "resetSettings requested")
        prefs.edit().clear().apply()
        main.post {
            activity.findViewById<android.webkit.WebView>(android.R.id.content)
            // Clearing webview storage is handled on the JS side; this is
            // the Android-side mirror for persisted Android prefs.
        }
    }

    // ---------- Network info ----------

    @JavascriptInterface
    fun getWifiInfo(): String {
        val o = JSONObject()
        try {
            o.put("enabled", wifi.isWifiEnabled)
            // Even with ACCESS_FINE_LOCATION granted, Android 11+ redacts
            // WifiManager.connectionInfo when system "location services"
            // are off — networkId becomes -1 and the SSID returns
            // "<unknown>". This is a kiosk with location services
            // permanently off, so parse `cmd wifi status` via root for
            // the authoritative state instead.
            val raw = runAsRoot("cmd wifi status") ?: ""
            val ssidMatch = Regex("""WifiInfo:\s+SSID:\s+"([^"]*)"""").find(raw)
            val ssid = ssidMatch?.groupValues?.get(1) ?: ""
            val ipMatch = Regex("""IP:\s+/([0-9.]+)""").find(raw)
            val ip = ipMatch?.groupValues?.get(1) ?: ""
            val rssiMatch = Regex("""RSSI:\s+(-?\d+)""").find(raw)
            val rssi = rssiMatch?.groupValues?.get(1)?.toIntOrNull() ?: 0
            val speedMatch = Regex("""Link speed:\s+(\d+)Mbps""").find(raw)
            val speed = speedMatch?.groupValues?.get(1)?.toIntOrNull() ?: 0
            val supplicantOk = raw.contains("Supplicant state: COMPLETED")
            val connectedLine = raw.contains("Wifi is connected to")
            o.put("connected", supplicantOk && connectedLine && ssid.isNotEmpty())
            o.put("ssid", ssid)
            o.put("rssi", rssi)
            o.put("linkSpeedMbps", speed)
            o.put("ip", ip)
        } catch (e: Exception) {
            o.put("error", e.message ?: "unknown")
        }
        return o.toString()
    }

    @JavascriptInterface
    fun getCellularInfo(): String {
        val o = JSONObject()
        try {
            o.put("simState", simStateLabel(telephony.simState))
            o.put("carrier", telephony.networkOperatorName ?: "")
            o.put("operator", telephony.networkOperator ?: "")
            o.put("dataState", dataStateLabel(telephony.dataState))
            // `settings get global mobile_data` reflects the user-facing
            // toggle state, which is what the operator expects to see in
            // the UI — `telephony.dataState` only flips when there's an
            // active data connection, so it would lie if mobile data was
            // turned on with no carrier.
            val raw = runAsRoot("settings get global mobile_data")?.trim()
            o.put("dataEnabled", raw == "1")
        } catch (e: SecurityException) {
            o.put("error", "permission_denied")
        } catch (e: Exception) {
            o.put("error", e.message ?: "unknown")
        }
        return o.toString()
    }

    @JavascriptInterface
    fun setMobileDataEnabled(enabled: Boolean) {
        // `svc data` alone is a no-op on this MTK build — `settings get
        // global mobile_data` stays at "1" regardless. Writing the global
        // setting directly is what the framework actually honours; pair it
        // with `svc data` so the live data connection follows the toggle
        // (otherwise the radio stays attached even after the user flips it
        // off).
        val v = if (enabled) "1" else "0"
        runAsRoot("settings put global mobile_data $v")
        runAsRoot("svc data ${if (enabled) "enable" else "disable"}")
    }

    @JavascriptInterface
    fun triggerWifiScan(): Boolean {
        val out = runAsRoot("cmd wifi start-scan") ?: return false
        Log.i(TAG, "triggerWifiScan: $out")
        return true
    }

    @JavascriptInterface
    fun scanWifi(): String {
        // Format (Android 14, `cmd wifi list-scan-results`):
        //   BSSID  Frequency  RSSI  Age(sec)  SSID  Flags
        // SSID may contain spaces ("Helvey's WiFi", "DIRECT-59-HP DeskJet…").
        // Flags always start with '[', so we use that as the anchor.
        val out = runAsRoot("cmd wifi list-scan-results") ?: return "[]"
        Log.i(TAG, "scanWifi raw output (${out.length} chars):\n$out")
        val seen = HashMap<String, JSONObject>()
        val lines = out.split("\n").drop(1)
        val bssidRe = Regex("^[0-9a-fA-F:]{17}\\b")
        for (raw in lines) {
            val line = raw.trimEnd()
            if (line.isBlank()) continue
            val t = line.trim()
            val bssidMatch = bssidRe.find(t) ?: continue
            val bssid = bssidMatch.value
            val afterBssid = t.substring(bssidMatch.range.last + 1).trim()
            val head = afterBssid.split(Regex("\\s+"), 4)
            if (head.size < 4) continue
            val rssi = head[1].toIntOrNull() ?: -127
            val remainder = head[3]
            // remainder is "<SSID> <Flags>" where Flags starts with '['.
            val flagsStart = remainder.indexOf('[')
            val ssidRaw = (if (flagsStart >= 0) remainder.substring(0, flagsStart) else remainder).trim()
            val caps = if (flagsStart >= 0) remainder.substring(flagsStart) else ""
            if (ssidRaw.isEmpty()) continue
            val secured = caps.contains("WPA") || caps.contains("WEP") ||
                    caps.contains("PSK") || caps.contains("EAP") || caps.contains("SAE")
            val prev = seen[ssidRaw]
            if (prev == null || rssi > prev.optInt("rssi", -999)) {
                val item = JSONObject()
                item.put("bssid", bssid)
                item.put("ssid", ssidRaw)
                item.put("rssi", rssi)
                item.put("secured", secured)
                seen[ssidRaw] = item
            }
        }
        val list = JSONArray()
        seen.values.sortedByDescending { it.optInt("rssi", -999) }.forEach { list.put(it) }
        return list.toString()
    }

    @JavascriptInterface
    fun connectWifi(ssid: String, password: String): Boolean {
        // Escape single quotes in user input.
        val safeSsid = ssid.replace("'", "'\\''")
        val safePass = password.replace("'", "'\\''")
        val cmd = if (password.isEmpty()) {
            "cmd wifi connect-network '$safeSsid' open"
        } else {
            "cmd wifi connect-network '$safeSsid' wpa2 '$safePass'"
        }
        val out = runAsRoot(cmd) ?: return false
        Log.i(TAG, "connectWifi: $out")
        return !out.contains("error", ignoreCase = true)
    }

    @JavascriptInterface
    fun setWifiEnabled(enabled: Boolean) {
        runAsRoot("svc wifi ${if (enabled) "enable" else "disable"}")
    }

    // ---------- Debug (ADB) ----------

    @JavascriptInterface
    fun setDebug(enabled: Boolean) {
        if (enabled) {
            runAsRoot("settings put global development_settings_enabled 1")
            runAsRoot("settings put global adb_enabled 1")
            // Wireless debugging requires adb tcp port set.
            runAsRoot("setprop service.adb.tcp.port 5555")
            runAsRoot("stop adbd; start adbd")
        } else {
            runAsRoot("setprop service.adb.tcp.port -1")
            runAsRoot("settings put global adb_enabled 0")
            runAsRoot("stop adbd; start adbd")
        }
        prefs.edit().putBoolean("debug", enabled).apply()
    }

    @JavascriptInterface
    fun getDebug(): Boolean {
        val adbEnabled = runAsRoot("settings get global adb_enabled")?.trim() == "1"
        return adbEnabled
    }

    @JavascriptInterface
    fun getDebugEndpoint(): String {
        val o = JSONObject()
        val port = runAsRoot("getprop service.adb.tcp.port")?.trim() ?: ""
        o.put("port", port)
        val wifiIp = runAsRoot("ip -4 -o addr show wlan0 | awk '{print \$4}' | cut -d/ -f1")?.trim() ?: ""
        o.put("ip", wifiIp)
        return o.toString()
    }

    // ---------- Helpers ----------

    private fun simStateLabel(state: Int): String = when (state) {
        TelephonyManager.SIM_STATE_ABSENT -> "absent"
        TelephonyManager.SIM_STATE_READY -> "ready"
        TelephonyManager.SIM_STATE_PIN_REQUIRED -> "pin_required"
        TelephonyManager.SIM_STATE_PUK_REQUIRED -> "puk_required"
        TelephonyManager.SIM_STATE_NETWORK_LOCKED -> "network_locked"
        TelephonyManager.SIM_STATE_NOT_READY -> "not_ready"
        TelephonyManager.SIM_STATE_PERM_DISABLED -> "perm_disabled"
        TelephonyManager.SIM_STATE_CARD_IO_ERROR -> "card_io_error"
        TelephonyManager.SIM_STATE_CARD_RESTRICTED -> "card_restricted"
        else -> "unknown"
    }

    private fun dataStateLabel(state: Int): String = when (state) {
        TelephonyManager.DATA_DISCONNECTED -> "disconnected"
        TelephonyManager.DATA_CONNECTING -> "connecting"
        TelephonyManager.DATA_CONNECTED -> "connected"
        TelephonyManager.DATA_SUSPENDED -> "suspended"
        else -> "unknown"
    }

    internal fun runAsRoot(cmd: String): String? {
        return RootShell.run(cmd)
    }
}
