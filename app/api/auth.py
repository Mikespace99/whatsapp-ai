from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session
import requests
from datetime import datetime, timedelta
from app.db.database import get_db
from app.db.models import Tenant
from app.core.config import settings

router = APIRouter(prefix="/auth")

@router.get("/google")
def google_auth_initiate(tenant_id: int, db: Session = Depends(get_db)):
    """
    Initiates Google OAuth 2.0 authorization code flow statelessly.
    """
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
        
    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={settings.GOOGLE_CLIENT_ID}"
        f"&redirect_uri={settings.GOOGLE_REDIRECT_URI}"
        "&response_type=code"
        "&scope=https://www.googleapis.com/auth/calendar"
        "&access_type=offline"
        "&prompt=consent"
        f"&state={tenant_id}"
    )
    
    return RedirectResponse(auth_url)

@router.get("/google/callback", response_class=HTMLResponse)
def google_auth_callback(code: str, state: str, db: Session = Depends(get_db)):
    """
    Exchanges authorization code for refresh/access tokens statelessly.
    """
    try:
        tenant_id = int(state)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid state parameter")
        
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
        
    token_url = "https://oauth2.googleapis.com/token"
    payload = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": settings.GOOGLE_REDIRECT_URI
    }
    
    res = requests.post(token_url, data=payload)
    token_data = res.json()
    
    if "error" in token_data:
        err_msg = token_data.get("error_description") or token_data.get("error")
        raise HTTPException(status_code=400, detail=f"Authentication failed: ({token_data.get('error')}) {err_msg}")
        
    tenant.google_access_token = token_data.get("access_token")
    if token_data.get("refresh_token"):
        tenant.google_refresh_token = token_data.get("refresh_token")
        
    expires_in = token_data.get("expires_in", 3600)
    tenant.google_token_expiry = datetime.utcnow() + timedelta(seconds=expires_in)
    
    db.commit()
    
    return """
    <html>
        <head>
            <style>
                body { font-family: sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; background-color: #f7f9fb; }
                .card { text-align: center; background: white; padding: 40px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); max-width: 400px; }
                h1 { color: #2ecc71; font-size: 24px; margin-bottom: 10px; }
                p { color: #64748b; font-size: 15px; line-height: 1.5; }
            </style>
        </head>
        <body>
            <div class="card">
                <h1>Connesso! 🎉</h1>
                <p>Google Calendar è stato collegato con successo al tuo account. Puoi chiudere questa pagina e tornare su WhatsApp.</p>
            </div>
        </body>
    </html>
    """
