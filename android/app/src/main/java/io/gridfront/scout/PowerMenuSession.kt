package io.gridfront.scout

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.service.voice.VoiceInteractionSession
import android.util.Log

class PowerMenuSession(context: Context) : VoiceInteractionSession(context) {

    override fun onShow(args: Bundle?, showFlags: Int) {
        super.onShow(args, showFlags)
        Log.i("GF_VIS", "onShow flags=$showFlags — launching PowerMenuActivity")
        val intent = Intent(context, PowerMenuActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        }
        try {
            startAssistantActivity(intent)
        } catch (t: Throwable) {
            Log.w("GF_VIS", "startAssistantActivity failed, trying context.startActivity", t)
            context.startActivity(intent)
        }
        hide()
    }
}
