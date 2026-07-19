import os
import json
from datetime import datetime
from openai import OpenAI
from app.core.config import settings
from app.ai.prompts import INTENT_EXTRACTION_PROMPT, CONVERSATIONAL_REPLY_PROMPT

def get_openai_client():
    if not settings.OPENAI_API_KEY or settings.OPENAI_API_KEY == "" or settings.OPENAI_API_KEY.startswith("your_"):
        raise RuntimeError("Chiave API OpenAI mancante. Per favore imposta la variabile OPENAI_API_KEY nel file .env.")
    return OpenAI(api_key=settings.OPENAI_API_KEY)

def extract_intent_and_entities(message: str) -> dict:
    """
    Extracts the user's intent, date, time, and name using OpenAI Chat Completion API.
    Guarantees structured output using response_format JSON mode.
    """
    client = get_openai_client()
    current_time_info = datetime.now().strftime("%Y-%m-%d %H:%M (giorno della settimana: %A)")
    
    response = client.chat.completions.create(
        model=settings.AI_MODEL,
        messages=[
            {"role": "system", "content": INTENT_EXTRACTION_PROMPT.format(current_time_info=current_time_info)},
            {"role": "user", "content": message}
        ],
        temperature=0.0,
        response_format={"type": "json_object"}
    )
    
    content = response.choices[0].message.content.strip()
    return json.loads(content)

def generate_conversational_reply(context_msg: str, user_message: str) -> str:
    """
    Generates a natural, professional WhatsApp response based on message context.
    """
    client = get_openai_client()
    
    response = client.chat.completions.create(
        model=settings.AI_MODEL,
        messages=[
            {"role": "system", "content": CONVERSATIONAL_REPLY_PROMPT},
            {"role": "user", "content": f"Contesto/Instruzione:\n{context_msg}\n\nMessaggio Utente:\n{user_message}"}
        ],
        temperature=0.7
    )
    return response.choices[0].message.content.strip()
