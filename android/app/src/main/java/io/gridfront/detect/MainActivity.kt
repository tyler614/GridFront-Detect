package io.gridfront.detect

import android.app.ActivityManager
import android.app.admin.DevicePolicyManager
import android.content.ComponentName
import android.content.Context
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.util.Log
import android.view.View
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.view.WindowManager
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.content.Intent
import androidx.appcompat.app.AppCompatActivity

/**
 * Main Activity — the GridFront Detect kiosk display.
 *
 * Runs a full-screen WebView pointing to the bundled radar UI served from
 * assets/www/. When Device Owner is enabled, locks the device into this
 * app exclusively (Lock Task mode).
 *
 * The WebView loads from http://127.0.0.1:8080/ served by LocalAssetServer,
 * which proxies /api/ requests to the Flask backend on port 5555.
 */
class MainActivity : AppCompatActivity() {

    companion object {
        private const val TAG = "GF_Main"
        private const val LOCAL_URL = "http://127.0.0.1:8080/"
    }

    private lateinit var webView: WebView
    private lateinit var dpm: DevicePolicyManager
    private lateinit var adminComponent: ComponentName
    private var wakeLock: PowerManager.WakeLock? = null
    private var assetServer: LocalAssetServer? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        dpm = getSystemService(Context.DEVICE_POLICY_SERVICE) as DevicePolicyManager
        adminComponent = AdminReceiver.getComponentName(this)

        // Create and configure WebView
        webView = WebView(this).apply {
            settings.apply {
                javaScriptEnabled = true
                domStorageEnabled = true
                databaseEnabled = true
                allowFileAccess = true
                allowContentAccess = true
                mediaPlaybackRequiresUserGesture = false
                mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
                cacheMode = WebSettings.LOAD_DEFAULT
                setSupportZoom(false)
                builtInZoomControls = false
                displayZoomControls = false
                useWideViewPort = true
                loadWithOverviewMode = true
            }

            webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(
                    view: WebView?,
                    request: WebResourceRequest?
                ): Boolean {
                    // Keep all navigation inside our WebView
                    return false
                }

                override fun onPageFinished(view: WebView?, url: String?) {
                    super.onPageFinished(view, url)
                    Log.i(TAG, "Page loaded: $url")
                }
            }

            webChromeClient = WebChromeClient()

            // Light background while loading (matches GridFront theme)
            setBackgroundColor(0xFFF8F8F8.toInt())
        }

        setContentView(webView)

        // Now that content view is set, hide system UI and enable kiosk
        hideSystemUI()
        setupKioskMode()

        // Start local asset server (serves www/ and proxies /api/ to Flask)
        assetServer = LocalAssetServer(this).also { it.start() }

        // Load the bundled web app
        webView.loadUrl(LOCAL_URL)

        // Acquire partial wake lock to keep running
        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = pm.newWakeLock(
            PowerManager.PARTIAL_WAKE_LOCK,
            "gridfront:detect"
        ).apply { acquire() }

        // Start detection service
        val serviceIntent = Intent(this, WebServerService::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(serviceIntent)
        } else {
            startService(serviceIntent)
        }

        Log.i(TAG, "GridFront Detect started")
        Log.i(TAG, "Device Owner: ${isDeviceOwner()}")
    }

    private fun isDeviceOwner(): Boolean {
        return dpm.isDeviceOwnerApp(packageName)
    }

    private fun setupKioskMode() {
        if (!isDeviceOwner()) {
            Log.w(TAG, "Not Device Owner — kiosk lock unavailable. Run: adb shell dpm set-device-owner io.gridfront.detect/.AdminReceiver")
            return
        }

        Log.i(TAG, "Device Owner confirmed — enabling kiosk mode")

        // Allow this app to enter Lock Task mode
        dpm.setLockTaskPackages(adminComponent, arrayOf(packageName))

        // Configure which system UI features are available in lock task
        dpm.setLockTaskFeatures(
            adminComponent,
            // Allow nothing — full lockdown
            DevicePolicyManager.LOCK_TASK_FEATURE_NONE
        )

        // Start lock task (pins the app)
        startLockTask()

        // Disable keyguard (lock screen)
        dpm.setKeyguardDisabled(adminComponent, true)

        // Disable status bar
        dpm.setStatusBarDisabled(adminComponent, true)

        Log.i(TAG, "Kiosk mode fully enabled")
    }

    private fun hideSystemUI() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            window.insetsController?.let { controller ->
                controller.hide(WindowInsets.Type.statusBars() or WindowInsets.Type.navigationBars())
                controller.systemBarsBehavior =
                    WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            }
        } else {
            @Suppress("DEPRECATION")
            window.decorView.systemUiVisibility = (
                View.SYSTEM_UI_FLAG_FULLSCREEN
                    or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                    or View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                    or View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                    or View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                    or View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                )
        }
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) hideSystemUI()
    }

    override fun onBackPressed() {
        // In kiosk mode, back button does nothing (or navigates within WebView)
        if (webView.canGoBack()) {
            webView.goBack()
        }
        // Don't call super — prevents exiting the app
    }

    override fun onDestroy() {
        stopService(Intent(this, WebServerService::class.java))
        assetServer?.stop()
        wakeLock?.release()
        webView.destroy()
        super.onDestroy()
    }
}
