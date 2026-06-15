"""E-mail via Resend, met console fallback als RESEND_API_KEY niet is gezet."""
import config


def stuur_verificatie_mail(naar_email: str, verificatie_link: str) -> bool:
    api_key = config.get("RESEND_API_KEY").strip()
    from_email = config.get("RESEND_FROM_EMAIL", "onboarding@resend.dev").strip() or "onboarding@resend.dev"

    onderwerp = "Bevestig je e-mailadres bij Babynamen"
    html = f"""
    <div style="font-family: -apple-system, sans-serif; max-width: 500px; margin: 0 auto; padding: 30px;">
      <h2 style="color: #1a3a5c;">Welkom bij Babynamen 👶</h2>
      <p>Klik op de knop hieronder om je e-mailadres te bevestigen:</p>
      <p style="text-align: center; margin: 30px 0;">
        <a href="{verificatie_link}" style="background: #C9E4FF; color: #1a3a5c;
           padding: 14px 28px; border-radius: 12px; text-decoration: none; font-weight: bold;">
          Bevestig mijn e-mailadres
        </a>
      </p>
      <p style="color: #888; font-size: 13px;">Of kopieer deze link: {verificatie_link}</p>
    </div>
    """

    if not api_key or api_key.startswith("re_voorbeeld"):
        print("\n" + "=" * 60)
        print(f"[E-MAIL — geen RESEND_API_KEY, dus console-modus]")
        print(f"Naar: {naar_email}")
        print(f"Onderwerp: {onderwerp}")
        print(f"Verificatielink: {verificatie_link}")
        print("=" * 60 + "\n")
        return True

    try:
        import resend
        resend.api_key = api_key
        resend.Emails.send({
            "from": from_email,
            "to": naar_email,
            "subject": onderwerp,
            "html": html,
        })
        return True
    except Exception as e:
        print(f"[E-mail fout: {e}] Fallback naar console:")
        print(f"Naar {naar_email}: {verificatie_link}")
        return True
