"""Authenticatie: e-mail/wachtwoord + Google OAuth + Flask-Login."""
import secrets
import bcrypt
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from authlib.integrations.flask_client import OAuth

import config
import database as db
from email_helper import stuur_verificatie_mail

WEGWERP_DOMEINEN = {
    "10minutemail.com", "tempmail.com", "guerrillamail.com", "mailinator.com",
    "throwawaymail.com", "yopmail.com", "trashmail.com", "fakeinbox.com",
    "getnada.com", "maildrop.cc", "sharklasers.com", "temp-mail.org",
    "dispostable.com", "mintemail.com", "mohmal.com",
}

login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Je moet ingelogd zijn om dit te gebruiken."
login_manager.login_message_category = "info"

oauth = OAuth()

auth_bp = Blueprint("auth", __name__)


class User(UserMixin):
    def __init__(self, rij):
        self.id = str(rij["id"])
        self.uid = rij["id"]
        self.email = rij["email"]
        self.email_geverifieerd = bool(rij["email_geverifieerd"])

    @property
    def is_admin(self):
        return self.email.lower() == config.get("ADMIN_EMAIL", "").strip().lower()


@login_manager.user_loader
def laad_user(uid):
    rij = db.get_user_by_id(int(uid))
    return User(rij) if rij else None


def setup_oauth(app):
    """Registreer Google OAuth client, of None als geen keys."""
    cid = config.get("GOOGLE_CLIENT_ID").strip()
    csec = config.get("GOOGLE_CLIENT_SECRET").strip()
    if cid and csec:
        oauth.register(
            name="google",
            client_id=cid,
            client_secret=csec,
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )


def google_actief() -> bool:
    return config.is_gezet("GOOGLE_CLIENT_ID") and config.is_gezet("GOOGLE_CLIENT_SECRET")


def _geldig_email(email: str) -> bool:
    if "@" not in email or "." not in email.split("@")[-1]:
        return False
    domein = email.split("@")[-1].lower()
    return domein not in WEGWERP_DOMEINEN


def _client_ip():
    return request.headers.get("X-Forwarded-For", request.remote_addr or "0.0.0.0").split(",")[0].strip()


@auth_bp.route("/registreer", methods=["GET", "POST"])
def registreer():
    if current_user.is_authenticated:
        return redirect(url_for("generator"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        wachtwoord = request.form.get("wachtwoord", "")
        wachtwoord2 = request.form.get("wachtwoord2", "")

        if not _geldig_email(email):
            flash("Vul een geldig e-mailadres in (geen wegwerp-mail).", "danger")
            return render_template("registreer.html", google_actief=google_actief())
        if len(wachtwoord) < 8:
            flash("Wachtwoord moet minimaal 8 tekens zijn.", "danger")
            return render_template("registreer.html", google_actief=google_actief())
        if wachtwoord != wachtwoord2:
            flash("Wachtwoorden komen niet overeen.", "danger")
            return render_template("registreer.html", google_actief=google_actief())
        if db.get_user_by_email(email):
            flash("Er bestaat al een account met dit e-mailadres.", "danger")
            return render_template("registreer.html", google_actief=google_actief())

        ip = _client_ip()
        if db.tel_accounts_per_ip(ip) >= 3:
            flash("Te veel accounts vanaf deze locatie. Probeer het later opnieuw.", "danger")
            return render_template("registreer.html", google_actief=google_actief())

        hash_ = bcrypt.hashpw(wachtwoord.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

        # Admin wordt direct geverifieerd (geen e-mailcheck nodig)
        if email == config.get("ADMIN_EMAIL", "").strip().lower():
            db.maak_user(email, password_hash=hash_, geverifieerd=True, ip=ip)
            flash("Admin-account aangemaakt en geverifieerd. Je kunt inloggen.", "success")
            return redirect(url_for("auth.login"))

        token = secrets.token_urlsafe(32)
        db.maak_user(email, password_hash=hash_, verificatie_token=token, ip=ip)
        link = url_for("auth.verifieer", token=token, _external=True)
        stuur_verificatie_mail(email, link)

        flash("Account aangemaakt! Check je inbox (en spam) om te verifiëren.", "success")
        return redirect(url_for("auth.login"))

    return render_template("registreer.html", google_actief=google_actief())


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("generator"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        wachtwoord = request.form.get("wachtwoord", "")
        rij = db.get_user_by_email(email)
        if not rij or not rij["password_hash"]:
            flash("Onjuist e-mailadres of wachtwoord.", "danger")
            return render_template("login.html", google_actief=google_actief())
        if not bcrypt.checkpw(wachtwoord.encode("utf-8"), rij["password_hash"].encode("utf-8")):
            flash("Onjuist e-mailadres of wachtwoord.", "danger")
            return render_template("login.html", google_actief=google_actief())
        if not rij["email_geverifieerd"]:
            flash("Je e-mailadres is nog niet geverifieerd. Check je inbox (en spam).", "warning")
            return render_template("login.html", google_actief=google_actief())

        login_user(User(rij), remember=True)
        return redirect(url_for("generator"))

    return render_template("login.html", google_actief=google_actief())


@auth_bp.route("/verifieer/<token>")
def verifieer(token):
    rij = db.get_user_by_token(token)
    if not rij:
        flash("Verificatielink is ongeldig of al gebruikt.", "danger")
        return redirect(url_for("auth.login"))
    db.verifieer_user(rij["id"])
    flash("E-mail geverifieerd! Je kunt nu inloggen.", "success")
    return redirect(url_for("auth.login"))


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))


# --- Google OAuth ---

@auth_bp.route("/login/google")
def login_google():
    if not google_actief():
        flash("Google login is nog niet geconfigureerd.", "warning")
        return redirect(url_for("auth.login"))
    redirect_uri = url_for("auth.google_callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@auth_bp.route("/login/google/callback")
def google_callback():
    if not google_actief():
        return redirect(url_for("auth.login"))
    try:
        token = oauth.google.authorize_access_token()
        info = token.get("userinfo") or oauth.google.parse_id_token(token, None)
    except Exception as e:
        flash(f"Google login mislukt: {e}", "danger")
        return redirect(url_for("auth.login"))

    google_id = info.get("sub")
    email = (info.get("email") or "").lower()
    if not email or not google_id:
        flash("Geen e-mail ontvangen van Google.", "danger")
        return redirect(url_for("auth.login"))

    rij = db.get_user_by_google_id(google_id)
    if not rij:
        rij = db.get_user_by_email(email)
        if rij:
            db.koppel_google_id(rij["id"], google_id)
            rij = db.get_user_by_id(rij["id"])
        else:
            ip = _client_ip()
            uid = db.maak_user(email, google_id=google_id, geverifieerd=True, ip=ip)
            rij = db.get_user_by_id(uid)

    login_user(User(rij), remember=True)
    return redirect(url_for("generator"))
