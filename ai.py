"""Claude Haiku integratie voor babynaam-generatie."""
import json
import re
import config

MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = (
    "Je bent een expert in babynamen wereldwijd met diepe kennis van etymologie, "
    "culturele context en klanken in verschillende talen. Je geeft gepersonaliseerde, "
    "doordachte naamsuggesties die exact passen bij wat ouders zoeken. "
    "Je antwoordt altijd in puur JSON-formaat zonder verdere tekst eromheen."
)


def _regels(filters: dict) -> list[str]:
    """Bouw alleen regels voor velden die NIET 'maakt niet uit' zijn."""
    r = []

    geslacht = filters.get("geslacht")
    if geslacht and geslacht != "maakt_niet_uit":
        labels = {"jongen": "Jongen", "meisje": "Meisje", "neutraal": "Genderneutraal / beide"}
        r.append(f"Geslacht: {labels.get(geslacht, geslacht)}")

    lettergrepen = filters.get("lettergrepen")
    if lettergrepen and lettergrepen != "maakt_niet_uit":
        r.append(f"Aantal lettergrepen: {lettergrepen}")

    achternaam = (filters.get("achternaam") or "").strip()
    if achternaam and filters.get("achternaam_match") == "ja":
        r.append(f"Achternaam om bij te passen: {achternaam} (naam moet hier goed mee klinken)")

    siblings = (filters.get("siblings") or "").strip()
    if siblings and filters.get("siblings_match") == "ja":
        r.append(f"Namen van broertjes/zusjes om bij te passen qua stijl: {siblings}")

    continenten = filters.get("continenten") or []
    if continenten and "maakt_niet_uit" not in continenten:
        r.append(f"Continenten van herkomst: {', '.join(continenten)}")

    landen = filters.get("landen") or []
    if landen:
        r.append(f"Specifieke landen van herkomst: {', '.join(landen)}")

    stijlen = filters.get("stijlen") or []
    if stijlen and "maakt_niet_uit" not in stijlen:
        r.append(f"Stijl: {', '.join(stijlen)}")

    geen_letters = (filters.get("geen_letters") or "").strip()
    if geen_letters:
        r.append(f"Letters die NIET in de naam mogen voorkomen: {geen_letters}")

    geen_begin = (filters.get("geen_begin") or "").strip()
    if geen_begin:
        r.append(f"Naam mag NIET beginnen met: {geen_begin}")

    geen_eind = (filters.get("geen_eind") or "").strip()
    if geen_eind:
        r.append(f"Naam mag NIET eindigen op: {geen_eind}")

    verhaal = (filters.get("verhaal") or "").strip()
    if verhaal:
        r.append(f"Persoonlijk verhaal van de ouders: {verhaal}")

    return r


def bouw_user_prompt(filters: dict, aantal: int) -> str:
    regels = _regels(filters)
    voorkeuren = "\n".join(f"- {r}" for r in regels) if regels else "- Geen specifieke voorkeuren, geef een mooie diverse selectie."

    return f"""Genereer exact {aantal} unieke babynamen op basis van deze voorkeuren:

{voorkeuren}

Regels:
- Geef exact {aantal} namen, geen herhalingen
- Elke naam moet aan ALLE bovenstaande criteria voldoen

ACHTERNAAM (HOOGSTE PRIORITEIT als opgegeven):
- Als een achternaam is opgegeven om bij te passen, MOET elke voornaam écht goed klinken met die achternaam. Dit is geen formaliteit — het is een harde eis.
- Let op: ritme (aantal lettergrepen samen), klankoverloop (laatste klank van voornaam mag niet botsen met eerste klank achternaam), eindrijm vermijden (Stevens → niet "Evans"), en geen tongbreker-combinaties.
- Spreek de volledige naam in gedachten hardop uit. Klinkt het vloeiend, natuurlijk, mooi? Zo nee → kies een andere naam.
- Noem in de uitleg EXPLICIET hoe de voornaam + achternaam samen klinkt en waarom dat werkt (ritme, klank, alliteratie, etc.).

OVERIGE:
- Voor elke naam geef je: naam, oorsprong (land/cultuur), betekenis, fonetische uitspraak, en een korte persoonlijke uitleg waarom deze naam past bij DEZE specifieke ouders
- Als broertjes/zusjes namen gegeven met match: noem in 'uitleg' waarom de naam daarbij past qua stijl en klank
- Als 'persoonlijk verhaal' is gegeven: laat duidelijk zien dat je dit verhaal hebt begrepen en hebt meegenomen in je keuzes

Output: alleen een geldige JSON-array, geen andere tekst:
[
  {{
    "naam": "...",
    "oorsprong": "...",
    "betekenis": "...",
    "uitspraak": "...",
    "uitleg": "..."
  }}
]"""


def _parse_json_array(tekst: str) -> list[dict]:
    """Parse JSON-array, ook bij truncatie of rommel eromheen."""
    tekst = tekst.strip()
    if tekst.startswith("```"):
        tekst = re.sub(r"^```(?:json)?\s*", "", tekst)
        tekst = re.sub(r"\s*```$", "", tekst)

    # Eerste poging: clean parse
    start = tekst.find("[")
    if start == -1:
        raise ValueError("Geen JSON-array gevonden in Claude antwoord")
    tekst = tekst[start:]
    try:
        return json.loads(tekst)
    except json.JSONDecodeError:
        pass

    # Fallback: parse object voor object, stop bij eerste kapotte
    namen = []
    decoder = json.JSONDecoder()
    i = 1  # skip [
    while i < len(tekst):
        while i < len(tekst) and tekst[i] in " \t\n\r,":
            i += 1
        if i >= len(tekst) or tekst[i] == "]":
            break
        try:
            obj, eind = decoder.raw_decode(tekst, i)
            namen.append(obj)
            i = eind
        except json.JSONDecodeError:
            break
    if not namen:
        raise ValueError("Kon geen namen parsen uit Claude antwoord")
    return namen


def genereer_namen(filters: dict, aantal: int) -> list[dict]:
    """Roep Claude Haiku aan en geef lijst van naam-dicts terug."""
    api_key = config.get("ANTHROPIC_API_KEY").strip()
    if not api_key or api_key.startswith("sk-ant-..."):
        raise RuntimeError("ANTHROPIC_API_KEY is niet ingesteld. Ga naar /admin om de key in te voeren.")

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    # 5 namen = ~1500 tokens, 50 namen = ~12000 tokens. Ruim genomen:
    max_tokens = 16000 if aantal >= 50 else 2500

    msg = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        temperature=0.8,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": bouw_user_prompt(filters, aantal)}],
    )
    tekst = msg.content[0].text
    namen = _parse_json_array(tekst)

    if not isinstance(namen, list):
        raise RuntimeError("Claude gaf geen geldige lijst terug.")
    return namen
