from fastapi import FastAPI
from app.db.database import engine, Base, SessionLocal
from app.db.models import Tenant
from app.whatsapp.webhook import router as whatsapp_router
from app.api.auth import router as auth_router

# Create SQLite tables if they do not exist
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



