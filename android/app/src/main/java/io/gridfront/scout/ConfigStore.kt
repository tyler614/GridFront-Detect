package io.gridfront.scout

import android.content.Context
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * Thread-safe store for the tablet-owned zone/machine config.
 *
 * Kept on disk at filesDir/config.json. This is the authoritative copy —
 * the OAK-D firmware holds only a baked fallback plus whatever the tablet
 * has pushed over UDP since boot.
 *
 * Schema (simplified — circles-only, per Phase 1 plan):
 * ```
 * {
 *   "machine_name": "Machine 1",
 *   "machine_type": "wheel_loader",
 *   "machine_footprint_m": {"length": 8.0, "width": 2.5},
 *   "installed_cameras": [
 *     {"id": "cam-0", "label": "Front", "device_id": "169.254.1.222",
 *      "position_m": [0.0, 4.0, 2.0],  // [x, y, z] in machine frame
 *      "yaw_deg": 0.0, "pitch_deg": 0.0, "roll_deg": 0.0,
 *      "hfov_deg": 127.0, "max_range_m": 12.0}
 *   ],
 *   "zones": [
 *     {"id": "z-1", "color": "danger",  "cx_m": 0.0, "cy_m": 0.0, "r_m": 3.5},
 *     {"id": "z-2", "color": "warning", "cx_m": 0.0, "cy_m": 0.0, "r_m": 6.0}
 *   ]
 * }
 * ```
 */
class ConfigStore(context: Context) {

    companion object {
        private const val TAG = "GF_Cfg"
        private const val FILE_NAME = "config.json"
    }

    private val file = File(context.filesDir, FILE_NAME)
    private val lock = Any()

    fun read(): JSONObject = synchronized(lock) {
        if (!file.exists()) {
            val defaults = defaultConfig()
            try { file.writeText(defaults.toString(2)) }
            catch (e: Exception) { Log.w(TAG, "seed write failed: ${e.message}") }
            return defaults
        }
        try {
            JSONObject(file.readText())
        } catch (e: Exception) {
            Log.w(TAG, "config.json corrupt (${e.message}) — recreating")
            val defaults = defaultConfig()
            try { file.writeText(defaults.toString(2)) } catch (_: Exception) {}
            defaults
        }
    }

    fun write(doc: JSONObject): JSONObject = synchronized(lock) {
        try {
            file.writeText(doc.toString(2))
        } catch (e: Exception) {
            Log.e(TAG, "write failed: ${e.message}")
        }
        doc
    }

    fun mutate(block: (JSONObject) -> Unit): JSONObject = synchronized(lock) {
        val doc = read()
        block(doc)
        write(doc)
    }

    /** Build the UDP push payload destined for a specific camera. */
    fun messageForCamera(cameraId: String): JSONObject? = synchronized(lock) {
        val doc = read()
        val cam = findCamera(doc, cameraId) ?: return null
        val pose = JSONObject().apply {
            val pos = cam.optJSONArray("position_m")
            put("x_m",     pos?.optDouble(0, 0.0) ?: 0.0)
            put("y_m",     pos?.optDouble(1, 0.0) ?: 0.0)
            put("yaw_deg", cam.optDouble("yaw_deg", 0.0))
        }
        // Zones are now interpreted as "distance from machine edge", so the
        // OAK needs the machine rectangle to compute point-to-edge distance.
        val fp = doc.optJSONObject("machine_footprint_m")
        val machine = JSONObject().apply {
            put("length", fp?.optDouble("length", 8.0) ?: 8.0)
            put("width",  fp?.optDouble("width",  2.5) ?: 2.5)
        }
        JSONObject().apply {
            put("type",                "config")
            put("camera_id",           cameraId)
            put("pose",                pose)
            put("zones",               zonesForCamera(doc, cameraId))
            put("machine_footprint_m", machine)
            put("target_fps",          doc.optDouble("target_fps", 10.0))
        }
    }

    /** All installed cameras (id + ip) for ConfigSync's push loop. */
    fun installedCameras(): List<CameraRef> = synchronized(lock) {
        val doc = read()
        val cams = doc.optJSONArray("installed_cameras") ?: return emptyList()
        val out = ArrayList<CameraRef>(cams.length())
        for (i in 0 until cams.length()) {
            val c = cams.optJSONObject(i) ?: continue
            val id = c.optString("id", "").takeIf { it.isNotBlank() } ?: continue
            val ip = c.optString("device_id", "").takeIf { it.isNotBlank() } ?: continue
            out.add(CameraRef(id, ip))
        }
        out
    }

    private fun findCamera(doc: JSONObject, cameraId: String): JSONObject? {
        val cams = doc.optJSONArray("installed_cameras") ?: return null
        for (i in 0 until cams.length()) {
            val c = cams.optJSONObject(i) ?: continue
            if (c.optString("id") == cameraId) return c
        }
        return null
    }

    private fun zonesForCamera(doc: JSONObject, cameraId: String): JSONArray {
        // Current behaviour: one global zone list applies to all cameras.
        // Per-camera overrides can be added later via a per_camera_zones
        // block without touching the firmware contract.
        val raw = doc.optJSONArray("zones") ?: JSONArray()
        val out = JSONArray()
        for (i in 0 until raw.length()) {
            val z = raw.optJSONObject(i) ?: continue
            out.put(JSONObject().apply {
                put("color", z.optString("color", "warning"))
                put("cx_m", z.optDouble("cx_m", 0.0))
                put("cy_m", z.optDouble("cy_m", 0.0))
                put("r_m",  z.optDouble("r_m",  0.0))
            })
        }
        return out
    }

    private fun defaultConfig(): JSONObject = JSONObject().apply {
        put("machine_name", "Machine")
        put("machine_type", "wheel_loader")
        put("machine_footprint_m", JSONObject().apply {
            put("length", 8.0)
            put("width",  2.5)
        })
        put("target_fps", 10.0)
        put("active_model", ModelRegistry.DEFAULT_MODEL_ID)
        put("pending_model", "")
        put("installed_cameras", JSONArray())
        put("zones", JSONArray().apply {
            put(JSONObject().apply {
                put("id",    "z-1")
                put("color", "danger")
                put("cx_m",  0.0); put("cy_m", 0.0); put("r_m", 3.5)
            })
            put(JSONObject().apply {
                put("id",    "z-2")
                put("color", "warning")
                put("cx_m",  0.0); put("cy_m", 0.0); put("r_m", 6.0)
            })
        })
    }

    data class CameraRef(val id: String, val ip: String)
}
