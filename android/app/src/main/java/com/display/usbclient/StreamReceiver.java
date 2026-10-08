package com.display.usbclient;

import android.util.Log;
import org.json.JSONObject;
import java.io.BufferedInputStream;
import java.io.DataInputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

public class StreamReceiver extends Thread {
    public interface Listener {
        void onConnected();
        void onDisconnected();
        void onConfigReceived(int width, int height, int fps);
        void onVideoFrame(byte[] payload);
        void onImageFrame(byte[] payload);
    }

    public static final String TAG = "StreamReceiver";
    public static final int MSG_CONFIG = 1;
    public static final int MSG_VIDEO = 2;
    public static final int MSG_HEARTBEAT = 3;

    private final H264Decoder decoder;
    private final String host;
    private final int port;
    private final long reconnectDelayMs;
    private final Listener listener;

    private volatile boolean isRunning = true;
    private final Object outputLock = new Object();
    private Socket activeSocket;
    private OutputStream activeOutputStream;
    private final ThreadPoolExecutor sendExecutor = new ThreadPoolExecutor(
        1, 1, 0L, TimeUnit.MILLISECONDS,
        new LinkedBlockingQueue<Runnable>(64),
        new ThreadPoolExecutor.DiscardOldestPolicy()
    );

    public StreamReceiver(H264Decoder decoder, String host, int port, long reconnectDelayMs, Listener listener) {
        super("StreamReceiverThread");
        this.decoder = decoder;
        this.host = host != null ? host : "127.0.0.1";
        this.port = port > 0 ? port : 7070;
        this.reconnectDelayMs = reconnectDelayMs > 0 ? reconnectDelayMs : 1000L;
        this.listener = listener;
    }

    public StreamReceiver(H264Decoder decoder, Listener listener) {
        this(decoder, "127.0.0.1", 7070, 1000L, listener);
    }

    @Override
    public void run() {
        Log.i(TAG, "Starting StreamReceiver worker thread connecting to " + host + ":" + port);

        while (isRunning) {
            Socket socket = null;
            try {
                socket = new Socket();
                socket.setTcpNoDelay(true);
                socket.setKeepAlive(true);
                socket.setReceiveBufferSize(512 * 1024);
                socket.connect(new InetSocketAddress(host, port), 3000);

                synchronized (outputLock) {
                    activeSocket = socket;
                    activeOutputStream = socket.getOutputStream();
                }

                Log.i(TAG, "Connected to streamer host at " + host + ":" + port);
                if (listener != null) listener.onConnected();

                DataInputStream dis = new DataInputStream(new BufferedInputStream(socket.getInputStream(), 64 * 1024));

                while (isRunning) {
                    int totalLen = dis.readInt();
                    if (totalLen < 1) {
                        throw new IOException("Invalid packet total length: " + totalLen);
                    }
                    int msgType = dis.readByte() & 0xFF;
                    int payloadLen = totalLen - 1;
                    byte[] payload = new byte[payloadLen];
                    dis.readFully(payload);

                    switch (msgType) {
                        case MSG_CONFIG:
                            handleConfig(payload);
                            break;
                        case MSG_VIDEO:
                            handleVideo(payload);
                            break;
                        case MSG_HEARTBEAT:
                            handleHeartbeat(payload);
                            break;
                        default:
                            Log.w(TAG, "Unknown message type: " + msgType);
                            break;
                    }
                }
            } catch (Exception e) {
                if (isRunning) {
                    Log.d(TAG, "Stream disconnected: " + e.getMessage() + ". Reconnecting in " + reconnectDelayMs + "ms...");
                    if (listener != null) listener.onDisconnected();
                    try {
                        Thread.sleep(reconnectDelayMs);
                    } catch (InterruptedException ie) {
                        break;
                    }
                }
            } finally {
                synchronized (outputLock) {
                    activeOutputStream = null;
                    if (socket != null) {
                        try { socket.close(); } catch (Exception ignored) {}
                    }
                    if (activeSocket == socket) {
                        activeSocket = null;
                    }
                }
            }
        }
        Log.i(TAG, "StreamReceiver thread terminated cleanly");
    }

    public void sendTouch(String action, float normX, float normY) {
        if (!isRunning) return;
        final String message = "m:" + action + ":" + String.format(Locale.US, "%.4f:%.4f", normX, normY) + "\n";
        try {
            sendExecutor.execute(new Runnable() {
                @Override
                public void run() {
                    synchronized (outputLock) {
                        if (activeOutputStream != null) {
                            try {
                                activeOutputStream.write(message.getBytes(StandardCharsets.UTF_8));
                                activeOutputStream.flush();
                            } catch (IOException e) {
                                Log.w(TAG, "Failed sending touch message: " + e.getMessage());
                            }
                        }
                    }
                }
            });
        } catch (RejectedExecutionException ignored) {
        }
    }

    private void handleConfig(byte[] payload) {
        try {
            String jsonStr = new String(payload, StandardCharsets.UTF_8);
            Log.i(TAG, "Received MSG_CONFIG: " + jsonStr);
            JSONObject json = new JSONObject(jsonStr);
            int width = json.optInt("width", 1280);
            int height = json.optInt("height", 800);
            int fps = json.optInt("fps", 60);
            if (listener != null) listener.onConfigReceived(width, height, fps);
        } catch (Exception e) {
            Log.e(TAG, "Failed parsing config payload: " + e.getMessage(), e);
        }
    }

    private void handleVideo(byte[] payload) {
        if (payload == null || payload.length == 0) return;
        boolean isJpeg = payload.length > 2 && (payload[0] & 0xFF) == 0xFF && (payload[1] & 0xFF) == 0xD8;
        if (isJpeg) {
            if (listener != null) {
                listener.onImageFrame(payload);
            }
        } else {
            if (decoder != null) {
                decoder.decodeFrame(payload, 0, payload.length, 0);
            }
            if (listener != null) {
                listener.onVideoFrame(payload);
            }
        }
    }

    private void handleHeartbeat(byte[] payload) {
        Log.v(TAG, "Heartbeat ping (" + payload.length + " bytes)");
    }

    public void stopReceiver() {
        isRunning = false;
        synchronized (outputLock) {
            activeOutputStream = null;
            if (activeSocket != null) {
                try { activeSocket.close(); } catch (Exception ignored) {}
            }
            activeSocket = null;
        }
        try {
            sendExecutor.shutdownNow();
        } catch (Exception ignored) {}
        interrupt();
    }
}
