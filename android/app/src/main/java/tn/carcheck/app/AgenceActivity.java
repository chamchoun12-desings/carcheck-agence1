package tn.carcheck.app;

import android.Manifest;
import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.ContentValues;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.MediaStore;
import android.util.Base64;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.BufferedOutputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;

/**
 * L'application agence : la page agence.html (dans l'APK) + un pont natif « CC » :
 *  - requêtes vers le serveur avec l'identifiant de l'employé (gardées pour le hors ligne),
 *  - tournage guidé (RecorderActivity), photos (compteur, permis) gardées dans l'application,
 *  - envoi d'une sortie ou d'un retour par la file d'attente (part tout seul quand le réseau revient).
 */
public class AgenceActivity extends Activity {
    private static final int REQ_FILM = 11, REQ_PHOTO = 12, PERM = 13;
    private WebView web;
    private SharedPreferences prefs;
    private boolean pageReady;
    private final List<String> pendingJs = new ArrayList<>();
    private String photoKey, photoName, filmKey;
    private Uri photoUri;
    private volatile boolean sending;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setStatusBarColor(Ui.BRAND);
        prefs = getSharedPreferences("carcheck", MODE_PRIVATE);
        if (state != null) {
            photoKey = state.getString("photoKey");
            photoName = state.getString("photoName");
            filmKey = state.getString("filmKey");
            String u = state.getString("photoUri");
            if (u != null) photoUri = Uri.parse(u);
        }
        Store.cleanup(this);
        web = new WebView(this);
        setContentView(web);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(true);
        web.addJavascriptInterface(new Bridge(), "CC");
        web.setWebChromeClient(new WebChromeClient());
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
                Uri u = req.getUrl();
                if ("file".equals(u.getScheme())) return false;
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, u));      // wa.me, tel:, autres sites
                } catch (ActivityNotFoundException e) {
                    toast("Aucune application pour ouvrir ce lien");
                }
                return true;
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                pageReady = true;
                for (String js : pendingJs) web.evaluateJavascript(js, null);
                pendingJs.clear();
            }
        });
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.CAMERA}, PERM);
        }
        web.loadUrl("file:///android_asset/agence.html");
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        out.putString("photoKey", photoKey);
        out.putString("photoName", photoName);
        out.putString("filmKey", filmKey);
        if (photoUri != null) out.putString("photoUri", photoUri.toString());
    }

    @Override
    protected void onResume() {
        super.onResume();
        js("window.ccResume&&window.ccResume()");
        sendQueue();
    }

    /** Contrôles enregistrés hors ligne : envoi automatique dès que le serveur répond. */
    private void sendQueue() {
        if (sending || Store.items(this).length == 0) return;
        sending = true;
        new Thread(() -> {
            Uploader.sendAll(this, false);
            sending = false;
            js("window.ccResume&&window.ccResume()");
        }).start();
    }

    @Override
    public void onBackPressed() {
        web.evaluateJavascript("window.ccBack?window.ccBack():false", v -> {
            if (!"true".equals(v)) finish();
        });
    }

    private void toast(String m) {
        runOnUiThread(() -> Toast.makeText(this, m, Toast.LENGTH_LONG).show());
    }

    /** Exécute du JavaScript dans la page (sur le fil de l'interface, après le chargement). */
    private void js(String code) {
        runOnUiThread(() -> {
            if (pageReady) web.evaluateJavascript(code, null);
            else pendingJs.add(code);
        });
    }

    private static String q(String s) {
        return JSONObject.quote(s == null ? "" : s);
    }

    private File item(String key) {
        if (key == null || !key.matches("c[0-9]+")) return null;
        File d = new File(Store.queueDir(this), key);
        return d.isDirectory() ? d : null;
    }

    // ---------- HTTP ----------
    static final class Resp {
        int code;
        byte[] body = new byte[0];
        String type = "";
    }

    private String server() {
        return prefs.getString("server", "").trim().replaceAll("/+$", "");
    }

    private HttpURLConnection open(String path, String method) throws IOException {
        HttpURLConnection con = (HttpURLConnection) new URL(server() + path).openConnection();
        con.setRequestMethod(method);
        con.setConnectTimeout(15000);
        con.setReadTimeout(90000);
        String login = prefs.getString("user", "") + ":" + prefs.getString("pass", "");
        con.setRequestProperty("Authorization", "Basic "
                + Base64.encodeToString(login.getBytes(StandardCharsets.UTF_8), Base64.NO_WRAP));
        return con;
    }

    private static Resp read(HttpURLConnection con) throws IOException {
        Resp r = new Resp();
        r.code = con.getResponseCode();
        r.type = con.getContentType() == null ? "" : con.getContentType();
        InputStream in = r.code < 400 ? con.getInputStream() : con.getErrorStream();
        if (in != null) {
            ByteArrayOutputStream b = new ByteArrayOutputStream();
            byte[] buf = new byte[16384];
            int n;
            while ((n = in.read(buf)) > 0) b.write(buf, 0, n);
            in.close();
            r.body = b.toByteArray();
        }
        return r;
    }

    private File cacheFile(String path) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-1");
            StringBuilder sb = new StringBuilder();
            for (byte x : md.digest((prefs.getString("user", "") + path).getBytes(StandardCharsets.UTF_8))) {
                sb.append(String.format("%02x", x));
            }
            File d = new File(getFilesDir(), "cache");
            d.mkdirs();
            return new File(d, sb + ".json");
        } catch (Exception e) {
            return new File(getFilesDir(), "cache.json");
        }
    }

    private static void write(File f, byte[] data) {
        try (OutputStream o = new FileOutputStream(f)) {
            o.write(data);
        } catch (IOException ignored) {
            // le cache n'est qu'une aide pour le hors ligne
        }
    }

    private static byte[] readFile(File f) throws IOException {
        try (InputStream in = new FileInputStream(f)) {
            ByteArrayOutputStream b = new ByteArrayOutputStream();
            byte[] buf = new byte[16384];
            int n;
            while ((n = in.read(buf)) > 0) b.write(buf, 0, n);
            return b.toByteArray();
        }
    }

    /** Petite image (environ 640 px) pour l'afficher dans la page. */
    private static String thumb(File f) {
        BitmapFactory.Options o = new BitmapFactory.Options();
        o.inJustDecodeBounds = true;
        BitmapFactory.decodeFile(f.getAbsolutePath(), o);
        int sample = 1;
        while (Math.max(o.outWidth, o.outHeight) / (sample * 2) >= 640) sample *= 2;
        BitmapFactory.Options o2 = new BitmapFactory.Options();
        o2.inSampleSize = sample;
        Bitmap bm = BitmapFactory.decodeFile(f.getAbsolutePath(), o2);
        if (bm == null) return "";
        ByteArrayOutputStream b = new ByteArrayOutputStream();
        bm.compress(Bitmap.CompressFormat.JPEG, 70, b);
        bm.recycle();
        return "data:image/jpeg;base64," + Base64.encodeToString(b.toByteArray(), Base64.NO_WRAP);
    }

    // ---------- caméra ----------
    private void startPhoto(String key, String name) {
        photoKey = key;
        photoName = name;
        photoUri = null;
        Intent pick = new Intent(Intent.ACTION_GET_CONTENT);
        pick.addCategory(Intent.CATEGORY_OPENABLE);
        pick.setType("image/*");
        Intent chooser = Intent.createChooser(pick, "dash".equals(name) ? "Photo du compteur" : "Photo du permis");
        if (Build.VERSION.SDK_INT >= 29 && checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
            try {
                ContentValues v = new ContentValues();
                v.put(MediaStore.Images.Media.DISPLAY_NAME, "carcheck_" + System.currentTimeMillis() + ".jpg");
                v.put(MediaStore.Images.Media.MIME_TYPE, "image/jpeg");
                photoUri = getContentResolver().insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, v);
                if (photoUri != null) {
                    Intent cam = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
                    cam.putExtra(MediaStore.EXTRA_OUTPUT, photoUri);
                    cam.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
                    chooser.putExtra(Intent.EXTRA_INITIAL_INTENTS, new Intent[]{cam});
                }
            } catch (Exception e) {
                photoUri = null;
            }
        }
        try {
            startActivityForResult(chooser, REQ_PHOTO);
        } catch (ActivityNotFoundException e) {
            toast("Aucune application photo");
        }
    }

    @Override
    protected void onActivityResult(int req, int res, Intent data) {
        super.onActivityResult(req, res, data);
        if (req == REQ_FILM) {
            File it = item(filmKey);
            boolean ok = res == RESULT_OK && data != null && it != null && new File(it, "walk.mp4").length() > 0;
            long secs = ok ? data.getLongExtra("seconds", 0) : 0;
            if (ok) {
                try {
                    JSONObject f = new JSONObject();
                    f.put("started_at", data.getDoubleExtra("started_at", 0));
                    f.put("seconds", secs);
                    write(new File(it, "film.json"), f.toString().getBytes(StandardCharsets.UTF_8));
                } catch (JSONException ignored) {
                    // l'heure du téléphone sera celle du fichier
                }
            }
            js("window.ccFilmed(" + q(filmKey) + "," + ok + "," + secs + ")");
        } else if (req == REQ_PHOTO) {
            final String key = photoKey, name = photoName;
            final Uri cam = photoUri;
            final Uri src = res == RESULT_OK ? (data != null && data.getData() != null ? data.getData() : cam) : null;
            photoUri = null;
            new Thread(() -> {
                File it = item(key);
                boolean ok = false;
                String th = "";
                if (src != null && it != null && name != null && name.matches("dash|license")) {
                    try {
                        File dst = new File(it, name + ".jpg");
                        Store.copy(this, src, dst);
                        ok = dst.length() > 0;
                        th = ok ? thumb(dst) : "";
                    } catch (IOException e) {
                        toast("Photo illisible : recommencez");
                    }
                }
                if (cam != null) {
                    try {
                        getContentResolver().delete(cam, null, null);   // pas de copie dans la galerie
                    } catch (Exception ignored) { }
                }
                js("window.ccPhoto(" + q(key) + "," + q(name) + "," + ok + "," + q(th) + ")");
            }).start();
        }
    }

    /** Ce que la page peut demander au téléphone. Appelé depuis un autre fil : rien de bloquant ici. */
    final class Bridge {
        @JavascriptInterface
        public void request(String id, String method, String path, String body) {
            new Thread(() -> {
                String text = "";
                int code = 0;
                boolean cached = false;
                File cache = cacheFile(path);
                try {
                    HttpURLConnection con = open(path, "POST".equals(method) ? "POST" : "GET");
                    if ("POST".equals(method)) {
                        StringBuilder form = new StringBuilder();
                        if (body != null && !body.isEmpty()) {
                            JSONObject o = new JSONObject(body);
                            for (Iterator<String> it = o.keys(); it.hasNext(); ) {
                                String k = it.next();
                                if (form.length() > 0) form.append('&');
                                form.append(URLEncoder.encode(k, "UTF-8")).append('=')
                                        .append(URLEncoder.encode(o.optString(k, ""), "UTF-8"));
                            }
                        }
                        byte[] b = form.toString().getBytes(StandardCharsets.UTF_8);
                        con.setDoOutput(true);
                        con.setRequestProperty("Content-Type", "application/x-www-form-urlencoded");
                        con.setFixedLengthStreamingMode(b.length);
                        try (OutputStream o = con.getOutputStream()) {
                            o.write(b);
                        }
                    }
                    Resp r = read(con);
                    con.disconnect();
                    code = r.code;
                    text = new String(r.body, StandardCharsets.UTF_8);
                    if (!"POST".equals(method) && code == 200) write(cache, r.body);
                } catch (IOException | JSONException e) {
                    if (!"POST".equals(method) && cache.exists()) {
                        try {
                            text = new String(readFile(cache), StandardCharsets.UTF_8);
                            code = 200;
                            cached = true;
                        } catch (IOException ignored) {
                            code = 0;
                        }
                    }
                }
                js("window.ccDone(" + q(id) + "," + code + "," + q(text) + "," + cached + ")");
            }).start();
        }

        @JavascriptInterface
        public void image(String id, String path) {
            new Thread(() -> {
                String url = "";
                try {
                    HttpURLConnection con = open(path, "GET");
                    Resp r = read(con);
                    con.disconnect();
                    if (r.code == 200) {
                        String type = r.type.isEmpty() ? "image/jpeg" : r.type.split(";")[0];
                        url = "data:" + type + ";base64," + Base64.encodeToString(r.body, Base64.NO_WRAP);
                    }
                } catch (IOException ignored) {
                    // image absente : la page affiche un cadre vide
                }
                js("window.ccDone(" + q(id) + "," + (url.isEmpty() ? 0 : 200) + "," + q(url) + ",false)");
            }).start();
        }

        @JavascriptInterface
        public String newItem() {
            return Store.newItem(AgenceActivity.this).getName();
        }

        @JavascriptInterface
        public void film(String key) {
            runOnUiThread(() -> {
                File it = item(key);
                if (it == null) return;
                filmKey = key;
                new File(it, "walk.mp4").delete();
                Intent i = new Intent(AgenceActivity.this, RecorderActivity.class);
                i.putExtra("out", new File(it, "walk.mp4").getAbsolutePath());
                startActivityForResult(i, REQ_FILM);
            });
        }

        @JavascriptInterface
        public void photo(String key, String name) {
            runOnUiThread(() -> startPhoto(key, name));
        }

        /** Envoi immédiat (en ligne seulement) de photos de la sortie en cours, ex. lecture du compteur. */
        @JavascriptInterface
        public void post(String id, String path, String key, String filesJson, String fieldsJson) {
            new Thread(() -> {
                int code = 0;
                String text = "";
                File it = item(key);
                String b = "----carcheck" + System.currentTimeMillis();
                try {
                    if (it == null) throw new IOException("item");
                    JSONObject files = new JSONObject(filesJson), fields = new JSONObject(fieldsJson);
                    HttpURLConnection con = open(path, "POST");
                    con.setDoOutput(true);
                    con.setChunkedStreamingMode(64 * 1024);
                    con.setRequestProperty("Content-Type", "multipart/form-data; boundary=" + b);
                    try (OutputStream out = new BufferedOutputStream(con.getOutputStream())) {
                        for (Iterator<String> k = fields.keys(); k.hasNext(); ) {
                            String n = k.next();
                            Uploader.field(out, b, n, fields.optString(n, ""));
                        }
                        for (Iterator<String> k = files.keys(); k.hasNext(); ) {
                            String n = k.next();
                            Uploader.file(out, b, n, new File(it, files.optString(n)), "image/jpeg");
                        }
                        out.write(("--" + b + "--\r\n").getBytes(StandardCharsets.UTF_8));
                    }
                    Resp r = read(con);
                    con.disconnect();
                    code = r.code;
                    text = new String(r.body, StandardCharsets.UTF_8);
                } catch (IOException | JSONException e) {
                    code = 0;
                }
                js("window.ccDone(" + q(id) + "," + code + "," + q(text) + ",false)");
            }).start();
        }

        /** Fin de l'assistant : tout est gardé dans le téléphone, puis envoyé (maintenant ou plus tard). */
        @JavascriptInterface
        public void submit(String key, String fieldsJson) {
            new Thread(() -> {
                File it = item(key);
                String state = "refused", message = "", body = "";
                try {
                    if (it == null) throw new IOException("contrôle introuvable dans le téléphone");
                    File video = new File(it, "walk.mp4");
                    if (video.length() == 0) throw new IOException("vidéo manquante : filmez de nouveau");
                    JSONObject fields = new JSONObject(fieldsJson);
                    double started = 0;
                    File fj = new File(it, "film.json");
                    if (fj.exists()) {
                        started = new JSONObject(new String(readFile(fj), StandardCharsets.UTF_8)).optDouble("started_at", 0);
                    }
                    if (started <= 0) started = video.lastModified() / 1000.0;
                    fields.put("recorded_at", String.valueOf(started));
                    fields.put("phone_sha256", Store.sha256(video));       // empreinte calculée dans le téléphone
                    JSONObject files = new JSONObject();
                    files.put("video", "walk.mp4");
                    if (new File(it, "dash.jpg").exists()) files.put("dash", "dash.jpg");
                    if (new File(it, "license.jpg").exists() && "out".equals(fields.optString("kind"))) files.put("license", "license.jpg");
                    JSONObject meta = new JSONObject();
                    meta.put("endpoint", "/api/a/checks");
                    meta.put("fields", fields);
                    meta.put("files", files);
                    meta.put("car", fields.optString("car"));
                    meta.put("kind", fields.optString("kind"));
                    meta.put("recorded_at", String.valueOf(started));
                    meta.put("status", "waiting");
                    meta.put("created", System.currentTimeMillis());
                    Store.writeMeta(it, meta);
                    Uploader.Result r = Uploader.sendOne(AgenceActivity.this, it);
                    state = r.ok ? "sent" : r.refused ? "refused" : "queued";
                    message = r.message;
                    body = r.body;
                    if (r.refused) new File(it, "meta.json").delete();   // la page montre l'erreur : l'employé corrige et renvoie
                } catch (IOException | JSONException e) {
                    message = e.getMessage();
                }
                js("window.ccSubmitted(" + q(key) + "," + q(state) + "," + q(message) + "," + q(body) + ")");
            }).start();
        }

        @JavascriptInterface
        public void discard(String key) {
            File it = item(key);
            if (it != null && !new File(it, "meta.json").exists()) Store.deleteDir(it);
        }

        @JavascriptInterface
        public int queueCount() {
            return Store.items(AgenceActivity.this).length;
        }

        @JavascriptInterface
        public void openQueue() {
            runOnUiThread(() -> startActivity(new Intent(AgenceActivity.this, QueueActivity.class)));
        }

        @JavascriptInterface
        public void settings() {
            runOnUiThread(() -> {
                Intent i = new Intent(AgenceActivity.this, MainActivity.class);
                i.putExtra("settings", true);
                startActivity(i);
                finish();
            });
        }

        @JavascriptInterface
        public void openServer(String path) {
            runOnUiThread(() -> {
                Intent i = new Intent(AgenceActivity.this, WebActivity.class);
                i.putExtra("url", server() + (path.startsWith("/") ? path : "/" + path));
                startActivity(i);
            });
        }
    }
}
