package com.display.usbclient

import android.util.Log
import org.json.JSONObject
import java.io.BufferedInputStream
import java.io.DataInputStream
import java.io.IOException
import java.net.InetSocketAddress
import java.net.Socket

/**
 * Socket listener for USB extended display streaming over ADB forwarded localhost TCP.
 * Connects to 127.0.0.1:7070, unmarshals binary protocol headers (>IB),
 * routes video frames to H264Decoder, handles configuration handshakes, and provides auto-reconnection.
 */
class StreamReceiver(
    private val decoder: H264Decoder? = null,
    private val host: String = "127.0.0.1",
    private val port: Int = 7070,
    private val reconnectDelayMs: Long = 1000L,
    private val listener: Listener? = null
) : Thread("StreamReceiverThread") {

    interface Listener {
        fun onConnected() {}
        fun onDisconnected() {}
        fun onConfigReceived(width: Int, height: Int, fps: Int) {}
        fun onVideoFrame(payload: ByteArray) {}
    }

    companion object {
        const val TAG = "StreamReceiver"
        const val MSG_CONFIG = 1
        const val MSG_VIDEO = 2
        const val MSG_HEARTBEAT = 3
        const val HEADER_SIZE = 5 // 4 bytes totalLen + 1 byte msgType
    }

    @Volatile
    var isRunning: Boolean = true
        private set

    private var activeSocket: Socket? = null

    override fun run() {
        Log.i(TAG, "Starting StreamReceiver worker thread connecting to $host:$port")

        while (isRunning) {
            var socket: Socket? = null
            try {
                socket = Socket().apply {
                    tcpNoDelay = true
                    keepAlive = true
                    receiveBufferSize = 512 * 1024
                    connect(InetSocketAddress(host, port), 3000)
                }
                activeSocket = socket

                Log.i(TAG, "Successfully connected to streamer host at $host:$port")
                listener?.onConnected()

                val dis = DataInputStream(BufferedInputStream(socket.getInputStream(), 64 * 1024))

                while (isRunning) {
                    // Protocol Header: >IB (4-byte Big-Endian totalLen, 1-byte msgType)
                    val totalLen = dis.readInt()
                    if (totalLen < 1) {
                        throw IOException("Invalid packet total length received: $totalLen")
                    }

                    val msgType = dis.readByte().toInt() and 0xFF
                    val payloadLen = totalLen - 1
                    val payload = ByteArray(payloadLen)
                    dis.readFully(payload)

                    when (msgType) {
                        MSG_CONFIG -> handleConfig(payload)
                        MSG_VIDEO -> handleVideo(payload)
                        MSG_HEARTBEAT -> handleHeartbeat(payload)
                        else -> Log.w(TAG, "Unknown message type received: $msgType ($payloadLen bytes)")
                    }
                }
            } catch (e: Exception) {
                if (isRunning) {
                    Log.d(TAG, "Stream disconnected or connection failed: ${e.message}. Reconnecting in ${reconnectDelayMs}ms...")
                    listener?.onDisconnected()
                    try {
                        sleep(reconnectDelayMs)
                    } catch (ie: InterruptedException) {
                        break
                    }
                }
            } finally {
                try {
                    socket?.close()
                } catch (ignored: Exception) {}
                if (activeSocket == socket) {
                    activeSocket = null
                }
            }
        }
        Log.i(TAG, "StreamReceiver thread terminated cleanly")
    }

    private fun handleConfig(payload: ByteArray) {
        try {
            val jsonStr = String(payload, Charsets.UTF_8)
            Log.i(TAG, "Received MSG_CONFIG: $jsonStr")
            val json = JSONObject(jsonStr)
            val width = json.optInt("width", 1920)
            val height = json.optInt("height", 1080)
            val fps = json.optInt("fps", 60)
            listener?.onConfigReceived(width, height, fps)
        } catch (e: Exception) {
            Log.e(TAG, "Failed parsing config payload: ${e.message}", e)
        }
    }

    private fun handleVideo(payload: ByteArray) {
        decoder?.decodeFrame(payload)
        listener?.onVideoFrame(payload)
    }

    private fun handleHeartbeat(payload: ByteArray) {
        Log.v(TAG, "Received heartbeat ping (${payload.size} bytes)")
    }

    /**
     * Gracefully stops the receiver thread and closes any active socket connection.
     */
    fun stopReceiver() {
        isRunning = false
        try {
            activeSocket?.close()
        } catch (ignored: Exception) {}
        interrupt()
    }
}
