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
    """Tests Google Gemini AI via REST API."""
    import requests as req
    api_key = os.environ.get("GOOGLE_AI_API_KEY", "").strip()
    if not api_key:
        return {"status": "error", "message": "GOOGLE_AI_API_KEY non trovata!"}
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={api_key}"
        res = req.post(url, headers={"Content-Type": "application/json"},
                       json={"contents": [{"parts": [{"text": "Rispondi solo con: OK"}]}]})
        if res.status_code != 200:
            return {"status": "error", "http_status": res.status_code, "error": res.text}
        reply = res.json()["candidates"][0]["content"]["parts"][0]["text"]
        return {"status": "success", "key_preview": f"{api_key[:8]}...", "ai_response": reply}
    except Exception as e:
        return {"status": "error", "error": str(e)}

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

        # Subscribe app to WABA
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
@app.get("/debug-db")
def debug_db():
    """
    Debug temporaneo: verifica quale database sta usando l'app,
    senza esporre credenziali sensibili.
    """
    from app.core.config import settings
    url = settings.DATABASE_URL
    
    db_type = "postgres" if url.startswith("postgres") else "sqlite" if url.startswith("sqlite") else "unknown"
    
    # Maschera tutto ciò che precede "@" (contiene user:password)
    if "@" in url:
        host_part = url.split("@", 1)[1]
    else:
        host_part = url  # caso sqlite, nessuna password da mascherare
    
    return {
        "db_type": db_type,
        "host_masked": host_part,
        "raw_prefix": url[:15] + "..." if len(url) > 15 else url
    }



from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, UniqueConstraint
from datetime import datetime
from app.db.database import Base


class Tenant(Base):
    __tablename__ = "tenants"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)  # nome visualizzato / nome studio (usato dal bot nei messaggi)

    # --- Dati anagrafici del professionista (raccolti in fase di onboarding) ---
    title = Column(String, nullable=True)        # es. "Dott.", "Dott.ssa", "Avv."
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    email = Column(String, unique=True, index=True, nullable=True)
    contact_phone = Column(String, nullable=True)  # telefono amministrativo, NON il numero WhatsApp del bot

    # Meta WhatsApp credentials per professional (populated during onboarding / signup)
    whatsapp_phone_number_id = Column(String, unique=True, index=True, nullable=True)
    whatsapp_access_token = Column(String, nullable=True)

    # Google Calendar OAuth 2.0 Credentials
    google_access_token = Column(String, nullable=True)
    google_refresh_token = Column(String, nullable=True)
    google_token_expiry = Column(DateTime, nullable=True)

    # --- Nuovi campi: configurazione orari di lavoro (impostati in fase di onboarding) ---
    # Orario di apertura/chiusura, in formato "HH:MM" (stessa fascia tutti i giorni lavorativi, per ora)
    work_start_time = Column(String, default="09:00", nullable=False)
    work_end_time = Column(String, default="17:00", nullable=False)

    # Giorni di lavoro: stringa con i giorni separati da virgola, es. "mon,tue,wed,thu,fri"
    # Usiamo una stringa semplice invece di una tabella separata per restare leggeri in questa fase.
    working_days = Column(String, default="mon,tue,wed,thu,fri", nullable=False)

    # Durata di ogni slot/appuntamento, in minuti
    slot_duration_minutes = Column(Integer, default=30, nullable=False)

    # Pausa/cuscinetto tra un appuntamento e il successivo, in minuti
    buffer_minutes = Column(Integer, default=10, nullable=False)

    # Fuso orario del professionista (per ora usato solo come riferimento futuro;
    # la logica attuale in calendar.py usa ancora una costante fissa Europe/Rome)
    timezone = Column(String, default="Europe/Rome", nullable=False)

    # Istruzioni personalizzate per l'AI: testo libero scritto dal professionista
    # (es. tono da usare, informazioni specifiche sullo studio, cosa dire in certi casi).
    # Viene iniettato automaticamente nei prompt ad ogni richiesta per questo tenant.
    custom_instructions = Column(String, nullable=True)

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class UserSession(Base):
    __tablename__ = "user_sessions"
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    customer_phone = Column(String, nullable=False)

    state = Column(String, default="idle")  # idle, select_time, confirming
    temp_date = Column(String, nullable=True)  # YYYY-MM-DD
    temp_time = Column(String, nullable=True)  # HH:MM
    # Quale azione e' in sospeso mentre lo stato e' "select_time": es. "book_appointment"
    # o "reschedule_appointment". Serve per non confondere le due quando l'utente
    # risponde solo con un orario, senza ripetere l'intento.
    pending_action = Column(String, default="book_appointment", nullable=True)
    last_interaction = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # A customer session is unique to a specific professional's channel
    __table_args__ = (
        UniqueConstraint('tenant_id', 'customer_phone', name='uix_tenant_customer'),
    )


class Appointment(Base):
    __tablename__ = "appointments"
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    customer_phone = Column(String, nullable=False)
    customer_name = Column(String, nullable=True)

    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    google_event_id = Column(String, unique=True, nullable=True)
    status = Column(String, default="confirmed")  # confirmed, cancelled
    created_at = Column(DateTime, default=datetime.utcnow)
