package tn.carcheck.app;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.hardware.Camera;
import android.media.CamcorderProfile;
import android.media.MediaRecorder;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.Surface;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import java.io.File;
import java.util.List;

/**
 * Guided walk-around: big arrow + side to film + timer, so every employee films the same way.
 * Front -> right -> rear -> left -> inside + dashboard. "Finish" stays locked before 45 s.
 * No sound is recorded (no conversations captured).
 */
@SuppressWarnings("deprecation")   // android.hardware.Camera: simple and available on every phone
public class RecorderActivity extends Activity implements SurfaceHolder.Callback {
    static final String[] STEPS = {"AVANT", "CÔTÉ DROIT", "ARRIÈRE", "CÔTÉ GAUCHE", "INTÉRIEUR + COMPTEUR"};
    static final String[] HINTS = {
            "Face à la voiture : pare-choc, capot, pare-brise, plaque bien visible",
            "Longez le côté droit lentement : ailes, portes, jantes",
            "Pare-choc arrière, coffre, lunette, plaque arrière",
            "Longez le côté gauche lentement : portes, ailes, jantes",
            "Sièges, tableau de bord, compteur (contact mis)"};
    static final String[] ARROWS = {"⬆", "➡", "⬇", "⬅", "⟳"};
    static final int[] SECONDS = {15, 22, 15, 22, 12};          // ≈ 86 s au total
    static final int MIN_SECONDS = 45, MAX_SECONDS = 230;
    private static final int PERM = 7;

    private SurfaceView preview;
    private Camera camera;
    private int camId = 0;
    private int rotation = 0;
    private MediaRecorder recorder;
    private boolean recording;
    private boolean maxReached;     // the recorder already stopped by itself at MAX_SECONDS
    private long startMs, stepStartMs;
    private int step;
    private String outPath;
    private TextView stepView, hintView, arrowView, timerView;
    private Button mainBtn, nextBtn;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable tick = new Runnable() {
        @Override
        public void run() {
            updateUi();
            if (recording) handler.postDelayed(this, 250);
        }
    };

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON | WindowManager.LayoutParams.FLAG_FULLSCREEN);
        outPath = getIntent().getStringExtra("out");

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.BLACK);
        preview = new SurfaceView(this);
        root.addView(preview, new FrameLayout.LayoutParams(-1, -1));

        LinearLayout top = new LinearLayout(this);
        top.setOrientation(LinearLayout.VERTICAL);
        top.setBackgroundColor(0x99000000);
        int p = Ui.dp(this, 12);
        top.setPadding(p, p, p, p);
        stepView = Ui.text(this, "", 22, Color.WHITE);
        stepView.setTypeface(Typeface.DEFAULT_BOLD);
        hintView = Ui.text(this, "", 15, Color.parseColor("#E9EEF3"));
        top.addView(stepView);
        top.addView(hintView);
        root.addView(top, new FrameLayout.LayoutParams(-1, -2, Gravity.TOP));

        arrowView = Ui.text(this, "", 96, Color.parseColor("#F2B705"));
        arrowView.setShadowLayer(12, 0, 0, Color.BLACK);
        root.addView(arrowView, new FrameLayout.LayoutParams(-2, -2, Gravity.CENTER));

        LinearLayout bottom = new LinearLayout(this);
        bottom.setOrientation(LinearLayout.HORIZONTAL);
        bottom.setGravity(Gravity.CENTER_VERTICAL);
        bottom.setBackgroundColor(0x99000000);
        bottom.setPadding(p, p, p, p);
        timerView = Ui.text(this, "0:00", 26, Color.WHITE);
        timerView.setTypeface(Typeface.MONOSPACE);
        bottom.addView(timerView, new LinearLayout.LayoutParams(0, -2, 1));
        nextBtn = smallButton("Côté suivant ➜");
        nextBtn.setOnClickListener(v -> nextStep(true));
        bottom.addView(nextBtn);
        mainBtn = smallButton("● Démarrer");
        mainBtn.setBackground(Ui.box(this, Color.parseColor("#C92A2A"), Color.parseColor("#C92A2A")));
        mainBtn.setTextColor(Color.WHITE);
        mainBtn.setOnClickListener(v -> {
            if (!recording) startRecording();
            else stopRecording(true);
        });
        bottom.addView(mainBtn);
        root.addView(bottom, new FrameLayout.LayoutParams(-1, -2, Gravity.BOTTOM));
        setContentView(root);

        preview.getHolder().addCallback(this);
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.CAMERA}, PERM);
        }
        updateUi();
    }

    private Button smallButton(String s) {
        Button b = new Button(this);
        b.setText(s);
        b.setAllCaps(false);
        b.setTextSize(16);
        b.setTextColor(Ui.BRAND);
        b.setBackground(Ui.box(this, Color.WHITE, Color.WHITE));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-2, -2);
        lp.leftMargin = Ui.dp(this, 10);
        b.setLayoutParams(lp);
        b.setPadding(Ui.dp(this, 16), Ui.dp(this, 10), Ui.dp(this, 16), Ui.dp(this, 10));
        return b;
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] perms, int[] results) {
        if (code != PERM) return;
        if (results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED) {
            if (preview.getHolder().getSurface().isValid()) openCamera();
        } else {
            Toast.makeText(this, "Autorisez l’appareil photo pour filmer", Toast.LENGTH_LONG).show();
            finish();
        }
    }

    // ---------- camera ----------
    @Override
    public void surfaceCreated(SurfaceHolder holder) {
        if (checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) openCamera();
    }

    @Override
    public void surfaceChanged(SurfaceHolder holder, int format, int w, int h) { }

    @Override
    public void surfaceDestroyed(SurfaceHolder holder) {
        releaseCamera();
    }

    private void openCamera() {
        if (camera != null) return;
        try {
            Camera.CameraInfo info = new Camera.CameraInfo();
            for (int i = 0; i < Camera.getNumberOfCameras(); i++) {
                Camera.getCameraInfo(i, info);
                if (info.facing == Camera.CameraInfo.CAMERA_FACING_BACK) {
                    camId = i;
                    break;
                }
            }
            camera = Camera.open(camId);
            Camera.getCameraInfo(camId, info);
            int degrees = 0;
            switch (getWindowManager().getDefaultDisplay().getRotation()) {
                case Surface.ROTATION_90: degrees = 90; break;
                case Surface.ROTATION_180: degrees = 180; break;
                case Surface.ROTATION_270: degrees = 270; break;
                default: degrees = 0;
            }
            rotation = (info.orientation - degrees + 360) % 360;
            camera.setDisplayOrientation(rotation);
            Camera.Parameters params = camera.getParameters();
            List<String> modes = params.getSupportedFocusModes();
            if (modes != null && modes.contains(Camera.Parameters.FOCUS_MODE_CONTINUOUS_VIDEO)) {
                params.setFocusMode(Camera.Parameters.FOCUS_MODE_CONTINUOUS_VIDEO);
            }
            CamcorderProfile prof = profile();
            for (Camera.Size s : params.getSupportedPreviewSizes()) {
                if (s.width == prof.videoFrameWidth && s.height == prof.videoFrameHeight) {
                    params.setPreviewSize(s.width, s.height);
                    break;
                }
            }
            params.setRecordingHint(true);
            camera.setParameters(params);
            camera.setPreviewDisplay(preview.getHolder());
            camera.startPreview();
        } catch (Exception e) {
            Toast.makeText(this, "Caméra indisponible : " + e.getMessage(), Toast.LENGTH_LONG).show();
            releaseCamera();
            finish();
        }
    }

    private CamcorderProfile profile() {
        if (CamcorderProfile.hasProfile(camId, CamcorderProfile.QUALITY_720P)) {
            return CamcorderProfile.get(camId, CamcorderProfile.QUALITY_720P);   // net et léger à envoyer
        }
        return CamcorderProfile.get(camId, CamcorderProfile.QUALITY_HIGH);
    }

    private void releaseCamera() {
        if (camera != null) {
            try {
                camera.stopPreview();
            } catch (RuntimeException ignored) { }
            camera.release();
            camera = null;
        }
    }

    // ---------- recording ----------
    private void startRecording() {
        if (camera == null) return;
        try {
            CamcorderProfile prof = profile();
            camera.unlock();
            recorder = new MediaRecorder();
            recorder.setCamera(camera);
            recorder.setVideoSource(MediaRecorder.VideoSource.CAMERA);
            recorder.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4);
            recorder.setVideoEncoder(MediaRecorder.VideoEncoder.H264);
            recorder.setVideoSize(prof.videoFrameWidth, prof.videoFrameHeight);
            recorder.setVideoFrameRate(prof.videoFrameRate);
            recorder.setVideoEncodingBitRate(Math.min(prof.videoBitRate, 6000000));
            recorder.setOrientationHint(rotation);
            recorder.setMaxDuration(MAX_SECONDS * 1000);
            recorder.setOutputFile(outPath);
            recorder.setPreviewDisplay(preview.getHolder().getSurface());
            recorder.setOnInfoListener((mr, what, extra) -> {
                if (what == MediaRecorder.MEDIA_RECORDER_INFO_MAX_DURATION_REACHED) {
                    maxReached = true;
                    stopRecording(true);
                }
            });
            recorder.prepare();
            recorder.start();
        } catch (Exception e) {
            Toast.makeText(this, "Impossible de filmer : " + e.getMessage(), Toast.LENGTH_LONG).show();
            cleanRecorder();
            return;
        }
        recording = true;
        startMs = stepStartMs = System.currentTimeMillis();
        step = 0;
        handler.post(tick);
    }

    private void stopRecording(boolean keep) {
        if (!recording) return;
        long seconds = (System.currentTimeMillis() - startMs) / 1000;
        if (keep && seconds < MIN_SECONDS) return;
        recording = false;
        boolean saved = keep;
        if (!maxReached) {
            try {
                recorder.stop();
            } catch (RuntimeException e) {
                saved = false;                // nothing usable was written
            }
        }
        cleanRecorder();
        if (saved) {
            Intent data = new Intent();
            data.putExtra("seconds", seconds);
            data.putExtra("started_at", startMs / 1000.0);
            setResult(RESULT_OK, data);
        } else {
            new File(outPath).delete();
            setResult(RESULT_CANCELED);
        }
        finish();
    }

    private void cleanRecorder() {
        if (recorder != null) {
            recorder.reset();
            recorder.release();
            recorder = null;
        }
        if (camera != null) {
            try {
                camera.lock();
            } catch (RuntimeException ignored) { }
        }
    }

    private void nextStep(boolean manual) {
        if (!recording) return;
        long onStep = (System.currentTimeMillis() - stepStartMs) / 1000;
        if (manual && onStep < 6) {
            Toast.makeText(this, "Plus lentement : prenez le temps de bien montrer ce côté", Toast.LENGTH_SHORT).show();
        }
        if (step < STEPS.length - 1) {
            step++;
            stepStartMs = System.currentTimeMillis();
        }
        updateUi();
    }

    private void updateUi() {
        if (!recording) {
            stepView.setText("Tour guidé · 5 étapes · environ 1 min 30");
            hintView.setText("Téléphone à l’horizontale, à 1,5 m de la voiture. Commencez face à l’avant. Ne filmez pas les visages.");
            arrowView.setText("⬆");
            timerView.setText("0:00");
            nextBtn.setVisibility(View.GONE);
            mainBtn.setText("● Démarrer");
            return;
        }
        long now = System.currentTimeMillis();
        long total = (now - startMs) / 1000;
        long onStep = (now - stepStartMs) / 1000;
        if (onStep >= SECONDS[step] + 5 && step < STEPS.length - 1) {     // trop long sur ce côté : on avance
            step++;
            stepStartMs = now;
            onStep = 0;
        }
        stepView.setText((step + 1) + "/" + STEPS.length + " · " + STEPS[step]);
        long left = Math.max(0, SECONDS[step] - onStep);
        hintView.setText(HINTS[step] + (left > 0 ? "  (~" + left + " s)" : "  → côté suivant"));
        boolean blink = left == 0 && (now / 500) % 2 == 0;
        arrowView.setText(blink ? "" : ARROWS[step]);
        timerView.setText(String.format("%d:%02d", total / 60, total % 60));
        nextBtn.setVisibility(step < STEPS.length - 1 ? View.VISIBLE : View.GONE);
        if (total < MIN_SECONDS) {
            mainBtn.setText("Terminer (encore " + (MIN_SECONDS - total) + " s)");
            mainBtn.setEnabled(false);
            mainBtn.setAlpha(0.6f);
        } else {
            mainBtn.setText("■ Terminer");
            mainBtn.setEnabled(true);
            mainBtn.setAlpha(1f);
        }
    }

    @Override
    protected void onPause() {
        super.onPause();
        if (recording) stopRecording(false);   // l’employé a quitté l’écran : le film est abandonné
        releaseCamera();
    }

    @Override
    public void onBackPressed() {
        if (recording) stopRecording(false);
        else super.onBackPressed();
    }
}
