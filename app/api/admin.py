from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
import requests

from app.db.database import get_db
from app.db.models import Tenant
from app.core.config import settings

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/connect-whatsapp", response_class=HTMLResponse)
def connect_whatsapp_form(db: Session = Depends(get_db)):
    """
    Form admin per collegare le credenziali WhatsApp (Meta) a un tenant esistente.
    Protetto da una password segreta (ADMIN_SECRET).
    """
    tenants = db.query(Tenant).order_by(Tenant.id).all()
    options = "\n".join(
        f'<option value="{t.id}">#{t.id} — {t.name} '
        f'({"WhatsApp già collegato" if t.whatsapp_phone_number_id else "da collegare"})</option>'
        for t in tenants
    )

    return f"""
    <html>
    <head>
        <meta charset="utf-8">
        <title>Admin — Collega WhatsApp</title>
        <style>
            body {{ font-family: -apple-system, sans-serif; background: #f7f9fb; display: flex; justify-content: center; padding: 40px 20px; margin: 0; }}
            .card {{ background: white; padding: 32px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.06); max-width: 480px; width: 100%; }}
            h1 {{ font-size: 20px; margin-bottom: 24px; color: #1a202c; }}
            label {{ display: block; font-size: 13px; font-weight: 600; color: #334155; margin-bottom: 6px; margin-top: 16px; }}
            input, select {{ width: 100%; padding: 10px 12px; border: 1px solid #cbd5e1; border-radius: 6px; font-size: 14px; box-sizing: border-box; }}
            button {{ margin-top: 28px; width: 100%; background-color: #2563eb; color: white; border: none; padding: 12px; border-radius: 6px; font-size: 15px; font-weight: 600; cursor: pointer; }}
            .hint {{ font-size: 12px; color: #94a3b8; margin-top: 4px; }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>🔧 Collega credenziali WhatsApp a un tenant</h1>
            <form method="post" action="/admin/connect-whatsapp">
                <label for="admin_secret">Password admin</label>
                <input type="password" id="admin_secret" name="admin_secret" required>

                <label for="tenant_id">Tenant</label>
                <select id="tenant_id" name="tenant_id" required>
                    {options}
                </select>

                <label for="phone_number_id">Phone Number ID (Meta)</label>
                <input type="text" id="phone_number_id" name="phone_number_id" required>

                <label for="access_token">Access Token (Meta)</label>
                <input type="text" id="access_token" name="access_token" required>

                <label for="waba_id">WABA ID (opzionale — iscrive subito il webhook)</label>
                <input type="text" id="waba_id" name="waba_id">
                <div class="hint">Se lo inserisci, colleghiamo automaticamente il webhook a questo WABA. Puoi anche lasciarlo vuoto e farlo dopo a parte.</div>

                <button type="submit">Salva e collega</button>
            </form>
        </div>
    </body>
    </html>
    """


@router.post("/connect-whatsapp", response_class=HTMLResponse)
def connect_whatsapp_submit(
    admin_secret: str = Form(...),
    tenant_id: int = Form(...),
    phone_number_id: str = Form(...),
    access_token: str = Form(...),
    waba_id: str = Form(default=""),
    db: Session = Depends(get_db),
):
    if admin_secret != settings.ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Password admin errata.")

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant non trovato.")

    tenant.whatsapp_phone_number_id = phone_number_id
    tenant.whatsapp_access_token = access_token
    db.commit()

    subscription_note = "Nessun WABA ID fornito: iscrizione webhook da fare a parte."
    if waba_id:
        try:
            sub_res = requests.post(
                f"https://graph.facebook.com/v18.0/{waba_id}/subscribed_apps",
                params={"access_token": access_token},
            ).json()
            subscription_note = f"Iscrizione webhook al WABA: {sub_res}"
        except Exception as e:
            subscription_note = f"Iscrizione webhook fallita: {e}"

    return f"""
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: -apple-system, sans-serif; background: #f7f9fb; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }}
            .card {{ background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.06); max-width: 460px; text-align: center; }}
            h1 {{ color: #16a34a; font-size: 22px; margin-bottom: 12px; }}
            p {{ color: #64748b; font-size: 14px; line-height: 1.5; }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>✅ WhatsApp collegato</h1>
            <p>Tenant #{tenant.id} ({tenant.name}) ora ha le credenziali WhatsApp salvate.</p>
            <p style="font-size:12px; color:#94a3b8;">{subscription_note}</p>
        </div>
    </body>
    </html>
    """
