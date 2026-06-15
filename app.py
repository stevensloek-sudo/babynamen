"""Babynamen — Flask hoofdbestand met alle routes."""
import secrets
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, abort, session
from flask_login import login_required, current_user

import config
import database as db
import auth
import ai
import betalingen as bet

app = Flask(__name__)
app.config["SECRET_KEY"] = config.get("FLASK_SECRET_KEY") or secrets.token_hex(32)

db.init_db()

auth.login_manager.init_app(app)
auth.oauth.init_app(app)
auth.setup_oauth(app)
app.register_blueprint(auth.auth_bp)


# Lijst landen voor het formulier
LANDEN = [
    "Nederland", "België", "Duitsland", "Frankrijk", "Engeland", "Schotland", "Ierland", "Wales",
    "Spanje", "Portugal", "Italië", "Griekenland", "Zweden", "Noorwegen", "Denemarken", "Finland",
    "IJsland", "Polen", "Tsjechië", "Hongarije", "Rusland", "Oekraïne", "Turkije", "Marokko",
    "Egypte", "Algerije", "Tunesië", "Nigeria", "Ghana", "Kenia", "Ethiopië", "Zuid-Afrika",
    "Israël", "Libanon", "Syrië", "Iran", "Irak", "Saudi-Arabië", "India", "Pakistan",
    "Bangladesh", "China", "Japan", "Korea", "Vietnam", "Thailand", "Indonesië", "Filipijnen",
    "Verenigde Staten", "Canada", "Mexico", "Brazilië", "Argentinië", "Colombia", "Peru", "Chili",
    "Australië", "Nieuw-Zeeland", "Hawaï", "Suriname",
]


def admin_only(f):
    @wraps(f)
    def wrap(*a, **kw):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return f(*a, **kw)
    return wrap


@app.context_processor
def globaal():
    return {
        "mollie_actief": bet.mollie_actief(),
        "anthropic_actief": config.is_gezet("ANTHROPIC_API_KEY"),
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/ping")
def ping():
    """Keep-alive endpoint voor UptimeRobot — houdt Render gratis-plan wakker."""
    return "ok", 200


@app.route("/generator", methods=["GET", "POST"])
@login_required
def generator():
    if not current_user.email_geverifieerd and not current_user.is_admin:
        flash("Verifieer eerst je e-mailadres voordat je kunt genereren.", "warning")
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        filters = _parse_form(request.form)

        # Admin = onbeperkt 50-namen gratis
        if current_user.is_admin:
            aantal = 50
            betaald = True
        elif db.heeft_gratis_generatie_gehad(current_user.uid):
            # Bewaar filters in session voor /upgrade
            session["pending_filters"] = filters
            return redirect(url_for("upgrade"))
        else:
            aantal = 5
            betaald = False

        try:
            namen = ai.genereer_namen(filters, aantal)
        except Exception as e:
            flash(f"Er ging iets mis bij het genereren: {e}", "danger")
            return redirect(url_for("generator"))

        gid = db.opslaan_generatie(current_user.uid, filters, namen, aantal, betaald=betaald)
        return redirect(url_for("resultaten", gid=gid))

    return render_template("generator.html", landen=LANDEN)


@app.route("/resultaten/<int:gid>")
@login_required
def resultaten(gid):
    g = db.get_generatie(gid)
    if not g or g["user_id"] != current_user.uid:
        abort(404)
    return render_template("resultaten.html", generatie=g)


@app.route("/upgrade", methods=["GET", "POST"])
@login_required
def upgrade():
    if current_user.is_admin:
        return redirect(url_for("generator"))

    pending = session.get("pending_filters")

    if request.method == "POST":
        if not pending:
            flash("Vul eerst het formulier in.", "warning")
            return redirect(url_for("generator"))
        if not bet.mollie_actief():
            flash("Betalingen zijn nog niet geconfigureerd. Vraag de beheerder om Mollie te activeren.", "warning")
            return redirect(url_for("upgrade"))

        base = config.get("BASE_URL", "http://localhost:5000").rstrip("/")
        redirect_url = base + url_for("betaling_klaar")
        try:
            payment = bet.start_betaling(current_user.uid, pending, base, redirect_url)
            session["pending_payment_id"] = payment.id
            return redirect(payment.checkout_url)
        except Exception as e:
            flash(f"Mollie fout: {e}", "danger")
            return redirect(url_for("upgrade"))

    return render_template("upgrade.html", heeft_pending=bool(pending))


@app.route("/betaling-klaar")
@login_required
def betaling_klaar():
    pid = session.get("pending_payment_id")
    pending = session.get("pending_filters")
    if not pid or not pending:
        flash("Geen actieve betaling gevonden.", "warning")
        return redirect(url_for("generator"))

    try:
        status = bet.get_payment_status(pid)
    except Exception as e:
        flash(f"Kon betaalstatus niet ophalen: {e}", "danger")
        return redirect(url_for("upgrade"))

    if status != "paid":
        flash(f"Betaling status: {status}. Probeer opnieuw of wacht even.", "warning")
        return redirect(url_for("upgrade"))

    try:
        namen = ai.genereer_namen(pending, 50)
    except Exception as e:
        # Generatie mislukt na betaling → automatisch geld terug
        refund_gelukt = False
        try:
            bet.refund_betaling(pid, reden=f"Generatie mislukt: {str(e)[:100]}")
            refund_gelukt = True
        except Exception as refund_err:
            print(f"[REFUND MISLUKT voor {pid}: {refund_err}]")

        if refund_gelukt:
            flash(f"De generatie is mislukt ({e}). Je €4,95 wordt automatisch teruggestort — "
                  "dit kan een paar werkdagen duren.", "warning")
        else:
            flash(f"De generatie is mislukt ({e}). Neem contact op, dan zorgen we voor terugbetaling.", "danger")
        session.pop("pending_filters", None)
        session.pop("pending_payment_id", None)
        return redirect(url_for("generator"))

    gid = db.opslaan_generatie(current_user.uid, pending, namen, 50, betaald=True)
    db.koppel_generatie_aan_betaling(pid, gid)
    session.pop("pending_filters", None)
    session.pop("pending_payment_id", None)
    return redirect(url_for("resultaten", gid=gid))


@app.route("/webhook/mollie", methods=["POST"])
def webhook_mollie():
    pid = request.form.get("id")
    if not pid:
        return "missing id", 400
    try:
        status = bet.get_payment_status(pid)
        db.update_betaling_status(pid, status)
    except Exception as e:
        print(f"[Webhook fout: {e}]")
    return "ok", 200


@app.route("/mijn-namen")
@login_required
def mijn_namen():
    generaties = db.get_generaties_van_user(current_user.uid)
    return render_template("mijn_namen.html", generaties=generaties)


@app.route("/admin", methods=["GET", "POST"])
@login_required
@admin_only
def admin():
    if request.method == "POST":
        updates = {}
        for veld in ["ANTHROPIC_API_KEY", "RESEND_API_KEY", "RESEND_FROM_EMAIL",
                     "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "MOLLIE_API_KEY", "BASE_URL"]:
            val = request.form.get(veld, "").strip()
            if val and val != "***":
                updates[veld] = val
        if updates:
            config.update_env(updates)
            auth.setup_oauth(app)
            flash(f"Bijgewerkt: {', '.join(updates.keys())}", "success")
        else:
            flash("Geen wijzigingen.", "info")
        return redirect(url_for("admin"))

    status = {
        "ANTHROPIC_API_KEY": config.is_gezet("ANTHROPIC_API_KEY"),
        "RESEND_API_KEY": config.is_gezet("RESEND_API_KEY"),
        "RESEND_FROM_EMAIL": bool(config.get("RESEND_FROM_EMAIL")),
        "GOOGLE_CLIENT_ID": config.is_gezet("GOOGLE_CLIENT_ID"),
        "GOOGLE_CLIENT_SECRET": config.is_gezet("GOOGLE_CLIENT_SECRET"),
        "MOLLIE_API_KEY": config.is_gezet("MOLLIE_API_KEY"),
        "BASE_URL": config.get("BASE_URL", "http://localhost:5000"),
    }
    return render_template("admin.html", status=status)


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


def _parse_form(form):
    """Zet form-data om in filters dict."""
    return {
        "geslacht": form.get("geslacht", "maakt_niet_uit"),
        "lettergrepen": form.get("lettergrepen", "maakt_niet_uit"),
        "achternaam": form.get("achternaam", "").strip(),
        "achternaam_match": form.get("achternaam_match", "nee"),
        "siblings": form.get("siblings", "").strip(),
        "siblings_match": form.get("siblings_match", "nee"),
        "continenten": form.getlist("continenten"),
        "landen": form.getlist("landen"),
        "stijlen": form.getlist("stijlen"),
        "geen_letters": form.get("geen_letters", "").strip(),
        "geen_begin": form.get("geen_begin", "").strip(),
        "geen_eind": form.get("geen_eind", "").strip(),
        "verhaal": form.get("verhaal", "").strip()[:500],
    }


@app.errorhandler(403)
def err_403(e):
    return render_template("error.html", code=403, msg="Geen toegang."), 403


@app.errorhandler(404)
def err_404(e):
    return render_template("error.html", code=404, msg="Pagina niet gevonden."), 404


if __name__ == "__main__":
    app.run(debug=True, port=5000)
