package io.gridfront.scout

import android.app.ActivityManager
import android.app.admin.DevicePolicyManager
import android.content.ComponentName
import android.content.Context
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.util.Log
import android.view.View
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.view.WindowManager
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputConnection
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.content.Intent
import androidx.appcompat.app.AppCompatActivity

/**
 * Main Activity — the GridFront Scout kiosk display.
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
        // MTK "process is bad" recovery: if page hasn't finished loading N ms
        // after (re)build, tear down the dead WebView and rebuild.
        private const val STARTUP_WATCHDOG_MS = 8_000L
    }

    private lateinit var webView: WebView
    private lateinit var dpm: DevicePolicyManager
    private lateinit var adminComponent: ComponentName
    private var wakeLock: PowerManager.WakeLock? = null
    private var assetServer: LocalAssetServer? = null
    private var udpListener: UdpListener? = null
    private lateinit var configStore: ConfigStore
    private var configSync: ConfigSync? = null
    private var ethProvisioner: EthernetProvisioner? = null
    private lateinit var bridge: GFBridge
    @Volatile private var pageHasLoaded = false
    private var rebuildAttempts = 0

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        dpm = getSystemService(Context.DEVICE_POLICY_SERVICE) as DevicePolicyManager
        adminComponent = AdminReceiver.getComponentName(this)

        bridge = GFBridge(this)
        // Without ACCESS_FINE_LOCATION the OS redacts WifiManager.connectionInfo
        // (networkId returns -1, SSID becomes "<unknown>") so the Wi-Fi panel
        // can never show the connected SSID. We have root, so self-heal the
        // grant idempotently — runs cheaply on every cold start.
        bridge.runAsRoot("pm grant ${packageName} android.permission.ACCESS_FINE_LOCATION")
        bridge.runAsRoot("pm grant ${packageName} android.permission.ACCESS_COARSE_LOCATION")
        // The kiosk owns the device — system IMEs (Gboard, AOSP latin)
        // collide with our themed in-page keyboard, so disable every
        // enabled IME we find. Idempotent: running on each cold start
        // re-asserts the desired state if anything re-enabled them.
        try {
            val enabled = bridge.runAsRoot("ime list -s") ?: ""
            enabled.lineSequence()
                .map { it.trim() }
                .filter { it.isNotEmpty() }
                .forEach { bridge.runAsRoot("ime disable $it") }
        } catch (e: Throwable) {
            Log.w(TAG, "ime suppression failed: ${e.message}")
        }
        webView = buildWebView()

        // Restore persisted brightness before first paint.
        val savedBrightness = bridge.getBrightness()
        val lp = window.attributes
        lp.screenBrightness = savedBrightness / 100f
        window.attributes = lp

        setContentView(webView)

        // Now that content view is set, hide system UI and enable kiosk
        hideSystemUI()
        setupKioskMode()

        // Config store is the tablet-owned source of truth for zones + camera poses.
        configStore = ConfigStore(this)
        // ConfigSync answers camera config_request packets and pushes on edits.
        configSync = ConfigSync(configStore).also { it.start() }
        // Camera firmware boots with baked-in zone defaults and waits up to
        // 30s before its first config_request. If the OAK power-cycled while
        // the tablet was off, an unsolicited push closes that window so the
        // operator's saved zones take effect before the first detection frame.
        val syncRef = configSync
        Handler(Looper.getMainLooper()).postDelayed({
            try { syncRef?.pushAll() } catch (e: Throwable) {
                Log.w(TAG, "boot pushAll failed: ${e.message}")
            }
        }, 1_500L)
        // UDP listener receives detection frames from each camera on :5556.
        udpListener = UdpListener().also { it.start() }
        // Auto-configure USB-C Ethernet when the OAK chain plugs in.
        ethProvisioner = EthernetProvisioner().also { it.start() }
        assetServer = LocalAssetServer(
            this,
            udpListener!!,
            configStore,
            configSync!!,
        ).also { it.start() }

        // Load the bundled web app
        webView.loadUrl(LOCAL_URL)
        armStartupWatchdog()

        // Honor "open settings" extra passed in from PowerMenuActivity on cold start
        maybeHandleOpenSettings(intent)

        // Acquire partial wake lock to keep running
        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = pm.newWakeLock(
            PowerManager.PARTIAL_WAKE_LOCK,
            "gridfront:scout"
        ).apply { acquire() }

        // Defer FGS start until the activity has had a chance to settle.
        // Starting it synchronously in onCreate() races the HOME-activity
        // reparent — AM brings the service down before onCreate() calls
        // startForeground(), producing a ForegroundServiceDidNotStartInTimeException.
        Handler(Looper.getMainLooper()).postDelayed({
            val serviceIntent = Intent(this, WebServerService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                startForegroundService(serviceIntent)
            } else {
                startService(serviceIntent)
            }
        }, 2_000L)

        Log.i(TAG, "GridFront Scout started")
        Log.i(TAG, "Device Owner: ${isDeviceOwner()}")
    }

    private fun isDeviceOwner(): Boolean {
        return dpm.isDeviceOwnerApp(packageName)
    }

    private fun buildWebView(): WebView {
        // Subclass so we can swallow the IME's editor connection. Returning
        // null from onCreateInputConnection tells the framework "this view
        // is not a text editor" — Android then never spins up the soft
        // keyboard for it. The WebView's HTML <input>s still receive focus
        // and our themed in-page keyboard inserts text via JS, so users
        // see exactly one keyboard (ours) and not the AOSP one fighting
        // for the bottom of the screen.
        val wv = object : WebView(this) {
            override fun onCreateInputConnection(outAttrs: EditorInfo): InputConnection? {
                outAttrs.imeOptions = EditorInfo.IME_ACTION_NONE or EditorInfo.IME_FLAG_NO_EXTRACT_UI
                outAttrs.inputType = EditorInfo.TYPE_NULL
                return null
            }

            override fun onCheckIsTextEditor(): Boolean = false
        }
        wv.settings.apply {
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
        wv.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(
                view: WebView?,
                request: WebResourceRequest?
            ): Boolean = false

            override fun onPageFinished(view: WebView?, url: String?) {
                super.onPageFinished(view, url)
                Log.i(TAG, "Page loaded: $url")
                if (url != null && url.startsWith(LOCAL_URL)) {
                    pageHasLoaded = true
                    rebuildAttempts = 0
                }
            }

            override fun onReceivedError(
                view: WebView?,
                request: WebResourceRequest?,
                error: WebResourceError?
            ) {
                val url = request?.url?.toString() ?: ""
                val isMain = request?.isForMainFrame == true
                Log.w(TAG, "WebView error isMain=$isMain url=$url code=${error?.errorCode} desc=${error?.description}")
                if (isMain && url.startsWith(LOCAL_URL)) {
                    Handler(Looper.getMainLooper()).postDelayed({
                        Log.i(TAG, "Retrying $LOCAL_URL after transient error")
                        view?.loadUrl(LOCAL_URL)
                    }, 1000)
                }
            }

            // MTK WebView multiprocess is broken — the sandboxed renderer
            // dies on AM "process is bad" and the screen goes white. Catch
            // the crash, destroy the dead WebView, build a fresh one, reload.
            override fun onRenderProcessGone(
                view: WebView?,
                detail: android.webkit.RenderProcessGoneDetail?
            ): Boolean {
                Log.w(TAG, "Render process gone — rebuilding WebView (didCrash=${detail?.didCrash()})")
                Handler(Looper.getMainLooper()).post { rebuildWebView() }
                return true
            }
        }
        wv.webChromeClient = object : WebChromeClient() {
            override fun onConsoleMessage(cm: android.webkit.ConsoleMessage?): Boolean {
                Log.i("GF_JS", "${cm?.messageLevel()} ${cm?.sourceId()}:${cm?.lineNumber()} ${cm?.message()}")
                return true
            }
        }
        wv.setBackgroundColor(0xFFF8F8F8.toInt())
        wv.addJavascriptInterface(bridge, "GFAndroid")
        return wv
    }

    private fun rebuildWebView() {
        pageHasLoaded = false
        rebuildAttempts += 1
        try { webView.destroy() } catch (_: Throwable) {}
        webView = buildWebView()
        setContentView(webView)
        webView.loadUrl(LOCAL_URL)
        armStartupWatchdog()
    }

    // If the WebView's renderer never successfully starts (MTK "process is
    // bad" hits before any render), onRenderProcessGone won't fire. So we
    // also check: after STARTUP_WATCHDOG_MS, if the page hasn't loaded, rebuild.
    private fun armStartupWatchdog() {
        val attempt = rebuildAttempts
        Handler(Looper.getMainLooper()).postDelayed({
            if (!pageHasLoaded && rebuildAttempts == attempt) {
                // Cap exponential-ish backoff — AM's "process is bad" decays
                // over roughly 15–30s. After ~5 tries, let it be.
                if (rebuildAttempts < 6) {
                    Log.w(TAG, "Startup watchdog: page not loaded after ${STARTUP_WATCHDOG_MS}ms, rebuilding (attempt $rebuildAttempts)")
                    rebuildWebView()
                } else {
                    Log.e(TAG, "Startup watchdog: giving up after $rebuildAttempts attempts")
                }
            }
        }, STARTUP_WATCHDOG_MS)
    }

    private fun setupKioskMode() {
        if (!isDeviceOwner()) {
            Log.w(TAG, "Not Device Owner — kiosk lock unavailable. Run: adb shell dpm set-device-owner io.gridfront.scout/.AdminReceiver")
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

    override fun onNewIntent(intent: Intent?) {
        super.onNewIntent(intent)
        setIntent(intent)
        maybeHandleOpenSettings(intent)
        maybeHandleReload(intent)
    }

    private fun maybeHandleOpenSettings(intent: Intent?) {
        if (intent?.getBooleanExtra(PowerMenuActivity.EXTRA_OPEN_SETTINGS, false) == true) {
            webView.postDelayed({
                webView.evaluateJavascript(
                    "typeof toggleSettings === 'function' && toggleSettings();",
                    null
                )
            }, 250)
            intent.removeExtra(PowerMenuActivity.EXTRA_OPEN_SETTINGS)
        }
    }

    private fun maybeHandleReload(intent: Intent?) {
        if (intent?.getBooleanExtra(PowerMenuActivity.EXTRA_RELOAD, false) == true) {
            Log.i(TAG, "Reload intent received — refreshing WebView")
            webView.post { webView.reload() }
            intent.removeExtra(PowerMenuActivity.EXTRA_RELOAD)
        }
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
        configSync?.stop()
        udpListener?.stop()
        ethProvisioner?.stop()
        wakeLock?.release()
        webView.destroy()
        super.onDestroy()
    }
}
