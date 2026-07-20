from fastapi import FastAPI
from app.db.database import engine, Base
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
def seed_database():
    """
    Seeds initial Tenant 1 (Dr. Rossi) in the production database.
    """
    db = SessionLocal()
    tenant = db.query(Tenant).filter(Tenant.id == 1).first()
    if not tenant:
        tenant = Tenant(
            id=1,
            name="Dr. Rossi (Dentista)",
            whatsapp_phone_number_id="WABA-ROSSI-111",
            whatsapp_access_token="rossi_mock_token"
        )
        db.add(tenant)
        db.commit()
        db.close()
        return {"status": "success", "message": "Tenant 1 (Dr. Rossi) creato con successo nel database!"}
    db.close()
    return {"status": "already_exists", "message": "Tenant 1 (Dr. Rossi) esiste già nel database."}

