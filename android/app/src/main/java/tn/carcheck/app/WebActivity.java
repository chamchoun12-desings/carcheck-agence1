package tn.carcheck.app;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.ContentValues;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.MediaStore;
import android.text.InputType;
import android.webkit.HttpAuthHandler;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.Toast;

/** Shows the demo or the real server. Handles video filming/picking and the staff login. */
public class WebActivity extends Activity {
    private static final int FILE_REQUEST = 42;
    private WebView web;
    private ValueCallback<Uri[]> fileCallback;
    private Uri photoUri;   // where the camera writes a photo of the dashboard
    private int authTries;  // saved login first, then ask

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        web = new WebView(this);
        setContentView(web);
        // The app declares CAMERA (guided filming): Android then also requires it for camera intents.
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.CAMERA}, 3);
        }

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(true);

        final String start = getIntent().getStringExtra("url");
        final String startHost = start == null ? null : Uri.parse(start).getHost();

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
                Uri u = req.getUrl();
                String scheme = u.getScheme();
                boolean sameSite = "file".equals(scheme)
                        || (startHost != null && startHost.equals(u.getHost()));
                if (sameSite) return false;
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, u));   // wa.me, tel:, other sites
                } catch (ActivityNotFoundException e) {
                    Toast.makeText(WebActivity.this, "Aucune application pour ouvrir ce lien", Toast.LENGTH_SHORT).show();
                }
                return true;
            }

            @Override
            public void onReceivedHttpAuthRequest(WebView view, HttpAuthHandler handler, String host, String realm) {
                SharedPreferences p = getSharedPreferences("carcheck", MODE_PRIVATE);
                String pw = p.getString("pass", "");
                if (authTries++ == 0 && !pw.isEmpty()) {
                    handler.proceed(p.getString("user", "staff"), pw);   // identifiants de l’écran d’accueil
                } else {
                    askLogin(handler);
                }
            }

            @Override
            public void onReceivedError(WebView view, int code, String description, String failingUrl) {
                Toast.makeText(WebActivity.this,
                        "Serveur injoignable : " + description + ". Vérifiez l’adresse et le Wi-Fi.",
                        Toast.LENGTH_LONG).show();
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (fileCallback != null) fileCallback.onReceiveValue(null);
                fileCallback = callback;
                photoUri = null;

                boolean wantsImage = false;
                for (String t : params.getAcceptTypes()) {
                    if (t != null && t.startsWith("image")) wantsImage = true;
                }
                if (wantsImage) return choosePhoto();

                boolean camOk = checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED;
                Intent camera = new Intent(MediaStore.ACTION_VIDEO_CAPTURE);
                camera.putExtra(MediaStore.EXTRA_DURATION_LIMIT, 240);
                camera.putExtra(MediaStore.EXTRA_VIDEO_QUALITY, 1);

                Intent pick = new Intent(Intent.ACTION_GET_CONTENT);
                pick.addCategory(Intent.CATEGORY_OPENABLE);
                pick.setType("video/*");

                Intent chooser = Intent.createChooser(pick, "Vidéo du tour de la voiture");
                if (camOk) chooser.putExtra(Intent.EXTRA_INITIAL_INTENTS, new Intent[]{camera});
                try {
                    startActivityForResult(params.isCaptureEnabled() && camOk ? camera : chooser, FILE_REQUEST);
                } catch (ActivityNotFoundException | SecurityException e) {
                    try {
                        startActivityForResult(chooser, FILE_REQUEST);
                    } catch (ActivityNotFoundException e2) {
                        fileCallback = null;
                        return false;
                    }
                }
                return true;
            }
        });

        if (state != null) web.restoreState(state);
        else web.loadUrl(start);
    }

    /** Photo du compteur : appareil photo (Android 10+) ou galerie. */
    private boolean choosePhoto() {
        Intent pick = new Intent(Intent.ACTION_GET_CONTENT);
        pick.addCategory(Intent.CATEGORY_OPENABLE);
        pick.setType("image/*");
        Intent chooser = Intent.createChooser(pick, "Photo du compteur");
        if (Build.VERSION.SDK_INT >= 29
                && checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
            try {
                ContentValues v = new ContentValues();
                v.put(MediaStore.Images.Media.DISPLAY_NAME, "compteur_" + System.currentTimeMillis() + ".jpg");
                v.put(MediaStore.Images.Media.MIME_TYPE, "image/jpeg");
                photoUri = getContentResolver().insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, v);
                if (photoUri != null) {
                    Intent camera = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
                    camera.putExtra(MediaStore.EXTRA_OUTPUT, photoUri);
                    camera.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
                    chooser.putExtra(Intent.EXTRA_INITIAL_INTENTS, new Intent[]{camera});
                }
            } catch (Exception ignored) {
                photoUri = null;
            }
        }
        try {
            startActivityForResult(chooser, FILE_REQUEST);
            return true;
        } catch (ActivityNotFoundException e) {
            fileCallback = null;
            return false;
        }
    }

    private void askLogin(HttpAuthHandler handler) {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        int p = Math.round(20 * getResources().getDisplayMetrics().density);
        box.setPadding(p, p / 2, p, 0);
        EditText user = new EditText(this);
        user.setHint("Utilisateur");
        user.setText("staff");
        EditText pass = new EditText(this);
        pass.setHint("Mot de passe");
        pass.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        box.addView(user);
        box.addView(pass);
        new AlertDialog.Builder(this)
                .setTitle("Connexion employé")
                .setView(box)
                .setCancelable(false)
                .setPositiveButton("Se connecter", (d, w) ->
                        handler.proceed(user.getText().toString(), pass.getText().toString()))
                .setNegativeButton("Annuler", (d, w) -> handler.cancel())
                .show();
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode != FILE_REQUEST) {
            super.onActivityResult(requestCode, resultCode, data);
            return;
        }
        if (fileCallback == null) return;
        Uri[] result = WebChromeClient.FileChooserParams.parseResult(resultCode, data);
        if (result == null && resultCode == RESULT_OK && data != null && data.getData() != null) {
            result = new Uri[]{data.getData()};
        }
        if (result == null && resultCode == RESULT_OK && photoUri != null) {
            result = new Uri[]{photoUri};          // the camera wrote the photo here
        } else if (photoUri != null) {
            // gallery chosen or cancelled: remove the empty camera placeholder
            try { getContentResolver().delete(photoUri, null, null); } catch (Exception ignored) { }
        }
        photoUri = null;
        fileCallback.onReceiveValue(result);
        fileCallback = null;
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        web.saveState(out);
    }

    @Override
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }
}
