package io.gridfront.detect

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.util.Log
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * Foreground service that monitors the detection pipeline and shows live
 * status in the Android notification.
 *
 * Polls the Flask backend health endpoint every 5 seconds and updates
 * the persistent notification with camera count + detection FPS.
 */
class WebServerService : Service() {

    companion object {
        private const val TAG = "GF_Service"
        private const val CHANNEL_ID = "gridfront_detect"
        private const val NOTIFICATION_ID = 1
        private const val HEALTH_URL = "http://127.0.0.1:5555/api/system/health"
        private const val POLL_INTERVAL_MS = 5000L
        private const val FAILURE_WARN_THRESHOLD = 3
    }

    private val handler = Handler(Looper.getMainLooper())
    private var consecutiveFailures = 0

    private val healthPoller = object : Runnable {
        override fun run() {
            Thread {
                val statusText = pollHealth()
                handler.post {
                    updateNotification(statusText)
                    handler.postDelayed(this, POLL_INTERVAL_MS)
                }
            }.start()
        }
    }

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        startForeground(NOTIFICATION_ID, buildNotification("Starting up..."))
        Log.i(TAG, "WebServerService started")

        // Begin health polling after a short initial delay
        handler.postDelayed(healthPoller, POLL_INTERVAL_MS)
    }

    override fun onDestroy() {
        handler.removeCallbacks(healthPoller)
        Log.i(TAG, "WebServerService stopped")
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    /**
     * Poll the Flask health endpoint. Returns a human-readable status string.
     * Never throws — connection failures are caught and tracked.
     */
    private fun pollHealth(): String {
        return try {
            val url = URL(HEALTH_URL)
            val conn = url.openConnection() as HttpURLConnection
            conn.connectTimeout = 3000
            conn.readTimeout = 3000
            conn.requestMethod = "GET"

            try {
                val code = conn.responseCode
                if (code == 200) {
                    val body = conn.inputStream.bufferedReader().readText()
                    val json = JSONObject(body)
                    consecutiveFailures = 0
                    formatHealthStatus(json)
                } else {
                    onHealthFailure("HTTP $code")
                    "Pipeline offline"
                }
            } finally {
                conn.disconnect()
            }
        } catch (e: Exception) {
            onHealthFailure(e.message ?: "unknown error")
            "Pipeline offline"
        }
    }

    /**
     * Extract camera count and FPS from the health JSON response.
     * Gracefully falls back if fields are missing.
     */
    private fun formatHealthStatus(json: JSONObject): String {
        val cameras = json.optInt("active_cameras", 0)
        val fps = json.optDouble("detection_fps", 0.0)
        val fpsStr = String.format("%.1f", fps)
        return "$cameras camera${if (cameras != 1) "s" else ""} active \u2022 Detection at $fpsStr FPS"
    }

    private fun onHealthFailure(reason: String) {
        consecutiveFailures++
        if (consecutiveFailures == FAILURE_WARN_THRESHOLD) {
            Log.w(TAG, "Health check failed $FAILURE_WARN_THRESHOLD consecutive times: $reason")
        } else if (consecutiveFailures % 10 == 0) {
            Log.w(TAG, "Health check still failing ($consecutiveFailures consecutive): $reason")
        }
    }

    private fun updateNotification(statusText: String) {
        val notification = buildNotification(statusText)
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.notify(NOTIFICATION_ID, notification)
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "GridFront Detect",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Detection pipeline status"
            }
            val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            nm.createNotificationChannel(channel)
        }
    }

    private fun buildNotification(statusText: String = "Proximity detection active"): Notification {
        return Notification.Builder(this, CHANNEL_ID)
            .setContentTitle("GridFront Detect")
            .setContentText(statusText)
            .setSmallIcon(android.R.drawable.ic_menu_compass)
            .setOngoing(true)
            .build()
    }
}
