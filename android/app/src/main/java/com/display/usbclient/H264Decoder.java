package com.display.usbclient;

import android.media.MediaCodec;
import android.media.MediaFormat;
import android.os.Build;
import android.util.Log;
import android.view.Surface;
import java.io.IOException;
import java.nio.ByteBuffer;

public class H264Decoder {
    private static final String TAG = "H264Decoder";
    private static final String MIME_TYPE = MediaFormat.MIMETYPE_VIDEO_AVC;
    private static final long DEFAULT_TIMEOUT_US = 5000L;

    private Surface surface;
    private int width = 1920;
    private int height = 1080;
    private MediaCodec codec;
    private final MediaCodec.BufferInfo bufferInfo = new MediaCodec.BufferInfo();
    private final Object lock = new Object();
    private volatile boolean isConfigured = false;
    private volatile boolean isReleased = false;

    public H264Decoder(Surface surface, int width, int height) {
        this.surface = surface;
        this.width = width;
        this.height = height;
        if (surface != null) {
            initializeCodec(surface, width, height);
        }
    }

    public H264Decoder(Surface surface) {
        this(surface, 1920, 1080);
    }

    public void configure(Surface targetSurface, int targetWidth, int targetHeight) {
        synchronized (lock) {
            if (isReleased) return;
            if (isConfigured && this.surface == targetSurface && this.width == targetWidth && this.height == targetHeight) {
                return;
            }
            stopAndReleaseCodecInternal();
            this.surface = targetSurface;
            this.width = targetWidth;
            this.height = targetHeight;
            initializeCodec(targetSurface, targetWidth, targetHeight);
        }
    }

    private void initializeCodec(Surface targetSurface, int w, int h) {
        try {
            MediaFormat format = MediaFormat.createVideoFormat(MIME_TYPE, w, h);
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                try {
                    format.setInteger(MediaFormat.KEY_LOW_LATENCY, 1);
                } catch (Exception ignored) {}
            }

            MediaCodec decoder = null;
            try {
                decoder = MediaCodec.createDecoderByType(MIME_TYPE);
                decoder.configure(format, targetSurface, null, 0);
                decoder.start();
            } catch (Exception hwEx) {
                Log.w(TAG, "Hardware decoder failed (" + hwEx.getMessage() + "), trying Google AVC decoder fallback");
                if (decoder != null) {
                    try { decoder.release(); } catch (Exception ignored) {}
                }
                try {
                    decoder = MediaCodec.createByCodecName("c2.android.avc.decoder");
                } catch (Exception e1) {
                    try {
                        decoder = MediaCodec.createByCodecName("OMX.google.h264.decoder");
                    } catch (Exception e2) {
                        decoder = MediaCodec.createDecoderByType(MIME_TYPE);
                    }
                }
                decoder.configure(format, targetSurface, null, 0);
                decoder.start();
            }

            this.codec = decoder;
            this.isConfigured = true;
            Log.i(TAG, "H264 decoder initialized successfully: " + w + "x" + h);
        } catch (IOException e) {
            Log.e(TAG, "Failed to create H264 decoder: " + e.getMessage(), e);
            isConfigured = false;
        } catch (Exception e) {
            Log.e(TAG, "Unexpected error configuring H264 decoder: " + e.getMessage(), e);
            isConfigured = false;
        }
    }

    public void decodeFrame(byte[] data, int offset, int length, long presentationTimeUs) {
        synchronized (lock) {
            if (!isConfigured || isReleased || codec == null) return;
            try {
                int inputIndex = codec.dequeueInputBuffer(DEFAULT_TIMEOUT_US);
                if (inputIndex >= 0) {
                    ByteBuffer inputBuffer = codec.getInputBuffer(inputIndex);
                    if (inputBuffer != null) {
                        inputBuffer.clear();
                        inputBuffer.put(data, offset, length);
                        long pts = presentationTimeUs > 0 ? presentationTimeUs : (System.nanoTime() / 1000L);
                        codec.queueInputBuffer(inputIndex, 0, length, pts, 0);
                    }
                } else {
                    Log.w(TAG, "Input buffer dequeue timed out, dropping frame slice");
                }
                drainOutput(codec);
            } catch (IllegalStateException e) {
                Log.e(TAG, "MediaCodec invalid state: " + e.getMessage() + ". Resetting...");
                try {
                    stopAndReleaseCodecInternal();
                    if (surface != null && surface.isValid()) {
                        initializeCodec(surface, width, height);
                    }
                } catch (Exception ex) {
                    Log.e(TAG, "Failed recovering MediaCodec: " + ex.getMessage());
                }
            } catch (Exception e) {
                Log.e(TAG, "Error decoding frame: " + e.getMessage(), e);
            }
        }
    }

    public void decodeFrame(byte[] data) {
        decodeFrame(data, 0, data.length, System.nanoTime() / 1000L);
    }

    private void drainOutput(MediaCodec activeCodec) {
        while (true) {
            int outputIndex = activeCodec.dequeueOutputBuffer(bufferInfo, 0);
            if (outputIndex >= 0) {
                activeCodec.releaseOutputBuffer(outputIndex, true);
            } else if (outputIndex == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                Log.i(TAG, "MediaCodec output format changed: " + activeCodec.getOutputFormat());
            } else {
                break;
            }
        }
    }

    private void stopAndReleaseCodecInternal() {
        if (codec != null) {
            try { codec.stop(); } catch (Exception ignored) {}
            try { codec.release(); } catch (Exception ignored) {}
            codec = null;
        }
        isConfigured = false;
    }

    public void release() {
        synchronized (lock) {
            isReleased = true;
            stopAndReleaseCodecInternal();
            surface = null;
            Log.i(TAG, "H264Decoder released");
        }
    }
}
