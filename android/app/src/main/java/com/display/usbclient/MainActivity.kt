package com.display.usbclient

import android.app.Activity
import android.content.pm.ActivityInfo
import android.os.Build
import android.os.Bundle
import android.util.Log
import android.view.MotionEvent
import android.view.SurfaceHolder
import android.view.SurfaceView
import android.view.View
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.view.WindowManager

/**
 * Main Activity hosting the fullscreen SurfaceView for zero-copy hardware rendering.
 * Configures landscape orientation, keeps screen on, enables immersive sticky mode,
 * and manages the lifecycle of the H264Decoder and StreamReceiver.
 */
class MainActivity : Activity(), SurfaceHolder.Callback, StreamReceiver.Listener {

    companion object {
        private const val TAG = "MainActivity"
        private const val STREAM_HOST = "127.0.0.1"
        private const val STREAM_PORT = 7070
    }

    private var surfaceView: SurfaceView? = null
    private var decoder: H264Decoder? = null
    private var receiver: StreamReceiver? = null
    private var currentSurfaceHolder: SurfaceHolder? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Keep screen continuously active without dimming
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        // Lock activity strictly to landscape orientation
        requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE

        // Setup immersive sticky fullscreen mode
        enableFullscreenImmersive()

        surfaceView = SurfaceView(this).apply {
            holder.addCallback(this@MainActivity)
            setOnTouchListener { view, event ->
                val w = view.width
                val h = view.height
                if (w <= 0 || h <= 0) return@setOnTouchListener true

                val normX = (event.x / w.toFloat()).coerceIn(0.0f, 1.0f)
                val normY = (event.y / h.toFloat()).coerceIn(0.0f, 1.0f)

                val activeReceiver = receiver
                when (event.actionMasked) {
                    MotionEvent.ACTION_DOWN -> {
                        activeReceiver?.sendTouch("down", normX, normY)
                        true
                    }
                    MotionEvent.ACTION_MOVE -> {
                        activeReceiver?.sendTouch("move", normX, normY)
                        true
                    }
                    MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                        activeReceiver?.sendTouch("up", normX, normY)
                        true
                    }
                    else -> false
                }
            }
        }
        setContentView(surfaceView)
    }

    override fun onResume() {
        super.onResume()
        enableFullscreenImmersive()
    }

    private fun enableFullscreenImmersive() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            window.insetsController?.let { controller ->
                controller.hide(WindowInsets.Type.statusBars() or WindowInsets.Type.navigationBars())
                controller.systemBarsBehavior = WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            }
        } else {
            @Suppress("DEPRECATION")
            window.decorView.systemUiVisibility = (
                View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                    or View.SYSTEM_UI_FLAG_FULLSCREEN
                    or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                    or View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                    or View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                    or View.SYSTEM_UI_FLAG_LAYOUT_STABLE
            )
        }
    }

    override fun surfaceCreated(holder: SurfaceHolder) {
        Log.i(TAG, "Surface created, binding decoder and starting StreamReceiver")
        currentSurfaceHolder = holder
        val newDecoder = H264Decoder(holder.surface)
        decoder = newDecoder

        val newReceiver = StreamReceiver(
            decoder = newDecoder,
            host = STREAM_HOST,
            port = STREAM_PORT,
            listener = this
        )
        receiver = newReceiver
        newReceiver.start()
    }

    override fun surfaceChanged(holder: SurfaceHolder, format: Int, width: Int, height: Int) {
        Log.i(TAG, "Surface dimensions updated: ${width}x${height}, format: $format")
        currentSurfaceHolder = holder
    }

    override fun surfaceDestroyed(holder: SurfaceHolder) {
        Log.i(TAG, "Surface destroyed, terminating stream pipeline")
        currentSurfaceHolder = null
        stopAndCleanPipeline()
    }

    override fun onConfigReceived(width: Int, height: Int, fps: Int) {
        Log.i(TAG, "Config received from host: ${width}x${height} @ ${fps}fps")
        currentSurfaceHolder?.surface?.let { surf ->
            decoder?.configure(surf, width, height)
        }
    }

    override fun onConnected() {
        Log.i(TAG, "Connected to USB display streamer on $STREAM_HOST:$STREAM_PORT")
    }

    override fun onDisconnected() {
        Log.d(TAG, "Disconnected from USB display streamer")
    }

    private fun stopAndCleanPipeline() {
        receiver?.stopReceiver()
        receiver = null

        decoder?.release()
        decoder = null
    }

    override fun onDestroy() {
        super.onDestroy()
        stopAndCleanPipeline()
    }
}
