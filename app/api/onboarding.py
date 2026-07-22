from fastapi import APIRouter, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Tenant

router = APIRouter(prefix="/onboarding", tags=["Onboarding"])


DAYS = [
    ("mon", "Lunedì"),
    ("tue", "Martedì"),
    ("wed", "Mercoledì"),
    ("thu", "Giovedì"),
    ("fri", "Venerdì"),
    ("sat", "Sabato"),
    ("sun", "Domenica"),
]


@router.get("", response_class=HTMLResponse)
def onboarding_form():
    """
    Landing page: form di registrazione per un nuovo professionista.
    """
    days_checkboxes = "\n".join(
        f'''
        <label class="day-checkbox">
            <input type="checkbox" name="working_days" value="{code}"
                   {"checked" if code in ("mon", "tue", "wed", "thu", "fri") else ""}>
            {label}
        </label>
        '''
        for code, label in DAYS
    )

    return f"""
    <html>
    <head>
        <meta charset="utf-8">
        <title>Registrazione — Assistente Prenotazioni WhatsApp AI</title>
        <style>
            body {{
                font-family: -apple-system, sans-serif;
                background-color: #f7f9fb;
                display: flex;
                justify-content: center;
                padding: 40px 20px;
                margin: 0;
            }}
            .card {{
                background: white;
                padding: 40px;
                border-radius: 12px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.06);
                max-width: 480px;
                width: 100%;
            }}
            h1 {{ font-size: 22px; margin-bottom: 6px; color: #1a202c; }}
            p.subtitle {{ color: #64748b; font-size: 14px; margin-bottom: 28px; }}
            label {{ display: block; font-size: 13px; font-weight: 600; color: #334155; margin-bottom: 6px; margin-top: 18px; }}
            input[type=text], input[type=time], select {{
                width: 100%;
                padding: 10px 12px;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                font-size: 14px;
                box-sizing: border-box;
            }}
            .days-grid {{
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 8px;
                margin-top: 8px;
            }}
            .day-checkbox {{
                display: flex;
                align-items: center;
                gap: 6px;
                font-weight: 400;
                font-size: 14px;
                margin: 0;
            }}
            .day-checkbox input {{ width: auto; }}
            .row {{ display: flex; gap: 16px; }}
            .row > div {{ flex: 1; }}
            button {{
                margin-top: 32px;
                width: 100%;
                background-color: #2563eb;
                color: white;
                border: none;
                padding: 13px;
                border-radius: 6px;
                font-size: 15px;
                font-weight: 600;
                cursor: pointer;
            }}
            button:hover {{ background-color: #1d4ed8; }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>Attiva il tuo assistente WhatsApp</h1>
            <p class="subtitle">Compila i tuoi dati e collega il calendario. Il collegamento del numero WhatsApp verrà completato subito dopo da noi.</p>

            <form method="post" action="/onboarding/register">
                <label for="title">Titolo</label>
                <select id="title" name="title">
                    <option value="Dott.">Dott.</option>
                    <option value="Dott.ssa">Dott.ssa</option>
                    <option value="Avv.">Avv.</option>
                    <option value="Prof.">Prof.</option>
                    <option value="">Nessuno</option>
                </select>

                <div class="row">
                    <div>
                        <label for="first_name">Nome</label>
                        <input type="text" id="first_name" name="first_name" placeholder="Mario" required>
                    </div>
                    <div>
                        <label for="last_name">Cognome</label>
                        <input type="text" id="last_name" name="last_name" placeholder="Rossi" required>
                    </div>
                </div>

                <label for="name">Nome dello studio / attività (mostrato ai pazienti)</label>
                <input type="text" id="name" name="name" placeholder="Es. Studio Dentistico Dott. Rossi" required>

                <div class="row">
                    <div>
                        <label for="email">Email</label>
                        <input type="text" id="email" name="email" placeholder="mario.rossi@email.it" required>
                    </div>
                    <div>
                        <label for="contact_phone">Telefono di contatto</label>
                        <input type="text" id="contact_phone" name="contact_phone" placeholder="333 1234567" required>
                    </div>
                </div>

                <label>Giorni di lavoro</label>
                <div class="days-grid">
                    {days_checkboxes}
                </div>

                <div class="row">
                    <div>
                        <label for="work_start_time">Apertura</label>
                        <input type="time" id="work_start_time" name="work_start_time" value="09:00" required>
                    </div>
                    <div>
                        <label for="work_end_time">Chiusura</label>
                        <input type="time" id="work_end_time" name="work_end_time" value="17:00" required>
                    </div>
                </div>

                <label for="slot_duration_minutes">Durata di ogni appuntamento</label>
                <select id="slot_duration_minutes" name="slot_duration_minutes">
                    <option value="15">15 minuti</option>
                    <option value="20">20 minuti</option>
                    <option value="30" selected>30 minuti</option>
                    <option value="45">45 minuti</option>
                    <option value="60">60 minuti</option>
                </select>

                <button type="submit">Continua e collega Google Calendar →</button>
            </form>
        </div>
    </body>
    </html>
    """


@router.post("/register")
def register_tenant(
    title: str = Form(default=""),
    first_name: str = Form(...),
    last_name: str = Form(...),
    name: str = Form(...),
    email: str = Form(...),
    contact_phone: str = Form(...),
    work_start_time: str = Form(...),
    work_end_time: str = Form(...),
    slot_duration_minutes: int = Form(...),
    working_days: list[str] = Form(default=[]),
    db: Session = Depends(get_db),
):
    """
    Crea un nuovo Tenant (senza credenziali WhatsApp, collegate manualmente in seguito)
    e avvia subito il flusso OAuth di Google Calendar per completare l'onboarding.
    """
    working_days_str = ",".join(working_days) if working_days else "mon,tue,wed,thu,fri"

    tenant = Tenant(
        name=name,
        title=title or None,
        first_name=first_name,
        last_name=last_name,
        email=email,
        contact_phone=contact_phone,
        whatsapp_phone_number_id=None,
        whatsapp_access_token=None,
        work_start_time=work_start_time,
        work_end_time=work_end_time,
        working_days=working_days_str,
        slot_duration_minutes=slot_duration_minutes,
        is_active=True,
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    # Passiamo subito al collegamento di Google Calendar, riusando il flusso OAuth esistente
    return RedirectResponse(url=f"/auth/google?tenant_id={tenant.id}", status_code=303)
