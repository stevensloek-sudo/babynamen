"""Config loader with hot-reload — admin page kan keys updaten en .env wordt opnieuw ingelezen."""
import os
from pathlib import Path
from dotenv import load_dotenv

ENV_PATH = Path(__file__).parent / ".env"


def laad_env():
    """Laad .env opnieuw in os.environ (override bestaande waardes)."""
    if ENV_PATH.exists():
        load_dotenv(ENV_PATH, override=True)


def get(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def is_gezet(key: str) -> bool:
    val = os.environ.get(key, "").strip()
    return bool(val) and not val.startswith("sk-ant-...") and val != "verander-dit-naar-een-lange-willekeurige-string"


def update_env(updates: dict):
    """Schrijf .env opnieuw met deze updates. Behoudt bestaande regels."""
    bestaand = {}
    if ENV_PATH.exists():
        for regel in ENV_PATH.read_text(encoding="utf-8").splitlines():
            if "=" in regel and not regel.strip().startswith("#"):
                k, _, v = regel.partition("=")
                bestaand[k.strip()] = v.strip()
    bestaand.update(updates)

    regels = ["# Babynamen configuratie\n"]
    volgorde = [
        "FLASK_SECRET_KEY", "ANTHROPIC_API_KEY", "RESEND_API_KEY", "RESEND_FROM_EMAIL",
        "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "MOLLIE_API_KEY", "BASE_URL", "ADMIN_EMAIL"
    ]
    geschreven = set()
    for k in volgorde:
        v = bestaand.get(k, "")
        regels.append(f"{k}={v}\n")
        geschreven.add(k)
    for k, v in bestaand.items():
        if k not in geschreven:
            regels.append(f"{k}={v}\n")
    ENV_PATH.write_text("".join(regels), encoding="utf-8")
    laad_env()


laad_env()
