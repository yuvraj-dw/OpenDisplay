package com.display.usbclient;

import android.app.Activity;
import android.app.ActivityManager;
import android.app.KeyguardManager;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ActivityInfo;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.hardware.usb.UsbAccessory;
import android.hardware.usb.UsbManager;
import android.os.Build;
import android.os.Bundle;
import android.os.PowerManager;
import android.util.Log;
import android.view.MotionEvent;
import android.view.Surface;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;

public class MainActivity extends Activity implements StreamReceiver.StreamListener {
    private static final String TAG = "MainActivity";
    private static final String STREAM_HOST = "127.0.0.1";
    private static final int STREAM_PORT = 7070;

    private SurfaceView surfaceView;
    private View idleLayout;
    private android.widget.TextView statusText;
    private android.widget.ProgressBar statusSpinner;
    private android.widget.TextView deviceInfoText;
    private H264Decoder decoder;
    private StreamReceiver streamReceiver;
    private boolean isStreamingActive = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        initWakeAndUnlock();
        setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE);
        enableFullscreenImmersive();

        setContentView(R.layout.activity_main);
        surfaceView = findViewById(R.id.surface_view);
        idleLayout = findViewById(R.id.idle_layout);
        statusText = findViewById(R.id.status_text);
        statusSpinner = findViewById(R.id.status_spinner);
        deviceInfoText = findViewById(R.id.device_info_text);

        try {
            Bitmap icon = BitmapFactory.decodeResource(getResources(), R.mipmap.ic_launcher);
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                setTaskDescription(new ActivityManager.TaskDescription("OpenDisplay", R.mipmap.ic_launcher, getColor(R.color.bg_dark)));
            } else {
                setTaskDescription(new ActivityManager.TaskDescription("OpenDisplay", icon, getResources().getColor(R.color.bg_dark)));
            }
        } catch (Exception ignored) {}

        updateDeviceInfo();

        surfaceView.getHolder().addCallback(new SurfaceHolder.Callback() {
            @Override
            public void surfaceCreated(SurfaceHolder holder) {
                Log.i(TAG, "Surface created, initializing H264Decoder and StreamReceiver");
                stopPipeline();
                try {
                    android.graphics.Point screen = getPhysicalScreenSize();
                    decoder = new H264Decoder(holder.getSurface(), screen.x, screen.y);
                    initReceiver();
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

                StreamReceiver currentReceiver = streamReceiver;
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
    }

    private android.graphics.Point getPhysicalScreenSize() {
        android.graphics.Point size = new android.graphics.Point();
        try {
            WindowManager wm = (WindowManager) getSystemService(Context.WINDOW_SERVICE);
            if (wm != null) {
                android.view.Display display = wm.getDefaultDisplay();
                display.getRealSize(size);
            }
        } catch (Exception ignored) {}
        if (size.x <= 0 || size.y <= 0) {
            android.util.DisplayMetrics dm = getResources().getDisplayMetrics();
            size.x = dm.widthPixels;
            size.y = dm.heightPixels;
        }
        int w = Math.max(size.x, size.y);
        int h = Math.min(size.x, size.y);
        return new android.graphics.Point(w, h);
    }

    private int getDisplayRefreshRate() {
        int rate = 60;
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                rate = (int) getDisplay().getRefreshRate();
            } else {
                WindowManager wm = (WindowManager) getSystemService(Context.WINDOW_SERVICE);
                if (wm != null) {
                    rate = (int) wm.getDefaultDisplay().getRefreshRate();
                }
            }
        } catch (Exception ignored) {}
        return (rate >= 30 && rate <= 240) ? rate : 60;
    }

    private void updateDeviceInfo() {
        if (deviceInfoText != null) {
            android.graphics.Point screen = getPhysicalScreenSize();
            int w = screen.x;
            int h = screen.y;
            int refreshRate = getDisplayRefreshRate();
            deviceInfoText.setText(String.format("Device Display: %d x %d @ %dHz | Ready", w, h, refreshRate));
        }
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        initWakeAndUnlock();
        if (intent != null && UsbManager.ACTION_USB_ACCESSORY_ATTACHED.equals(intent.getAction())) {
            Log.i(TAG, "USB_ACCESSORY_ATTACHED intent received in onNewIntent");
            initReceiver();
        }
    }

    private void initWakeAndUnlock() {
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            setShowWhenLocked(true);
            setTurnScreenOn(true);
            KeyguardManager km = (KeyguardManager) getSystemService(Context.KEYGUARD_SERVICE);
            if (km != null) {
                km.requestDismissKeyguard(this, null);
            }
        } else {
            getWindow().addFlags(
                WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED
                | WindowManager.LayoutParams.FLAG_DISMISS_KEYGUARD
                | WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON
            );
        }

        try {
            PowerManager pm = (PowerManager) getSystemService(Context.POWER_SERVICE);
            if (pm != null) {
                PowerManager.WakeLock wl = pm.newWakeLock(
                    PowerManager.FULL_WAKE_LOCK
                    | PowerManager.ACQUIRE_CAUSES_WAKEUP
                    | PowerManager.ON_AFTER_RELEASE,
                    "OpenDisplay:ScreenWake"
                );
                wl.acquire(2000);
            }
        } catch (Exception e) {
            Log.w(TAG, "WakeLock notice: " + e.getMessage());
        }
    }

    private synchronized void initReceiver() {
        if (streamReceiver != null) {
            try {
                streamReceiver.stopReceiver();
            } catch (Exception e) {
                Log.w(TAG, "Error stopping existing receiver: " + e.getMessage());
            }
            streamReceiver = null;
        }

        UsbManager usbManager = (UsbManager) getSystemService(Context.USB_SERVICE);
        UsbAccessory accessory = getIntent() != null ? (UsbAccessory) getIntent().getParcelableExtra(UsbManager.EXTRA_ACCESSORY) : null;
        if (accessory == null && usbManager != null) {
            UsbAccessory[] list = usbManager.getAccessoryList();
            if (list != null && list.length > 0) {
                accessory = list[0];
            }
        }

        if (accessory != null) {
            Log.i(TAG, "Opening StreamReceiver in AOAP Accessory mode");
            streamReceiver = new StreamReceiver(accessory, this, this);
        } else {
            Log.i(TAG, "Opening StreamReceiver in TCP mode (127.0.0.1:7070)");
            streamReceiver = new StreamReceiver(STREAM_HOST, STREAM_PORT, this);
        }

        if (decoder != null) {
            streamReceiver.setDecoder(decoder);
        }
        streamReceiver.start();
    }

    @Override
    public void onConnected() {
        Log.i(TAG, "StreamReceiver connected");
        // Handshake physical display resolution and refresh rate with host
        try {
            android.graphics.Point screen = getPhysicalScreenSize();
            int hz = getDisplayRefreshRate();
            if (streamReceiver != null) {
                streamReceiver.sendResolution(screen.x, screen.y, hz);
            }
        } catch (Exception ignored) {}

        runOnUiThread(new Runnable() {
            @Override
            public void run() {
                if (statusText != null) {
                    statusText.setText(R.string.status_connected);
                }
                if (statusSpinner != null) {
                    statusSpinner.setVisibility(View.GONE);
                }
                if (idleLayout != null) {
                    idleLayout.setVisibility(View.GONE);
                }
                isStreamingActive = true;
            }
        });
    }

    @Override
    public void onDisconnected() {
        Log.i(TAG, "StreamReceiver disconnected");
        runOnUiThread(new Runnable() {
            @Override
            public void run() {
                isStreamingActive = false;
                if (statusText != null) {
                    statusText.setText(R.string.status_reconnecting);
                }
                if (statusSpinner != null) {
                    statusSpinner.setVisibility(View.VISIBLE);
                }
                // Show idle dashboard overlay over the SurfaceView
                if (idleLayout != null) {
                    idleLayout.setVisibility(View.VISIBLE);
                }
            }
        });
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
        if (!isStreamingActive) {
            isStreamingActive = true;
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    if (idleLayout != null) {
                        idleLayout.setVisibility(View.GONE);
                    }
                }
            });
        }
        if (decoder != null && (streamReceiver == null || streamReceiver.getDecoder() == null)) {
            decoder.decodeFrame(payload, 0, payload.length, 0);
        }
    }

    @Override
    public void onImageFrame(byte[] payload) {
        if (!isStreamingActive) {
            isStreamingActive = true;
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    if (idleLayout != null) {
                        idleLayout.setVisibility(View.GONE);
                    }
                }
            });
        }
    }

    @Override
    protected void onPause() {
        super.onPause();
        isStreamingActive = false;
        if (idleLayout != null) {
            idleLayout.setVisibility(View.VISIBLE);
        }
    }

    @Override
    protected void onStart() {
        super.onStart();
        checkAndRestartPipeline();
    }

    @Override
    protected void onResume() {
        super.onResume();
        enableFullscreenImmersive();
        checkAndRestartPipeline();
    }

    @Override
    public void onBackPressed() {
        // Move task to back instead of terminating so user can reopen without cold restart
        moveTaskToBack(true);
    }

    private synchronized void checkAndRestartPipeline() {
        if (surfaceView != null) {
            SurfaceHolder holder = surfaceView.getHolder();
            Surface surface = holder != null ? holder.getSurface() : null;
            if (surface != null && surface.isValid()) {
                if (decoder == null || streamReceiver == null || !streamReceiver.isAlive()) {
                    Log.i(TAG, "checkAndRestartPipeline: Valid surface with inactive pipeline. Reconnecting...");
                    stopPipeline();
                    try {
                        android.graphics.Point screen = getPhysicalScreenSize();
                        decoder = new H264Decoder(surface, screen.x, screen.y);
                        initReceiver();
                    } catch (Exception e) {
                        Log.e(TAG, "Failed reconnecting pipeline: " + e.getMessage(), e);
                    }
                }
            }
        }
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
        if (streamReceiver != null) {
            try {
                streamReceiver.stopReceiver();
            } catch (Exception e) {
                Log.w(TAG, "Error stopping receiver: " + e.getMessage());
            }
            streamReceiver = null;
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
