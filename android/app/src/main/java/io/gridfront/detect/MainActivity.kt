package io.gridfront.detect

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
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.appcompat.app.AppCompatActivity

/**
 * Main Activity — the GridFront Detect kiosk display.
 *
 * Runs a full-screen WebView loading from a local HTTP server that serves
 * assets/www/. This avoids the WebView sandbox "process is bad" bug on
 * MediaTek devices that breaks file:///android_asset/ URLs.
 */
class MainActivity : AppCompatActivity() {

    companion object {
        private const val TAG = "GF_Main"
        private const val SERVER_PORT = 8080
        private const val LOCAL_URL = "http://127.0.0.1:$SERVER_PORT/"
    }

    private lateinit var webView: WebView
    private lateinit var dpm: DevicePolicyManager
    private lateinit var adminComponent: ComponentName
    private var wakeLock: PowerManager.WakeLock? = null
    private var assetServer: LocalAssetServer? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Full-screen flags before anything renders
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        window.addFlags(WindowManager.LayoutParams.FLAG_DRAWS_SYSTEM_BAR_BACKGROUNDS)
        window.statusBarColor = 0xFFF8F8F8.toInt()
        window.navigationBarColor = 0xFFF8F8F8.toInt()

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            window.setDecorFitsSystemWindows(false)
        }

        dpm = getSystemService(Context.DEVICE_POLICY_SERVICE) as DevicePolicyManager
        adminComponent = AdminReceiver.getComponentName(this)

        // Start local HTTP server for assets
        assetServer = LocalAssetServer(this, SERVER_PORT).also { it.start() }
        Log.i(TAG, "Asset server starting on port $SERVER_PORT")

        // Enable remote debugging via chrome://inspect
        WebView.setWebContentsDebuggingEnabled(true)

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
                cacheMode = WebSettings.LOAD_NO_CACHE
                setSupportZoom(false)
                builtInZoomControls = false
                displayZoomControls = false
                useWideViewPort = true
                loadWithOverviewMode = true
            }

            webViewClient = object : WebViewClient() {
                override fun onPageFinished(view: WebView?, url: String?) {
                    super.onPageFinished(view, url)
                    Log.i(TAG, "Page loaded: $url")
                }

                override fun onReceivedError(
                    view: WebView?,
                    errorCode: Int,
                    description: String?,
                    failingUrl: String?
                ) {
                    Log.e(TAG, "WebView error ($errorCode): $description — $failingUrl")
                }
            }

            webChromeClient = object : WebChromeClient() {
                override fun onConsoleMessage(message: android.webkit.ConsoleMessage?): Boolean {
                    message?.let {
                        Log.i(TAG, "JS [${it.messageLevel()}] ${it.message()} (${it.sourceId()}:${it.lineNumber()})")
                    }
                    return true
                }
            }

            setBackgroundColor(0xFFF8F8F8.toInt())
        }

        setContentView(webView)

        hideSystemUI()
        setupKioskMode()

        // Small delay to let the server start before loading
        webView.postDelayed({
            Log.i(TAG, "Loading $LOCAL_URL")
            webView.loadUrl(LOCAL_URL)
        }, 300)

        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = pm.newWakeLock(
            PowerManager.PARTIAL_WAKE_LOCK,
            "gridfront:detect"
        ).apply { acquire() }

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
        dpm.setLockTaskPackages(adminComponent, arrayOf(packageName))
        dpm.setLockTaskFeatures(adminComponent, DevicePolicyManager.LOCK_TASK_FEATURE_NONE)
        startLockTask()
        dpm.setKeyguardDisabled(adminComponent, true)
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
        if (webView.canGoBack()) {
            webView.goBack()
        }
    }

    override fun onDestroy() {
        wakeLock?.release()
        assetServer?.stop()
        webView.destroy()
        super.onDestroy()
    }
}
