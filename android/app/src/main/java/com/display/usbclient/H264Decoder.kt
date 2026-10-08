package com.display.usbclient

import android.media.MediaCodec
import android.media.MediaFormat
import android.os.Build
import android.util.Log
import android.view.Surface
import java.io.IOException

/**
 * Low-latency hardware H.264 (AVC) video decoder using MediaCodec.
 * Outputs decoded frames directly to the provided Surface for zero-copy hardware rendering.
 */
class H264Decoder(
    private var surface: Surface? = null,
    private var width: Int = 1280,
    private var height: Int = 800
) {
    companion object {
        private const val TAG = "H264Decoder"
        private const val MIME_TYPE = MediaFormat.MIMETYPE_VIDEO_AVC
        private const val DEFAULT_TIMEOUT_US = 5_000L // 5ms timeout for input buffer acquisition
    }

    private var codec: MediaCodec? = null
    private val bufferInfo = MediaCodec.BufferInfo()
    private val lock = Any()

    @Volatile
    private var isConfigured = false

    @Volatile
    private var isReleased = false

    init {
        surface?.let {
            initializeCodec(it, width, height)
        }
    }

    /**
     * Initializes or reconfigures the MediaCodec instance for the specified Surface and resolution.
     */
    fun configure(targetSurface: Surface, targetWidth: Int, targetHeight: Int) {
        synchronized(lock) {
            if (isReleased) return

            if (isConfigured && surface == targetSurface && width == targetWidth && height == targetHeight) {
                return
            }

            stopAndReleaseCodecInternal()
            this.surface = targetSurface
            this.width = targetWidth
            this.height = targetHeight
            initializeCodec(targetSurface, targetWidth, targetHeight)
        }
    }

    private fun initializeCodec(targetSurface: Surface, w: Int, h: Int) {
        try {
            val format = MediaFormat.createVideoFormat(MIME_TYPE, w, h).apply {
                // Low-latency configuration for real-time display streaming
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                    try {
                        setInteger(MediaFormat.KEY_LOW_LATENCY, 1)
                    } catch (ignored: Exception) {}
                }
            }

            val decoder = MediaCodec.createDecoderByType(MIME_TYPE)
            decoder.configure(format, targetSurface, null, 0)
            decoder.start()

            codec = decoder
            isConfigured = true
            Log.i(TAG, "Hardware H264 decoder initialized successfully: ${w}x${h}")
        } catch (e: IOException) {
            Log.e(TAG, "Failed to create H264 decoder: ${e.message}", e)
            isConfigured = false
        } catch (e: Exception) {
            Log.e(TAG, "Unexpected error configuring H264 decoder: ${e.message}", e)
            isConfigured = false
        }
    }

    /**
     * Feeds an H.264 NAL unit or frame slice into MediaCodec and renders available frames to Surface.
     */
    fun decodeFrame(data: ByteArray, offset: Int = 0, length: Int = data.size, presentationTimeUs: Long = 0) {
        synchronized(lock) {
            if (!isConfigured || isReleased) return
            val activeCodec = codec ?: return

            try {
                // 1. Submit input buffer
                val inputIndex = activeCodec.dequeueInputBuffer(DEFAULT_TIMEOUT_US)
                if (inputIndex >= 0) {
                    val inputBuffer = activeCodec.getInputBuffer(inputIndex)
                    if (inputBuffer != null) {
                        inputBuffer.clear()
                        inputBuffer.put(data, offset, length)
                        activeCodec.queueInputBuffer(inputIndex, 0, length, presentationTimeUs, 0)
                    }
                } else {
                    Log.w(TAG, "Input buffer full / dequeue timed out, dropping frame slice")
                }

                // 2. Drain all available decoded output buffers zero-copy to the Surface
                drainOutput(activeCodec)
            } catch (e: IllegalStateException) {
                Log.e(TAG, "MediaCodec invalid state during decoding: ${e.message}")
            } catch (e: Exception) {
                Log.e(TAG, "Error during frame decoding: ${e.message}", e)
            }
        }
    }

    /**
     * Drains output buffers and presents them zero-copy to the bound Surface.
     */
    private fun drainOutput(activeCodec: MediaCodec) {
        while (true) {
            val outputIndex = activeCodec.dequeueOutputBuffer(bufferInfo, 0)
            when {
                outputIndex >= 0 -> {
                    // render = true sends the buffer directly to the Surface zero-copy
                    activeCodec.releaseOutputBuffer(outputIndex, true)
                }
                outputIndex == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> {
                    val newFormat = activeCodec.outputFormat
                    Log.i(TAG, "MediaCodec output format changed: $newFormat")
                }
                outputIndex == MediaCodec.INFO_TRY_AGAIN_LATER -> {
                    break
                }
                else -> {
                    break
                }
            }
        }
    }

    private fun stopAndReleaseCodecInternal() {
        codec?.let { c ->
            try {
                c.stop()
            } catch (ignored: Exception) {}
            try {
                c.release()
            } catch (ignored: Exception) {}
        }
        codec = null
        isConfigured = false
    }

    /**
     * Releases MediaCodec resources.
     */
    fun release() {
        synchronized(lock) {
            isReleased = true
            stopAndReleaseCodecInternal()
            surface = null
            Log.i(TAG, "H264Decoder released")
        }
    }
}
