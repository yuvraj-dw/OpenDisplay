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
    private int width = 1280;
    private int height = 800;
    private MediaCodec codec;
    private final MediaCodec.BufferInfo bufferInfo = new MediaCodec.BufferInfo();
    private final Object lock = new Object();
    private volatile boolean isConfigured = false;
    private volatile boolean isReleased = false;
    private volatile boolean isRunning = false;
    private Thread outputThread;

    public H264Decoder(Surface surface, int width, int height) {
        this.surface = surface;
        this.width = width;
        this.height = height;
        if (surface != null) {
            initializeCodec(surface, width, height);
        }
    }

    public H264Decoder(Surface surface) {
        this(surface, 1280, 800);
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
            try { format.setInteger(MediaFormat.KEY_PRIORITY, 0); } catch (Exception ignored) {}
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                try {
                    format.setInteger(MediaFormat.KEY_LOW_LATENCY, 1);
                } catch (Exception ignored) {}
            }
            try { format.setInteger("vendor.mtk-ext-dec-low-latency.enable", 1); } catch (Exception ignored) {}
            try { format.setInteger("vendor.rtc-ext-dec-low-latency.enable", 1); } catch (Exception ignored) {}
            try { format.setInteger("low-latency", 1); } catch (Exception ignored) {}

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
            this.isRunning = true;
            this.outputThread = new Thread(new Runnable() {
                @Override
                public void run() {
                    runOutputLoop();
                }
            }, "H264DecoderOutputThread");
            this.outputThread.start();
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

                        int flags = 0;
                        boolean hasSlice = false;
                        boolean hasConfig = false;
                        // ponytail: NAL headers are at packet start; scan at most first 128 bytes
                        int scanLimit = Math.min(offset + length - 4, offset + 128);
                        for (int i = offset; i < scanLimit; i++) {
                            if (data[i] == 0 && data[i + 1] == 0 && (data[i + 2] == 1 || (data[i + 2] == 0 && data[i + 3] == 1))) {
                                int headerIdx = (data[i + 2] == 1) ? (i + 3) : (i + 4);
                                int nalType = data[headerIdx] & 0x1F;
                                if (nalType == 1 || nalType == 5) {
                                    hasSlice = true;
                                    break;
                                } else if (nalType == 7 || nalType == 8) {
                                    hasConfig = true;
                                }
                            }
                        }
                        if (!hasSlice && hasConfig) {
                            flags = MediaCodec.BUFFER_FLAG_CODEC_CONFIG;
                        }

                        codec.queueInputBuffer(inputIndex, 0, length, pts, flags);
                    }
                } else {
                    Log.w(TAG, "Input buffer dequeue timed out, dropping frame slice");
                }
            } catch (IllegalStateException e) {
                Log.e(TAG, "MediaCodec invalid state: " + e.getMessage(), e);
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
        if (data == null) return;
        decodeFrame(data, 0, data.length, 0);
    }

    private void runOutputLoop() {
        MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
        while (isRunning && !isReleased) {
            MediaCodec activeCodec = this.codec;
            if (activeCodec == null || !isConfigured) {
                try {
                    Thread.sleep(5);
                } catch (InterruptedException e) {
                    break;
                }
                continue;
            }
            try {
                int outputIndex = activeCodec.dequeueOutputBuffer(info, 10000);
                if (outputIndex >= 0) {
                    activeCodec.releaseOutputBuffer(outputIndex, true);
                    // ponytail: immediately drain any queued ready frames without 10ms wait
                    while (isRunning && !isReleased) {
                        int nextIdx = activeCodec.dequeueOutputBuffer(info, 0);
                        if (nextIdx >= 0) {
                            activeCodec.releaseOutputBuffer(nextIdx, true);
                        } else {
                            break;
                        }
                    }
                } else if (outputIndex == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                    Log.i(TAG, "MediaCodec output format changed: " + activeCodec.getOutputFormat());
                }
            } catch (IllegalStateException e) {
                break;
            } catch (Exception e) {
                Log.w(TAG, "Output loop notice: " + e.getMessage());
            }
        }
    }

    private void stopAndReleaseCodecInternal() {
        isRunning = false;
        if (outputThread != null) {
            try { outputThread.interrupt(); } catch (Exception ignored) {}
            try { outputThread.join(200); } catch (Exception ignored) {}
            outputThread = null;
        }
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
