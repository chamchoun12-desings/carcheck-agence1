package tn.carcheck.app;

import android.content.Context;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

/** Small helpers so every screen looks the same, without XML layouts. */
final class Ui {
    static final int BRAND = Color.parseColor("#1C4E80");
    static final int INK = Color.parseColor("#16202A");
    static final int MUTE = Color.parseColor("#5B6773");
    static final int BG = Color.parseColor("#EEF1F4");
    static final int LINE = Color.parseColor("#D5DBE1");
    static final int OK = Color.parseColor("#2B8A3E");
    static final int BAD = Color.parseColor("#C92A2A");
    static final int WARN = Color.parseColor("#E8590C");

    private Ui() { }

    static int dp(Context c, int v) {
        return Math.round(v * c.getResources().getDisplayMetrics().density);
    }

    static LinearLayout column(Context c) {
        LinearLayout col = new LinearLayout(c);
        col.setOrientation(LinearLayout.VERTICAL);
        int p = dp(c, 20);
        col.setPadding(p, dp(c, 28), p, p);
        col.setBackgroundColor(BG);
        return col;
    }

    static View space(Context c, int h) {
        View v = new View(c);
        v.setLayoutParams(new LinearLayout.LayoutParams(1, dp(c, h)));
        return v;
    }

    static TextView text(Context c, String s, int sp, int color) {
        TextView t = new TextView(c);
        t.setText(s);
        t.setTextSize(sp);
        t.setTextColor(color);
        return t;
    }

    static TextView title(Context c, String s) {
        TextView t = text(c, s, 26, INK);
        t.setTypeface(Typeface.create("sans-serif-condensed", Typeface.BOLD));
        return t;
    }

    static TextView label(Context c, String s) {
        TextView t = text(c, s, 17, INK);
        t.setTypeface(Typeface.DEFAULT_BOLD);
        return t;
    }

    static GradientDrawable box(Context c, int fill, int stroke) {
        GradientDrawable g = new GradientDrawable();
        g.setColor(fill);
        g.setCornerRadius(dp(c, 10));
        g.setStroke(dp(c, 1), stroke);
        return g;
    }

    static Button button(Context c, String s, boolean filled) {
        Button b = new Button(c);
        b.setText(s);
        b.setAllCaps(false);
        b.setTextSize(16);
        b.setGravity(Gravity.CENTER);
        b.setTextColor(filled ? Color.WHITE : BRAND);
        b.setBackground(box(c, filled ? BRAND : Color.WHITE, BRAND));
        b.setPadding(dp(c, 16), dp(c, 12), dp(c, 16), dp(c, 12));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        lp.topMargin = dp(c, 6);
        b.setLayoutParams(lp);
        return b;
    }

    static EditText input(Context c, String hint, int type, int id) {
        EditText e = new EditText(c);
        e.setId(id);                      // an id lets Android keep the text if the screen is rebuilt
        e.setSingleLine(true);
        e.setHint(hint);
        e.setInputType(type == 0 ? InputType.TYPE_CLASS_TEXT : type);
        e.setBackground(box(c, Color.WHITE, LINE));
        e.setPadding(dp(c, 12), dp(c, 12), dp(c, 12), dp(c, 12));
        return e;
    }

    /** A white card with a status line under its button. */
    static LinearLayout card(Context c) {
        LinearLayout l = new LinearLayout(c);
        l.setOrientation(LinearLayout.VERTICAL);
        l.setBackground(box(c, Color.WHITE, LINE));
        int p = dp(c, 14);
        l.setPadding(p, p, p, p);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        lp.topMargin = dp(c, 12);
        l.setLayoutParams(lp);
        return l;
    }
}
