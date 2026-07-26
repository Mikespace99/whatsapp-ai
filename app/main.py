from fastapi import FastAPI
from app.db.database import engine, Base, SessionLocal
from app.db.models import Tenant
from app.whatsapp.webhook import router as whatsapp_router
from app.api.auth import router as auth_router
from app.api.onboarding import router as onboarding_router
from app.api.admin import router as admin_router
import os

# Create database tables if they do not exist
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="WhatsApp AI SaaS Platform MVP",
    description="Multi-tenant booking assistant platform with Google Calendar OAuth & WhatsApp API routing",
    version="1.0.0"
)

# Include Authentication Routes (OAuth 2.0)
app.include_router(auth_router, tags=["Authentication"])

# Include the WhatsApp Webhook router
app.include_router(whatsapp_router, prefix="/webhook", tags=["Webhook"])

# Include the Onboarding router (landing page di registrazione)
app.include_router(onboarding_router)

# Include the Admin router (collegamento WhatsApp assistito)
app.include_router(admin_router)


@app.get("/")
async def root():
    """
    Health check / welcome endpoint.
    """
    return {
        "status": "online",
        "message": "WhatsApp AI SaaS Platform MVP is running!",
        "docs": "/docs"
    }


@app.get("/test-ai")
def test_ai():
    """Tests the configured AI provider via REST API (OpenAI)."""
    import requests as req
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return {"status": "error", "message": "OPENAI_API_KEY non trovata!"}
    try:
        res = req.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            json={"model": "gpt-5.4-mini", "input": "Rispondi solo con: OK"},
        )
        if res.status_code != 200:
            return {"status": "error", "http_status": res.status_code, "error": res.text}
        reply = res.json().get("output_text", "")
        return {"status": "success", "key_preview": f"{api_key[:8]}...", "ai_response": reply}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.get("/test-structured-output")
def test_structured_output():
    """
    Test degli Structured Outputs di OpenAI (client.responses.parse con uno schema
    Pydantic), per verificare la compatibilita' prima di riscrivere engine.py.
    """
    from pydantic import BaseModel
    from typing import Optional
    from openai import OpenAI

    class TestIntentSchema(BaseModel):
        intent: str
        service: Optional[str] = None
        operator: Optional[str] = None
        time_expression: Optional[str] = None
        customer_name: Optional[str] = None

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return {"status": "error", "message": "OPENAI_API_KEY non trovata!"}

    try:
        client = OpenAI(api_key=api_key)
        response = client.responses.parse(
            model="gpt-5.4-mini",
            input=(
                "Estrai le informazioni da questo messaggio in italiano di un cliente "
                "che scrive a un sistema di prenotazione: "
                "'Vorrei prenotare un taglio con Marco per venerdì dopo pranzo, sono Luca.'"
            ),
            text_format=TestIntentSchema,
        )
        parsed = response.output_parsed
        return {
            "status": "success",
            "parsed": parsed.model_dump(),
        }
    except Exception as e:
        return {"status": "error", "error": str(e), "error_type": type(e).__name__}


@app.get("/seed")
def seed_database(phone_id: str = "WABA-ROSSI-111", token: str = "rossi_mock_token"):
    """
    Seeds or updates initial Tenant 1 (Dr. Rossi) with real Meta test phone_id and token.
    """
    try:
        db = SessionLocal()
        tenant = db.query(Tenant).filter(Tenant.id == 1).first()
        if not tenant:
            tenant = Tenant(
                id=1,
                name="Dr. Rossi (Dentista)",
                whatsapp_phone_number_id=phone_id,
                whatsapp_access_token=token
            )
            db.add(tenant)
        else:
            tenant.whatsapp_phone_number_id = phone_id
            tenant.whatsapp_access_token = token

        db.commit()
        db.close()
        return {
            "status": "success",
            "message": f"Tenant 1 (Dr. Rossi) aggiornato con phone_id={phone_id}!"
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/debug-config")
def debug_config():
    """
    Debug route to verify environment variables loaded on Render.
    """
    from app.core.config import settings
    cid = settings.GOOGLE_CLIENT_ID
    return {
        "CLIENT_ID_LOADED": bool(cid and not cid.startswith("your_")),
        "CLIENT_ID_PREVIEW": f"{cid[:10]}...{cid[-20:]}" if cid else "NONE",
        "REDIRECT_URI": settings.GOOGLE_REDIRECT_URI
    }


@app.get("/debug-db")
def debug_db():
    """
    Debug temporaneo: verifica quale database sta usando l'app,
    senza esporre credenziali sensibili.
    """
    from app.core.config import settings
    url = settings.DATABASE_URL

    db_type = "postgres" if url.startswith("postgres") else "sqlite" if url.startswith("sqlite") else "unknown"

    if "@" in url:
        host_part = url.split("@", 1)[1]
    else:
        host_part = url

    return {
        "db_type": db_type,
        "host_masked": host_part,
        "raw_prefix": url[:15] + "..." if len(url) > 15 else url
    }


@app.get("/subscribe-waba")
def subscribe_waba(waba_id: str):
    """
    Subscribes the app to the WhatsApp Business Account (WABA)
    so that inbound messages trigger the webhook.
    Pass waba_id as query parameter.
    """
    import requests as req
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.id == 1).first()
        if not tenant:
            return {"status": "error", "message": "Tenant not found. Run /seed first!"}

        token = tenant.whatsapp_access_token

        sub_res = req.post(
            f"https://graph.facebook.com/v18.0/{waba_id}/subscribed_apps",
            params={"access_token": token}
        ).json()

        return {
            "status": "success",
            "waba_id": waba_id,
            "subscription_result": sub_res
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        db.close()
