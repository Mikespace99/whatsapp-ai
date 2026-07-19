from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db.models import Tenant
from app.core.config import settings
from google_auth_oauthlib.flow import Flow
from datetime import datetime

router = APIRouter(prefix="/auth")

def get_client_config():
    """
    Constructs the client configuration dictionary dynamically from environment variables.
    """
    return {
        "web": {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.GOOGLE_REDIRECT_URI]
        }
    }

@router.get("/google")
def google_auth_initiate(tenant_id: int, db: Session = Depends(get_db)):
    """
    Initiates Google OAuth 2.0 authorization code flow.
    We pass the tenant_id in the state parameter to map it back upon redirect.
    """
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
        
    flow = Flow.from_client_config(
        get_client_config(),
        scopes=['https://www.googleapis.com/auth/calendar']
    )
    flow.redirect_uri = settings.GOOGLE_REDIRECT_URI
    
    # We request 'offline' access and force consent prompt to ensure
    # Google always issues a refresh_token.
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent',
        state=str(tenant_id)
    )
    
    return RedirectResponse(authorization_url)

@router.get("/google/callback", response_class=HTMLResponse)
def google_auth_callback(code: str, state: str, db: Session = Depends(get_db)):
    """
    Receives authorization code, exchanges it for refresh/access tokens, and saves them.
    """
    try:
        tenant_id = int(state)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid state parameter")
        
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
        
    flow = Flow.from_client_config(
        get_client_config(),
        scopes=['https://www.googleapis.com/auth/calendar']
    )
    flow.redirect_uri = settings.GOOGLE_REDIRECT_URI
    
    try:
        flow.fetch_token(code=code)
        creds = flow.credentials
        
        # Save credentials to tenant
        tenant.google_access_token = creds.token
        if creds.refresh_token:
            tenant.google_refresh_token = creds.refresh_token
        tenant.google_token_expiry = creds.expiry
        
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
    except Exception as e:
        print(f"Error during Google OAuth exchange: {e}")
        raise HTTPException(status_code=500, detail=f"Authentication failed: {str(e)}")
