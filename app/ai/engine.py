import os
import json
from datetime import datetime

from openai import OpenAI
from app.ai.prompts import INTENT_EXTRACTION_PROMPT, CONVERSATIONAL_REPLY_PROMPT

client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY", "").strip()
)


def call_openai(prompt: str) -> str:
    if not client.api_key:
        raise RuntimeError("OPENAI_API_KEY mancante su Render.")

    response = client.responses.create(
        model="gpt-5.5-mini",
        input=prompt,
    )

    return response.output_text


def extract_intent_and_entities(message: str) -> dict:
    current_time_info = datetime.now().strftime(
        "%Y-%m-%d %H:%M (giorno della settimana: %A)"
    )

    prompt = (
        INTENT_EXTRACTION_PROMPT.format(current_time_info=current_time_info)
        + "\n\nMessaggio utente: "
        + message
        + "\n\nRispondi SOLO con un oggetto JSON valido, senza markdown, senza ```json."
    )

    content = call_openai(prompt).strip()

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

    return call_openai(prompt).strip()
