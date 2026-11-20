package tn.carcheck.app;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Bundle;
import android.text.InputType;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

/**
 * Premier écran : adresse du serveur, identifiant et mot de passe de l'employé (une seule fois).
 * Ensuite l'application s'ouvre directement sur l'accueil agence (AgenceActivity).
 */
public class MainActivity extends Activity {
    private static final int ID_URL = 2001, ID_USER = 2002, ID_PASS = 2003;
    private SharedPreferences prefs;
    private EditText url, user, pass;
    private TextView queueInfo;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        prefs = getSharedPreferences("carcheck", MODE_PRIVATE);
        if (!getIntent().getBooleanExtra("settings", false) && configured()) {
            startActivity(new Intent(this, AgenceActivity.class));
            finish();
            return;
        }
        getWindow().setStatusBarColor(Ui.BRAND);
        LinearLayout col = Ui.column(this);
        col.addView(Ui.title(this, "Car Check · Agence"));
        col.addView(Ui.text(this, "Réglage à faire une seule fois par téléphone · يتمّ هذا الإعداد مرّة واحدة", 15, Ui.MUTE));
        col.addView(Ui.space(this, 20));

        col.addView(Ui.label(this, "Adresse du serveur · عنوان الخادم"));
        col.addView(Ui.text(this, "Exemple : https://carcheck.mon-agence.tn  (test sur le Wi-Fi : http://IP-du-PC:8000)", 13, Ui.MUTE));
        url = Ui.input(this, "https://…", InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI, ID_URL);
        url.setText(prefs.getString("server", ""));
        col.addView(url);
        col.addView(Ui.space(this, 12));
        col.addView(Ui.label(this, "Identifiant · اسم المستخدم"));
        user = Ui.input(this, "ahmed", InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD, ID_USER);
        user.setText(prefs.getString("user", ""));
        col.addView(user);
        col.addView(Ui.space(this, 12));
        col.addView(Ui.label(this, "Mot de passe · كلمة السرّ"));
        pass = Ui.input(this, "••••••••", InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD, ID_PASS);
        pass.setText(prefs.getString("pass", ""));
        col.addView(pass);
        col.addView(Ui.space(this, 18));

        Button go = Ui.button(this, "Ouvrir l’application · فتح التطبيق", true);
        go.setOnClickListener(v -> {
            if (!saveSettings()) return;
            startActivity(new Intent(this, AgenceActivity.class));
            finish();
        });
        col.addView(go);
        Button queue = Ui.button(this, "Contrôles à envoyer · في انتظار الإرسال", false);
        queue.setOnClickListener(v -> startActivity(new Intent(this, QueueActivity.class)));
        col.addView(queue);
        queueInfo = Ui.text(this, "", 13, Ui.MUTE);
        col.addView(queueInfo);
        col.addView(Ui.space(this, 18));

        col.addView(Ui.label(this, "Autres · أخرى"));
        Button booking = Ui.button(this, "Page client « Réserver »", false);
        booking.setOnClickListener(v -> {
            if (saveSettings()) open(prefs.getString("server", "") + "/reserver");
        });
        col.addView(booking);
        Button demo = Ui.button(this, "Démo sans serveur (données d’exemple)", false);
        demo.setOnClickListener(v -> open("file:///android_asset/demo.html"));
        col.addView(demo);
        col.addView(Ui.space(this, 20));
        col.addView(Ui.text(this, "Règle : l’IA propose, l’employé décide.", 13, Ui.MUTE));

        ScrollView sv = new ScrollView(this);
        sv.setFillViewport(true);
        sv.setBackgroundColor(Ui.BG);
        sv.addView(col);
        setContentView(sv);
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (queueInfo != null) {
            int n = Store.items(this).length;
            queueInfo.setText(n == 0 ? "Rien à envoyer ✓" : n + " contrôle(s) gardé(s) dans le téléphone");
        }
    }

    private boolean configured() {
        String u = prefs.getString("server", "");
        return (u.startsWith("http://") || u.startsWith("https://")) && !prefs.getString("pass", "").isEmpty();
    }

    private boolean saveSettings() {
        String u = url.getText().toString().trim().replaceAll("/+$", "");
        if (!u.startsWith("http://") && !u.startsWith("https://")) {
            Toast.makeText(this, "L’adresse doit commencer par http:// ou https://", Toast.LENGTH_LONG).show();
            return false;
        }
        if (user.getText().toString().trim().isEmpty() || pass.getText().toString().isEmpty()) {
            Toast.makeText(this, "Identifiant et mot de passe obligatoires", Toast.LENGTH_LONG).show();
            return false;
        }
        prefs.edit()
                .putString("server", u)
                .putString("user", user.getText().toString().trim().toLowerCase())
                .putString("pass", pass.getText().toString())
                .apply();
        return true;
    }

    private void open(String u) {
        Intent i = new Intent(this, WebActivity.class);
        i.putExtra("url", u);
        startActivity(i);
    }
}
