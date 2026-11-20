package tn.carcheck.app;

import android.content.Context;
import android.net.Uri;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Arrays;

/**
 * Offline queue: each check waits in its own folder inside the app (private storage)
 *   files/queue/c1731920000000/meta.json, walk.mp4, dashboard.jpg, signature.png, license.jpg
 * until the server accepts it. Then the folder is deleted.
 */
final class Store {
    private Store() { }

    static File queueDir(Context c) {
        File d = new File(c.getFilesDir(), "queue");
        if (!d.exists()) d.mkdirs();
        return d;
    }

    static File newItem(Context c) {
        File d = new File(queueDir(c), "c" + System.currentTimeMillis());
        d.mkdirs();
        return d;
    }

    /** Items that are complete (meta.json written), oldest first. */
    static File[] items(Context c) {
        File[] all = queueDir(c).listFiles();
        if (all == null) return new File[0];
        int n = 0;
        File[] ok = new File[all.length];
        for (File f : all) {
            if (f.isDirectory() && new File(f, "meta.json").exists()) ok[n++] = f;
        }
        File[] out = Arrays.copyOf(ok, n);
        Arrays.sort(out);
        return out;
    }

    /** Removes unfinished checks (no meta.json) older than one day: abandoned or interrupted. */
    static void cleanup(Context c) {
        File[] all = queueDir(c).listFiles();
        if (all == null) return;
        long limit = System.currentTimeMillis() - 86400000L;
        for (File f : all) {
            if (f.isDirectory() && !new File(f, "meta.json").exists() && f.lastModified() < limit) deleteDir(f);
        }
    }

    static JSONObject readMeta(File item) {
        try (InputStream in = new FileInputStream(new File(item, "meta.json"))) {
            return new JSONObject(readAll(in));
        } catch (IOException | JSONException e) {
            return new JSONObject();
        }
    }

    static void writeMeta(File item, JSONObject meta) throws IOException {
        File tmp = new File(item, "meta.json.tmp");
        try (OutputStream out = new FileOutputStream(tmp)) {
            out.write(meta.toString().getBytes(StandardCharsets.UTF_8));
        }
        if (!tmp.renameTo(new File(item, "meta.json"))) throw new IOException("meta.json");
    }

    static String sha256(File f) throws IOException {
        MessageDigest md;
        try {
            md = MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException e) {
            throw new IOException(e);
        }
        byte[] buf = new byte[64 * 1024];
        try (InputStream in = new FileInputStream(f)) {
            int n;
            while ((n = in.read(buf)) > 0) md.update(buf, 0, n);
        }
        StringBuilder sb = new StringBuilder();
        for (byte b : md.digest()) sb.append(String.format("%02x", b));
        return sb.toString();
    }

    static void copy(Context c, Uri from, File to) throws IOException {
        try (InputStream in = c.getContentResolver().openInputStream(from);
             OutputStream out = new FileOutputStream(to)) {
            if (in == null) throw new IOException("fichier introuvable");
            byte[] buf = new byte[64 * 1024];
            int n;
            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
        }
    }

    static String readAll(InputStream in) throws IOException {
        ByteArrayOutputStream b = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int n;
        while ((n = in.read(buf)) > 0) b.write(buf, 0, n);
        return new String(b.toByteArray(), StandardCharsets.UTF_8);
    }

    static void deleteDir(File d) {
        File[] kids = d.listFiles();
        if (kids != null) for (File k : kids) {
            if (k.isDirectory()) deleteDir(k);
            else k.delete();
        }
        d.delete();
    }
}
