package io.gridfront.scout

import android.app.admin.DevicePolicyManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.util.Log
import android.view.KeyEvent
import android.widget.Button
import androidx.appcompat.app.AppCompatActivity
import java.io.DataOutputStream

class PowerMenuActivity : AppCompatActivity() {

    companion object {
        private const val TAG = "GF_PowerMenu"
        const val EXTRA_OPEN_SETTINGS = "gridfront.OPEN_SETTINGS"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_power_menu)

        findViewById<Button>(R.id.btn_reboot).setOnClickListener {
            Log.i(TAG, "Reboot requested")
            doReboot()
        }
        findViewById<Button>(R.id.btn_shutdown).setOnClickListener {
            Log.i(TAG, "Shutdown requested")
            doShutdown()
        }
        findViewById<Button>(R.id.btn_settings).setOnClickListener {
            Log.i(TAG, "Settings requested")
            openSettings()
        }
        findViewById<Button>(R.id.btn_cancel).setOnClickListener {
            finish()
        }
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        if (keyCode == KeyEvent.KEYCODE_BACK) {
            finish()
            return true
        }
        return super.onKeyDown(keyCode, event)
    }

    private fun openSettings() {
        val intent = Intent(this, MainActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT)
            putExtra(EXTRA_OPEN_SETTINGS, true)
        }
        startActivity(intent)
        finish()
    }

    private fun doReboot() {
        val dpm = getSystemService(Context.DEVICE_POLICY_SERVICE) as DevicePolicyManager
        val adminComponent = AdminReceiver.getComponentName(this)
        try {
            if (dpm.isDeviceOwnerApp(packageName)) {
                dpm.reboot(adminComponent)
                return
            }
        } catch (t: Throwable) {
            Log.w(TAG, "DPM.reboot failed, falling back to su", t)
        }
        execRoot("reboot")
        finish()
    }

    private fun doShutdown() {
        execRoot("reboot -p")
        finish()
    }

    private fun execRoot(cmd: String): Boolean {
        return try {
            val p = Runtime.getRuntime().exec(arrayOf("su", "-c", cmd))
            DataOutputStream(p.outputStream).use { }
            true
        } catch (t: Throwable) {
            Log.e(TAG, "Root exec failed: $cmd", t)
            false
        }
    }
}
