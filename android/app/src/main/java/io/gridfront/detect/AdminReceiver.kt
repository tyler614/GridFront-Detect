package io.gridfront.detect

import android.app.admin.DeviceAdminReceiver
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.util.Log

/**
 * Device Admin Receiver — enables Device Owner mode for full kiosk lockdown.
 *
 * When set as Device Owner (via ADB `dpm set-device-owner`), this receiver grants
 * the app permission to:
 * - Lock the device into our app (Lock Task / pinned mode)
 * - Disable the status bar, navigation, and notifications
 * - Prevent other apps from launching
 * - Auto-start on boot
 */
class AdminReceiver : DeviceAdminReceiver() {

    companion object {
        private const val TAG = "GF_Admin"

        fun getComponentName(context: Context): ComponentName {
            return ComponentName(context, AdminReceiver::class.java)
        }
    }

    override fun onEnabled(context: Context, intent: Intent) {
        super.onEnabled(context, intent)
        Log.i(TAG, "Device admin enabled")
    }

    override fun onDisabled(context: Context, intent: Intent) {
        super.onDisabled(context, intent)
        Log.i(TAG, "Device admin disabled")
    }

    override fun onProfileProvisioningComplete(context: Context, intent: Intent) {
        super.onProfileProvisioningComplete(context, intent)
        Log.i(TAG, "Profile provisioning complete — starting kiosk setup")

        // Launch main activity to begin kiosk setup
        val launch = Intent(context, MainActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(launch)
    }
}
