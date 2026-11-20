package tn.carcheck.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.os.Bundle;
import android.text.InputType;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.File;
import java.io.IOException;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

/** Checks filmed offline, waiting to be sent. Send, fix the plate, or delete. */
public class QueueActivity extends Activity {
    private LinearLayout list;
    private TextView summary;
    private Button sendAll;
    private volatile boolean busy;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setStatusBarColor(Ui.BRAND);
        LinearLayout col = Ui.column(this);
        col.addView(Ui.title(this, "À envoyer"));
        summary = Ui.text(this, "", 14, Ui.MUTE);
        col.addView(summary);
        sendAll = Ui.button(this, "Tout envoyer maintenant", true);
        sendAll.setOnClickListener(v -> send(null));
        col.addView(sendAll);
        list = new LinearLayout(this);
        list.setOrientation(LinearLayout.VERTICAL);
        col.addView(list);
        ScrollView sv = new ScrollView(this);
        sv.setFillViewport(true);
        sv.setBackgroundColor(Ui.BG);
        sv.addView(col);
        setContentView(sv);
    }

    @Override
    protected void onResume() {
        super.onResume();
        render();
    }

    private void render() {
        list.removeAllViews();
        File[] items = Store.items(this);
        summary.setText(items.length == 0 ? "Rien à envoyer ✓"
                : items.length + " contrôle(s) gardé(s) dans le téléphone. Ils partent tout seuls à l’ouverture de l’application si le serveur répond.");
        sendAll.setVisibility(items.length == 0 ? View.GONE : View.VISIBLE);
        SimpleDateFormat f = new SimpleDateFormat("dd/MM HH:mm", Locale.FRANCE);
        for (File item : items) {
            JSONObject m = Store.readMeta(item);
            LinearLayout card = Ui.card(this);
            String car = m.optString("car", "");
            card.addView(Ui.label(this, ("in".equals(m.optString("kind")) ? "Retour" : "Sortie") + " · "
                    + (car.isEmpty() ? "plaque à lire dans la vidéo" : car)));
            double rec = 0;
            try {
                rec = Double.parseDouble(m.optString("recorded_at", "0"));
            } catch (NumberFormatException ignored) { }
            card.addView(Ui.text(this, "Filmé le " + f.format(new Date((long) (rec * 1000))), 14, Ui.MUTE));
            String err = m.optString("error", "");
            if (!err.isEmpty()) {
                boolean refused = "refused".equals(m.optString("status"));
                card.addView(Ui.text(this, (refused ? "À corriger : " : "") + err, 14, refused ? Ui.BAD : Ui.WARN));
            }
            Button send = Ui.button(this, "Envoyer", true);
            send.setOnClickListener(v -> send(item));
            card.addView(send);
            Button fix = Ui.button(this, "Corriger la plaque", false);
            fix.setOnClickListener(v -> fixPlate(item));
            card.addView(fix);
            Button del = Ui.button(this, "Supprimer", false);
            del.setOnClickListener(v -> new AlertDialog.Builder(this)
                    .setTitle("Supprimer ce contrôle ?")
                    .setMessage("La vidéo, les photos et la signature seront effacées du téléphone.")
                    .setPositiveButton("Supprimer", (d, w) -> {
                        Store.deleteDir(item);
                        render();
                    })
                    .setNegativeButton("Annuler", null)
                    .show());
            card.addView(del);
            list.addView(card);
        }
    }

    private void send(File one) {
        if (busy) return;
        busy = true;
        sendAll.setEnabled(false);
        Toast.makeText(this, "Envoi en cours…", Toast.LENGTH_SHORT).show();
        new Thread(() -> {
            String msg;
            if (one == null) {
                msg = Uploader.sendAll(this, true);
            } else {
                Uploader.Result r = Uploader.sendOne(this, one);
                msg = r.message;
            }
            final String m = msg;
            runOnUiThread(() -> {
                busy = false;
                sendAll.setEnabled(true);
                Toast.makeText(this, m, Toast.LENGTH_LONG).show();
                render();
            });
        }).start();
    }

    private void fixPlate(File item) {
        final EditText e = new EditText(this);
        e.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS);
        e.setHint("123 TU 4567");
        e.setText(Store.readMeta(item).optString("car", ""));
        new AlertDialog.Builder(this)
                .setTitle("Immatriculation")
                .setView(e)
                .setPositiveButton("Enregistrer", (d, w) -> {
                    JSONObject m = Store.readMeta(item);
                    try {
                        m.put("car", e.getText().toString().trim());
                        m.put("status", "waiting");
                        m.put("error", "");
                        Store.writeMeta(item, m);
                    } catch (JSONException | IOException ex) {
                        Toast.makeText(this, "Non enregistré : " + ex.getMessage(), Toast.LENGTH_LONG).show();
                    }
                    render();
                })
                .setNegativeButton("Annuler", null)
                .show();
    }
}
