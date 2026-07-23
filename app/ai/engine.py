import os
import json
import requests
from datetime import datetime
from app.ai.prompts import INTENT_EXTRACTION_PROMPT, CONVERSATIONAL_REPLY_PROMPT

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent"

def call_gemini(prompt: str) -> str:
    api_key = os.environ.get("GOOGLE_AI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GOOGLE_AI_API_KEY mancante su Render.")

    response = requests.post(
        f"{GEMINI_API_URL}?key={api_key}",
        headers={"Content-Type": "application/json"},
        json={"contents": [{"parts": [{"text": prompt}]}]}
    )

    if response.status_code != 200:
        raise RuntimeError(f"Gemini API error {response.status_code}: {response.text}")

    data = response.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]

def extract_intent_and_entities(message: str) -> dict:
    current_time_info = datetime.now().strftime("%Y-%m-%d %H:%M (giorno della settimana: %A)")
    prompt = (
        INTENT_EXTRACTION_PROMPT.format(current_time_info=current_time_info)
        + "\n\nMessaggio utente: " + message
        + "\n\nRispondi SOLO con un oggetto JSON valido, senza markdown, senza ```json."
    )
    content = call_gemini(prompt).strip()
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
    return json.loads(content.strip())

def generate_conversational_reply(context_msg: str, user_message: str) -> str:
    prompt = (
        CONVERSATIONAL_REPLY_PROMPT
        + f"\n\nContesto/Istruzione:\n{context_msg}\n\nMessaggio Utente:\n{user_message}"
    )
    return call_gemini(prompt).strip()
