package tn.carcheck.app;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Base64;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.BufferedOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Iterator;

/** Sends one queued check to the server (POST /api/upload, multipart, staff login). Never on the UI thread. */
final class Uploader {
    static final class Result {
        boolean ok;          // accepted: the folder can be deleted
        boolean refused;     // the server said no (plate, expired licence...): needs a fix, not a retry
        String message = "";
        String body = "";    // réponse du serveur (JSON)
    }

    private Uploader() { }

    static Result upload(Context ctx, File item) {
        Result r = new Result();
        SharedPreferences p = ctx.getSharedPreferences("carcheck", Context.MODE_PRIVATE);
        String server = p.getString("server", "").trim().replaceAll("/+$", "");
        if (!server.startsWith("http")) {
            r.message = "Adresse du serveur non réglée (écran d’accueil)";
            return r;
        }
        JSONObject meta = Store.readMeta(item);
        String boundary = "----carcheck" + System.currentTimeMillis();
        HttpURLConnection con = null;
        try {
            String endpoint = meta.optString("endpoint", "/api/upload");
            if (!endpoint.startsWith("/api/")) endpoint = "/api/upload";
            con = (HttpURLConnection) new URL(server + endpoint).openConnection();
            con.setDoOutput(true);
            con.setRequestMethod("POST");
            con.setConnectTimeout(15000);
            con.setReadTimeout(300000);
            con.setChunkedStreamingMode(64 * 1024);     // the video is streamed, not loaded in memory
            con.setRequestProperty("Content-Type", "multipart/form-data; boundary=" + boundary);
            String login = p.getString("user", "staff") + ":" + p.getString("pass", "");
            con.setRequestProperty("Authorization", "Basic "
                    + Base64.encodeToString(login.getBytes(StandardCharsets.UTF_8), Base64.NO_WRAP));
            try (OutputStream out = new BufferedOutputStream(con.getOutputStream())) {
                JSONObject fields = meta.optJSONObject("fields");
                JSONObject files = meta.optJSONObject("files");
                if (fields != null && files != null) {
                    // nouvelle application : champs et fichiers décrits dans meta.json
                    fields.put("car", meta.optString("car", fields.optString("car")));   // plaque corrigée dans « À envoyer »
                    for (Iterator<String> it = fields.keys(); it.hasNext(); ) {
                        String k = it.next();
                        field(out, boundary, k, fields.optString(k, ""));
                    }
                    for (Iterator<String> it = files.keys(); it.hasNext(); ) {
                        String k = it.next();
                        String name = files.optString(k);
                        file(out, boundary, k, new File(item, name), name.endsWith(".mp4") ? "video/mp4" : "image/jpeg");
                    }
                } else {
                    for (String k : new String[]{"car", "kind", "client_phone", "client_name", "client_lang", "license_expiry", "recorded_at", "phone_sha256"}) {
                        field(out, boundary, k, meta.optString(k, ""));
                    }
                    file(out, boundary, "video", new File(item, "walk.mp4"), "video/mp4");
                    file(out, boundary, "dash", new File(item, "dashboard.jpg"), "image/jpeg");
                    file(out, boundary, "signature", new File(item, "signature.png"), "image/png");
                    file(out, boundary, "license", new File(item, "license.jpg"), "image/jpeg");
                }
                out.write(("--" + boundary + "--\r\n").getBytes(StandardCharsets.UTF_8));
            }
            int code = con.getResponseCode();
            InputStream is = code < 400 ? con.getInputStream() : con.getErrorStream();
            String body = is == null ? "" : Store.readAll(is);
            r.body = body;
            if (code == 200) {
                JSONObject j = new JSONObject(body);
                r.ok = j.optBoolean("ok");
                r.message = "Envoyé : " + j.optString("car") + " · " + j.optString("server_time");
                if (!r.ok) {
                    r.refused = true;
                    r.message = j.optString("error", "refusé par le serveur");
                }
            } else if (code == 422) {
                r.refused = true;
                r.message = new JSONObject(body).optString("error", "refusé par le serveur");
            } else if (code == 401) {
                r.message = "Identifiant ou mot de passe refusé (écran d’accueil)";
            } else {
                r.message = "Erreur du serveur (" + code + ") : nouvel essai plus tard";
            }
        } catch (IOException e) {
            r.message = "Pas de connexion au serveur : sera envoyé plus tard";
        } catch (JSONException e) {
            r.message = "Réponse du serveur illisible : vérifiez l’adresse";
        } finally {
            if (con != null) con.disconnect();
        }
        return r;
    }

    static void field(OutputStream out, String b, String name, String value) throws IOException {
        out.write(("--" + b + "\r\nContent-Disposition: form-data; name=\"" + name + "\"\r\n\r\n")
                .getBytes(StandardCharsets.UTF_8));
        out.write(value.getBytes(StandardCharsets.UTF_8));
        out.write("\r\n".getBytes(StandardCharsets.UTF_8));
    }

    static void file(OutputStream out, String b, String name, File f, String type) throws IOException {
        if (!f.exists()) return;
        out.write(("--" + b + "\r\nContent-Disposition: form-data; name=\"" + name + "\"; filename=\""
                + f.getName() + "\"\r\nContent-Type: " + type + "\r\n\r\n").getBytes(StandardCharsets.UTF_8));
        byte[] buf = new byte[64 * 1024];
        try (InputStream in = new FileInputStream(f)) {
            int n;
            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
        }
        out.write("\r\n".getBytes(StandardCharsets.UTF_8));
    }

    /** Sends one check. Accepted: folder deleted. Otherwise the reason is written in its meta.json. */
    static Result sendOne(Context ctx, File item) {
        Result r = upload(ctx, item);
        if (r.ok) {
            Store.deleteDir(item);
            return r;
        }
        JSONObject meta = Store.readMeta(item);
        try {
            meta.put("status", r.refused ? "refused" : "waiting");
            meta.put("error", r.message);
            Store.writeMeta(item, meta);
        } catch (JSONException | IOException ignored) {
            // the item stays in the queue anyway
        }
        return r;
    }

    /** Sends every waiting check (not the ones refused by the server: they need a fix first). */
    static String sendAll(Context ctx, boolean includeRefused) {
        int sent = 0, waiting = 0, fix = 0;
        for (File item : Store.items(ctx)) {
            if (!includeRefused && "refused".equals(Store.readMeta(item).optString("status"))) {
                fix++;
                continue;
            }
            Result r = sendOne(ctx, item);
            if (r.ok) sent++;
            else if (r.refused) fix++;
            else waiting++;
        }
        StringBuilder s = new StringBuilder();
        if (sent > 0) s.append(sent).append(" envoyé(s). ");
        if (waiting > 0) s.append(waiting).append(" en attente de connexion. ");
        if (fix > 0) s.append(fix).append(" à corriger. ");
        return s.length() == 0 ? "Rien à envoyer." : s.toString().trim();
    }
}
