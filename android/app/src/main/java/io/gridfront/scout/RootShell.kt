package io.gridfront.scout

import android.util.Log
import java.io.BufferedReader
import java.io.InputStreamReader

object RootShell {
    private const val TAG = "GF_Root"

    fun run(cmd: String): String? {
        return try {
            val p = ProcessBuilder("su", "-c", "$cmd 2>&1")
                .redirectErrorStream(true)
                .start()
            val reader = BufferedReader(InputStreamReader(p.inputStream))
            val sb = StringBuilder()
            var line: String?
            while (reader.readLine().also { line = it } != null) {
                sb.append(line).append('\n')
            }
            val rc = p.waitFor()
            if (rc != 0) Log.w(TAG, "su rc=$rc for '$cmd', out=${sb.take(200)}")
            sb.toString()
        } catch (e: Exception) {
            Log.w(TAG, "su failed for '$cmd': ${e.message}")
            null
        }
    }
}
