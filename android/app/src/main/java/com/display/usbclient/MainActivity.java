package com.display.usbclient;

import android.app.Activity;
import android.content.pm.ActivityInfo;
import android.os.Build;
import android.os.Bundle;
import android.util.Log;
import android.view.MotionEvent;
import android.view.Surface;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;

public class MainActivity extends Activity {
    private static final String TAG = "MainActivity";
    private static final String STREAM_HOST = "127.0.0.1";
    private static final int STREAM_PORT = 7070;

    private SurfaceView surfaceView;
    private H264Decoder decoder;
    private StreamReceiver receiver;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE);
        enableFullscreenImmersive();

        surfaceView = new SurfaceView(this);
        surfaceView.getHolder().addCallback(new SurfaceHolder.Callback() {
            @Override
            public void surfaceCreated(SurfaceHolder holder) {
                Log.i(TAG, "Surface created, initializing H264Decoder and StreamReceiver");
                stopPipeline();
                try {
                    decoder = new H264Decoder(holder.getSurface(), 1280, 800);
                    receiver = new StreamReceiver(decoder, STREAM_HOST, STREAM_PORT, 1000L, new StreamReceiver.Listener() {
                        @Override
                        public void onConnected() {
                            Log.i(TAG, "StreamReceiver connected to " + STREAM_HOST + ":" + STREAM_PORT);
                        }

                        @Override
                        public void onDisconnected() {
                            Log.i(TAG, "StreamReceiver disconnected");
                        }

                        @Override
                        public void onConfigReceived(int width, int height, int fps) {
                            Log.i(TAG, "Config received: " + width + "x" + height + " @" + fps + "fps");
                            if (decoder != null && surfaceView != null) {
                                Surface surface = surfaceView.getHolder().getSurface();
                                if (surface != null && surface.isValid()) {
                                    decoder.configure(surface, width, height);
                                }
                            }
                        }

                        @Override
                        public void onVideoFrame(byte[] payload) {
                        }

                        @Override
                        public void onImageFrame(byte[] payload) {
                        }
                    });
                    receiver.start();
                } catch (Exception e) {
                    Log.e(TAG, "Failed initializing decoder or receiver: " + e.getMessage(), e);
                }
            }

            @Override
            public void surfaceChanged(SurfaceHolder holder, int format, int width, int height) {
                Log.i(TAG, "Surface changed: " + width + "x" + height);
            }

            @Override
            public void surfaceDestroyed(SurfaceHolder holder) {
                Log.i(TAG, "Surface destroyed, releasing pipeline");
                stopPipeline();
            }
        });

        surfaceView.setOnTouchListener(new View.OnTouchListener() {
            @Override
            public boolean onTouch(View view, MotionEvent event) {
                int width = view.getWidth();
                int height = view.getHeight();
                if (width <= 0 || height <= 0) {
                    return true;
                }

                float normX = Math.max(0.0f, Math.min(1.0f, event.getX() / (float) width));
                float normY = Math.max(0.0f, Math.min(1.0f, event.getY() / (float) height));

                StreamReceiver currentReceiver = receiver;
                int action = event.getActionMasked();
                switch (action) {
                    case MotionEvent.ACTION_DOWN:
                        if (currentReceiver != null) {
                            currentReceiver.sendTouch("down", normX, normY);
                        }
                        return true;
                    case MotionEvent.ACTION_MOVE:
                        if (currentReceiver != null) {
                            currentReceiver.sendTouch("move", normX, normY);
                        }
                        return true;
                    case MotionEvent.ACTION_UP:
                    case MotionEvent.ACTION_CANCEL:
                        if (currentReceiver != null) {
                            currentReceiver.sendTouch("up", normX, normY);
                        }
                        return true;
                    default:
                        return false;
                }
            }
        });

        setContentView(surfaceView);
    }

    @Override
    protected void onResume() {
        super.onResume();
        enableFullscreenImmersive();
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) {
            enableFullscreenImmersive();
        }
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        stopPipeline();
    }

    private synchronized void stopPipeline() {
        if (receiver != null) {
            try {
                receiver.stopReceiver();
            } catch (Exception e) {
                Log.w(TAG, "Error stopping receiver: " + e.getMessage());
            }
            receiver = null;
        }

        if (decoder != null) {
            try {
                decoder.release();
            } catch (Exception e) {
                Log.w(TAG, "Error releasing decoder: " + e.getMessage());
            }
            decoder = null;
        }
    }

    private void enableFullscreenImmersive() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            WindowInsetsController controller = getWindow().getInsetsController();
            if (controller != null) {
                controller.hide(WindowInsets.Type.statusBars() | WindowInsets.Type.navigationBars());
                controller.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
            }
        } else {
            getWindow().getDecorView().setSystemUiVisibility(
                View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                | View.SYSTEM_UI_FLAG_FULLSCREEN
                | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                | View.SYSTEM_UI_FLAG_LAYOUT_STABLE
            );
        }
    }
}
