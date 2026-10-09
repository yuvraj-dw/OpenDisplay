package com.display.usbclient;

import android.content.Context;
import android.hardware.usb.UsbAccessory;
import android.hardware.usb.UsbManager;
import android.os.ParcelFileDescriptor;
import android.util.Log;
import org.json.JSONObject;

import java.io.BufferedInputStream;
import java.io.DataInputStream;
import java.io.FileDescriptor;
import java.io.FileInputStream;
import java.io.FileOutputStream;
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
    public interface StreamListener {
        void onConnected();
        void onDisconnected();
        void onConfigReceived(int width, int height, int fps);
        void onVideoFrame(byte[] payload);
        void onImageFrame(byte[] payload);
    }

    public interface Listener extends StreamListener {
    }

    public static final String TAG = "StreamReceiver";
    public static final int MSG_CONFIG = 1;
    public static final int MSG_VIDEO = 2;
    public static final int MSG_HEARTBEAT = 3;

    private H264Decoder decoder;
    private String host = "127.0.0.1";
    private int port = 7070;
    private long reconnectDelayMs = 1000L;
    private StreamListener listener;

    private UsbAccessory accessory;
    private Context context;
    private ParcelFileDescriptor pfd;
    private FileInputStream fileInputStream;
    private FileOutputStream fileOutputStream;

    private volatile boolean isRunning = true;
    private final Object outputLock = new Object();
    private Socket activeSocket;
    private OutputStream activeOutputStream;
    private ThreadPoolExecutor touchExecutor;

    public StreamReceiver(UsbAccessory accessory, Context context, StreamListener listener) {
        super("StreamReceiverThread");
        this.accessory = accessory;
        this.context = context;
        this.listener = listener;
        this.touchExecutor = new ThreadPoolExecutor(
            1, 1, 0L, TimeUnit.MILLISECONDS,
            new LinkedBlockingQueue<>(16),
            new ThreadPoolExecutor.DiscardOldestPolicy()
        );
    }

    public StreamReceiver(H264Decoder decoder, UsbAccessory accessory, Context context, StreamListener listener) {
        this(accessory, context, listener);
        this.decoder = decoder;
    }

    public StreamReceiver(String host, int port, StreamListener listener) {
        super("StreamReceiverThread");
        this.host = host != null ? host : "127.0.0.1";
        this.port = port > 0 ? port : 7070;
        this.reconnectDelayMs = 1000L;
        this.listener = listener;
        this.touchExecutor = new ThreadPoolExecutor(
            1, 1, 0L, TimeUnit.MILLISECONDS,
            new LinkedBlockingQueue<>(16),
            new ThreadPoolExecutor.DiscardOldestPolicy()
        );
    }

    public StreamReceiver(H264Decoder decoder, String host, int port, long reconnectDelayMs, StreamListener listener) {
        super("StreamReceiverThread");
        this.decoder = decoder;
        this.host = host != null ? host : "127.0.0.1";
        this.port = port > 0 ? port : 7070;
        this.reconnectDelayMs = reconnectDelayMs > 0 ? reconnectDelayMs : 1000L;
        this.listener = listener;
        this.touchExecutor = new ThreadPoolExecutor(
            1, 1, 0L, TimeUnit.MILLISECONDS,
            new LinkedBlockingQueue<>(16),
            new ThreadPoolExecutor.DiscardOldestPolicy()
        );
    }

    public StreamReceiver(H264Decoder decoder, StreamListener listener) {
        this(decoder, "127.0.0.1", 7070, 1000L, listener);
    }

    public H264Decoder getDecoder() {
        return decoder;
    }

    public void setDecoder(H264Decoder decoder) {
        this.decoder = decoder;
    }

    @Override
    public void run() {
        if (accessory != null) {
            runAccessory();
        } else {
            runSocket();
        }
    }

    private void runAccessory() {
        Log.i(TAG, "Starting StreamReceiver worker thread in AOAP Accessory mode");
        try {
            if (context == null) {
                Log.e(TAG, "Context is null for UsbAccessory mode");
                return;
            }
            UsbManager usbManager = (UsbManager) context.getSystemService(Context.USB_SERVICE);
            if (usbManager == null) {
                Log.e(TAG, "UsbManager is null");
                return;
            }

            pfd = usbManager.openAccessory(accessory);
            if (pfd == null) {
                Log.w(TAG, "Failed to open UsbAccessory (pfd is null). Failing over to TCP socket...");
                if (listener != null) listener.onDisconnected();
                runSocket();
                return;
            }

            FileDescriptor fd = pfd.getFileDescriptor();
            fileInputStream = new FileInputStream(fd);
            synchronized (outputLock) {
                fileOutputStream = new FileOutputStream(fd);
            }

            Log.i(TAG, "UsbAccessory opened successfully");
            if (listener != null) listener.onConnected();

            DataInputStream dis = new DataInputStream(new BufferedInputStream(fileInputStream, 64 * 1024));

            while (isRunning) {
                int totalLen = dis.readInt();
                if (totalLen < 1 || totalLen > 16 * 1024 * 1024) {
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
                Log.w(TAG, "Accessory stream disconnected/failed: " + e.getMessage() + ". Failing over to TCP socket...");
                if (listener != null) listener.onDisconnected();
                closeAccessory();
                runSocket();
                return;
            }
        } finally {
            closeAccessory();
        }
        Log.i(TAG, "StreamReceiver accessory thread terminated cleanly");
    }

    private void runSocket() {
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
                    if (totalLen < 1 || totalLen > 16 * 1024 * 1024) {
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
                closeSocket(socket);
            }
        }
        Log.i(TAG, "StreamReceiver TCP thread terminated cleanly");
    }

    public void sendTouch(String action, float normX, float normY) {
        if (!isRunning) return;
        final String message = "m:" + action + ":" + String.format(Locale.US, "%.4f:%.4f", normX, normY) + "\n";
        try {
            if (touchExecutor != null) {
                touchExecutor.execute(new Runnable() {
                    @Override
                    public void run() {
                        synchronized (outputLock) {
                            try {
                                byte[] bytes = message.getBytes(StandardCharsets.UTF_8);
                                if (fileOutputStream != null) {
                                    fileOutputStream.write(bytes);
                                    fileOutputStream.flush();
                                } else if (activeOutputStream != null) {
                                    activeOutputStream.write(bytes);
                                    activeOutputStream.flush();
                                }
                            } catch (IOException e) {
                                Log.w(TAG, "Failed sending touch message: " + e.getMessage());
                            }
                        }
                    }
                });
            }
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

    private void closeAccessory() {
        synchronized (outputLock) {
            if (fileOutputStream != null) {
                try { fileOutputStream.close(); } catch (Exception ignored) {}
                fileOutputStream = null;
            }
        }
        if (fileInputStream != null) {
            try { fileInputStream.close(); } catch (Exception ignored) {}
            fileInputStream = null;
        }
        if (pfd != null) {
            try { pfd.close(); } catch (Exception ignored) {}
            pfd = null;
        }
    }

    private void closeSocket(Socket socket) {
        synchronized (outputLock) {
            if (activeOutputStream != null) {
                try { activeOutputStream.close(); } catch (Exception ignored) {}
                activeOutputStream = null;
            }
            if (socket != null) {
                try { socket.close(); } catch (Exception ignored) {}
            }
            if (activeSocket == socket) {
                activeSocket = null;
            }
        }
    }

    private void closeSocket() {
        synchronized (outputLock) {
            if (activeOutputStream != null) {
                try { activeOutputStream.close(); } catch (Exception ignored) {}
                activeOutputStream = null;
            }
            if (activeSocket != null) {
                try { activeSocket.close(); } catch (Exception ignored) {}
                activeSocket = null;
            }
        }
    }

    public void stopReceiver() {
        isRunning = false;
        closeSocket();
        closeAccessory();
        if (touchExecutor != null) {
            try {
                touchExecutor.shutdownNow();
            } catch (Exception ignored) {}
        }
        interrupt();
    }
}
