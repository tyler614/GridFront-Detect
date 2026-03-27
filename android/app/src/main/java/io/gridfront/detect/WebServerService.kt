package io.gridfront.detect

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.util.Log

/**
 * Foreground service placeholder for future BLE + detection pipeline.
 *
 * In production, this service will:
 * - Manage BLE connection to Thingy:91 X
 * - Receive detection data from OAK-D via Thingy BLE
 * - Relay detection data to the WebView via JavaScript injection
 * - Upload detection events to GridFront platform via LTE/WiFi
 * - Capture and upload annotated screenshots
 */
class WebServerService : Service() {

    companion object {
        private const val TAG = "GF_Service"
        private const val CHANNEL_ID = "gridfront_detect"
        private const val NOTIFICATION_ID = 1
    }

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        startForeground(NOTIFICATION_ID, buildNotification())
        Log.i(TAG, "WebServerService started")
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "GridFront Detect",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Proximity detection service"
            }
            val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            nm.createNotificationChannel(channel)
        }
    }

    private fun buildNotification(): Notification {
        return Notification.Builder(this, CHANNEL_ID)
            .setContentTitle("GridFront Detect")
            .setContentText("Proximity detection active")
            .setSmallIcon(android.R.drawable.ic_menu_compass)
            .setOngoing(true)
            .build()
    }
}
