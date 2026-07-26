import os
import re
from datetime import datetime
from typing import Optional, Literal

import dateparser
from pydantic import BaseModel
from openai import OpenAI

from app.ai.prompts import (
    INTENT_EXTRACTION_PROMPT,
    CONVERSATIONAL_REPLY_PROMPT,
    build_tenant_context,
    build_confirmation_context,
)

client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY", "").strip()
)

MODEL_NAME = "gpt-5.4-mini"


# ---------------------------------------------------------------------------
# Livello 2 — Intent & Entity Extraction (LLM). Non decide nulla, non calcola
# date: estrae solo informazioni grezze secondo uno schema fisso.
# ---------------------------------------------------------------------------

class IntentSchemaBase(BaseModel):
    """Schema di default: usato quando NON siamo in attesa di una conferma esplicita."""
    intent: Literal[
        "greeting",
        "check_availability",
        "book_appointment",
        "reschedule_appointment",
        "cancel_appointment",
        "other",
    ]
    service: Optional[str] = None
    operator: Optional[str] = None
    time_expression: Optional[str] = None
    customer_name: Optional[str] = None


class IntentSchemaWithConfirmation(BaseModel):
    """
    Schema usato SOLO quando la sessione e' in stato "awaiting_confirmation".
    Include confirm_appointment/deny_appointment tra le opzioni possibili —
    fuori da questo stato, questi due intent non esistono proprio come scelta
    valida per il modello (non e' solo un'istruzione nel prompt, e' un vincolo
    strutturale dello schema: impossibile da aggirare).
    """
    intent: Literal[
        "greeting",
        "check_availability",
        "book_appointment",
        "reschedule_appointment",
        "cancel_appointment",
        "confirm_appointment",
        "deny_appointment",
        "other",
    ]
    service: Optional[str] = None
    operator: Optional[str] = None
    time_expression: Optional[str] = None
    customer_name: Optional[str] = None


def extract_intent(message: str, awaiting_confirmation: bool = False):
    """
    Chiama l'AI SOLO per capire il linguaggio naturale ed estrarre dati grezzi.
    Usa gli Structured Outputs (schema Pydantic): l'intent e' vincolato a un
    insieme fisso di valori (Literal), quindi non serve piu' validare/pulire
    manualmente una risposta testuale. Lo schema usato dipende dallo stato reale
    della conversazione, cosi' confirm/deny non sono mai un'opzione fuori contesto.
    """
    if not client.api_key:
        raise RuntimeError("OPENAI_API_KEY mancante su Render.")

    schema = IntentSchemaWithConfirmation if awaiting_confirmation else IntentSchemaBase

    confirmation_context = build_confirmation_context(awaiting_confirmation)
    prompt = INTENT_EXTRACTION_PROMPT.format(
        confirmation_context=confirmation_context,
        message=message,
    )

    response = client.responses.parse(
        model=MODEL_NAME,
        input=prompt,
        text_format=schema,
    )

    return response.output_parsed


# ---------------------------------------------------------------------------
# Livello 3 — Parser Temporale (dateparser). Nessun LLM: trasforma la
# "time_expression" grezza in data/ora strutturate, in modo deterministico.
# ---------------------------------------------------------------------------

IT_PERIOD_KEYWORDS = {
    "morning": ["mattina", "mattino", "stamattina", "domani mattina"],
    "afternoon": ["pomeriggio", "dopo pranzo", "dopopranzo"],
    "evening": ["sera", "stasera", "serata", "tardi"],
}

# Pattern per rilevare se nell'espressione e' presente un orario ESPLICITO
# (es. "alle 15", "alle 15:30", "ore 16", "16:00"), a differenza di una
# semplice data o fascia oraria generica ("venerdì", "pomeriggio").
_EXPLICIT_TIME_PATTERN = re.compile(
    r"\b(\d{1,2})([:.,]\d{2})?\s*(?=$|[^\d]|ore|di sera|di mattina|di pomeriggio)",
    re.IGNORECASE,
)
_TIME_HINT_WORDS = ["alle", "ore", ":", "verso le"]

# Espressioni come "da martedì in poi" o "a partire da lunedì prossimo" sono
# intervalli, non una singola data: dateparser va in confusione se gli passiamo
# la frase intera. Isoliamo l'ancora temporale vera prima di parsarla — il
# significato "da quel giorno in poi" e' comunque quello che find_next_available_slots
# gia' fa di suo (cerca in avanti a partire dalla data), quindi non serve altro.
_RANGE_START_PATTERNS = [
    re.compile(r"a partire da (.+)", re.IGNORECASE),
    re.compile(r"da (.+?) in poi", re.IGNORECASE),
]


def _extract_range_anchor(text: str) -> str:
    """Se il testo esprime un intervallo aperto ('da X in poi'), ritorna solo X. Altrimenti ritorna il testo originale."""
    for pattern in _RANGE_START_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1).strip()
    return text


def _detect_period(text: str) -> Optional[str]:
    if not text:
        return None
    lowered = text.lower()
    for period, keywords in IT_PERIOD_KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            return period
    return None


def _has_explicit_time_hint(text: str) -> bool:
    """Controllo leggero: il testo contiene indizi di un orario preciso (non solo una fascia generica)?"""
    lowered = text.lower()
    return any(hint in lowered for hint in _TIME_HINT_WORDS) and bool(re.search(r"\d", lowered))


def extract_datetime(time_expression: Optional[str]) -> dict:
    """
    Trasforma un'espressione temporale testuale (es. "venerdì dopo pranzo",
    "domani alle 16:30") in dati strutturati, usando dateparser — deterministico,
    nessuna chiamata AI. Ritorna sempre un dict con chiavi: date, time, period.

    - "date": stringa YYYY-MM-DD, o None se non risolvibile.
    - "time": stringa HH:MM, o None se l'espressione non conteneva un orario esplicito.
    - "period": "morning"/"afternoon"/"evening", o None.
    """
    result = {"date": None, "time": None, "period": None}

    if not time_expression or not time_expression.strip():
        return result

    result["period"] = _detect_period(time_expression)

    anchor_expression = _extract_range_anchor(time_expression)

    parsed_dt = dateparser.parse(
        anchor_expression,
        languages=["it"],
        settings={
            "PREFER_DATES_FROM": "future",
            "TIMEZONE": "Europe/Rome",
            "RETURN_AS_TIMEZONE_AWARE": False,
            "RELATIVE_BASE": datetime.now(),
        },
    )

    if not parsed_dt:
        return result

    result["date"] = parsed_dt.strftime("%Y-%m-%d")

    # dateparser assegna 00:00 come default quando non trova un orario esplicito.
    # Consideriamo l'ora attendibile solo se il testo conteneva davvero indizi
    # di un orario preciso (altrimenti "venerdì" darebbe erroneamente le 00:00).
    if _has_explicit_time_hint(time_expression) and not (parsed_dt.hour == 0 and parsed_dt.minute == 0):
        result["time"] = parsed_dt.strftime("%H:%M")

    return result


# ---------------------------------------------------------------------------
# Generazione della risposta finale (LLM) — SOLO per formulare in modo naturale
# una decisione che il backend ha gia' preso (o per saluti/fallback generici).
# Non deve mai ricevere il compito di "decidere" fatti: quelli restano
# messaggi deterministici costruiti in booking.py.
# ---------------------------------------------------------------------------

def generate_conversational_reply(context_msg: str, user_message: str, tenant=None) -> str:
    if not client.api_key:
        raise RuntimeError("OPENAI_API_KEY mancante su Render.")

    tenant_context = build_tenant_context(tenant)
    base_prompt = CONVERSATIONAL_REPLY_PROMPT.format(tenant_context=tenant_context)

    prompt = (
        base_prompt
        + f"\n\nContesto/Istruzione:\n{context_msg}\n\nMessaggio Utente:\n{user_message}"
    )

    response = client.responses.create(
        model=MODEL_NAME,
        input=prompt,
    )

    return response.output_text.strip()
