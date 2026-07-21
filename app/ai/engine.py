import os
import json
from datetime import datetime
from app.ai.prompts import INTENT_EXTRACTION_PROMPT, CONVERSATIONAL_REPLY_PROMPT

def get_gemini_client():
    import google.generativeai as genai
    api_key = os.environ.get("GOOGLE_AI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Chiave API Google AI mancante. Imposta GOOGLE_AI_API_KEY su Render.")
    genai.configure(api_key=api_key)
    return genai.GenerativeModel("gemini-1.5-flash")

def extract_intent_and_entities(message: str) -> dict:
    """
    Extracts the user's intent, date, time, and name using Google Gemini API.
    Returns structured JSON output.
    """
    model = get_gemini_client()
    current_time_info = datetime.now().strftime("%Y-%m-%d %H:%M (giorno della settimana: %A)")

    prompt = (
        INTENT_EXTRACTION_PROMPT.format(current_time_info=current_time_info)
        + "\n\nMessaggio utente: " + message
        + "\n\nRispondi SOLO con un oggetto JSON valido, senza markdown, senza ```json."
    )

    response = model.generate_content(prompt)
    content = response.text.strip()

    # Rimuovi eventuali backtick markdown
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
    content = content.strip()

    return json.loads(content)

def generate_conversational_reply(context_msg: str, user_message: str) -> str:
    """
    Generates a natural, professional WhatsApp response based on message context.
    """
    model = get_gemini_client()

    prompt = (
        CONVERSATIONAL_REPLY_PROMPT
        + f"\n\nContesto/Istruzione:\n{context_msg}\n\nMessaggio Utente:\n{user_message}"
    )

    response = model.generate_content(prompt)
    return response.text.strip()
