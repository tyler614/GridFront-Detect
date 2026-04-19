package io.gridfront.detect

import android.content.Intent
import android.service.voice.VoiceInteractionService
import android.util.Log

class PowerMenuVoiceService : VoiceInteractionService() {
    override fun onReady() {
        super.onReady()
        Log.i("GF_VIS", "ready")
    }
}
