"""SQLite schema en helpers."""
import sqlite3
import json
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / "babynaam.db"


def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    return c


def init_db():
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT,
            google_id TEXT UNIQUE,
            email_geverifieerd INTEGER DEFAULT 0,
            verificatie_token TEXT,
            registratie_ip TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS generaties (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            filters_json TEXT NOT NULL,
            namen_json TEXT NOT NULL,
            aantal_namen INTEGER NOT NULL,
            betaald INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS betalingen (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            generatie_id INTEGER,
            mollie_payment_id TEXT UNIQUE,
            bedrag REAL NOT NULL,
            status TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (generatie_id) REFERENCES generaties(id)
        );
        """)


# --- Users ---

def maak_user(email, password_hash=None, google_id=None, verificatie_token=None,
              geverifieerd=False, ip=None):
    with conn() as c:
        cur = c.execute(
            "INSERT INTO users (email, password_hash, google_id, email_geverifieerd, "
            "verificatie_token, registratie_ip) VALUES (?, ?, ?, ?, ?, ?)",
            (email, password_hash, google_id, 1 if geverifieerd else 0,
             verificatie_token, ip)
        )
        return cur.lastrowid


def get_user_by_email(email):
    with conn() as c:
        return c.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()


def get_user_by_id(uid):
    with conn() as c:
        return c.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()


def get_user_by_token(token):
    with conn() as c:
        return c.execute("SELECT * FROM users WHERE verificatie_token = ?", (token,)).fetchone()


def get_user_by_google_id(google_id):
    with conn() as c:
        return c.execute("SELECT * FROM users WHERE google_id = ?", (google_id,)).fetchone()


def verifieer_user(uid):
    with conn() as c:
        c.execute("UPDATE users SET email_geverifieerd = 1, verificatie_token = NULL WHERE id = ?", (uid,))


def koppel_google_id(uid, google_id):
    with conn() as c:
        c.execute("UPDATE users SET google_id = ?, email_geverifieerd = 1 WHERE id = ?", (google_id, uid))


def tel_accounts_per_ip(ip, uren=24):
    with conn() as c:
        rij = c.execute(
            "SELECT COUNT(*) AS n FROM users WHERE registratie_ip = ? "
            "AND created_at >= datetime('now', ?)",
            (ip, f"-{uren} hours")
        ).fetchone()
        return rij["n"]


# --- Generaties ---

def opslaan_generatie(user_id, filters, namen, aantal, betaald=False):
    with conn() as c:
        cur = c.execute(
            "INSERT INTO generaties (user_id, filters_json, namen_json, aantal_namen, betaald) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, json.dumps(filters, ensure_ascii=False),
             json.dumps(namen, ensure_ascii=False), aantal, 1 if betaald else 0)
        )
        return cur.lastrowid


def get_generatie(gid):
    with conn() as c:
        rij = c.execute("SELECT * FROM generaties WHERE id = ?", (gid,)).fetchone()
        if not rij:
            return None
        d = dict(rij)
        d["filters"] = json.loads(d["filters_json"])
        d["namen"] = json.loads(d["namen_json"])
        return d


def get_generaties_van_user(user_id):
    with conn() as c:
        rijen = c.execute(
            "SELECT * FROM generaties WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,)
        ).fetchall()
        result = []
        for r in rijen:
            d = dict(r)
            d["filters"] = json.loads(d["filters_json"])
            d["namen"] = json.loads(d["namen_json"])
            result.append(d)
        return result


def heeft_gratis_generatie_gehad(user_id):
    with conn() as c:
        rij = c.execute(
            "SELECT COUNT(*) AS n FROM generaties WHERE user_id = ? AND betaald = 0",
            (user_id,)
        ).fetchone()
        return rij["n"] > 0


# --- Betalingen ---

def maak_betaling(user_id, mollie_payment_id, bedrag, status="open", generatie_id=None):
    with conn() as c:
        cur = c.execute(
            "INSERT INTO betalingen (user_id, generatie_id, mollie_payment_id, bedrag, status) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, generatie_id, mollie_payment_id, bedrag, status)
        )
        return cur.lastrowid


def update_betaling_status(mollie_payment_id, status):
    with conn() as c:
        c.execute("UPDATE betalingen SET status = ? WHERE mollie_payment_id = ?",
                  (status, mollie_payment_id))


def get_betaling_by_mollie_id(mollie_payment_id):
    with conn() as c:
        return c.execute("SELECT * FROM betalingen WHERE mollie_payment_id = ?",
                         (mollie_payment_id,)).fetchone()


def koppel_generatie_aan_betaling(mollie_payment_id, generatie_id):
    with conn() as c:
        c.execute("UPDATE betalingen SET generatie_id = ? WHERE mollie_payment_id = ?",
                  (generatie_id, mollie_payment_id))
