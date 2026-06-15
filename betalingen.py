"""Mollie betalingen."""
import config
import database as db

BEDRAG = "4.95"
BESCHRIJVING = "Babynamen - 50 namen generatie"


def mollie_actief() -> bool:
    key = config.get("MOLLIE_API_KEY").strip()
    return bool(key) and (key.startswith("test_") or key.startswith("live_"))


def _client():
    from mollie.api.client import Client
    c = Client()
    c.set_api_key(config.get("MOLLIE_API_KEY").strip())
    return c


def start_betaling(user_id: int, filters_pending: dict, base_url: str, redirect_url: str):
    """Maak Mollie betaling aan, sla op in DB. filters_pending = inputs voor 50-namen generatie."""
    client = _client()
    payment = client.payments.create({
        "amount": {"currency": "EUR", "value": BEDRAG},
        "description": BESCHRIJVING,
        "redirectUrl": redirect_url,
        "webhookUrl": f"{base_url}/webhook/mollie",
        "metadata": {"user_id": user_id},
    })
    db.maak_betaling(user_id, payment.id, float(BEDRAG), status="open")
    return payment


def get_payment_status(payment_id: str) -> str:
    client = _client()
    payment = client.payments.get(payment_id)
    return payment.status


def refund_betaling(payment_id: str, reden: str = "Generatie mislukt") -> bool:
    """Betaal het volledige bedrag terug aan de klant."""
    client = _client()
    payment = client.payments.get(payment_id)
    payment.refunds.create({
        "amount": {"currency": "EUR", "value": BEDRAG},
        "description": reden,
    })
    db.update_betaling_status(payment_id, "refunded")
    return True
