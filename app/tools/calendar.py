from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from sqlalchemy.orm import Session
from app.core.config import settings

TENANT_TIMEZONE = "Europe/Rome"


class CalendarNotConnectedError(RuntimeError):
    """Il professionista non ha ancora collegato/autorizzato Google Calendar."""
    pass


class CalendarTemporarilyUnavailableError(Exception):
    """Google Calendar e' temporaneamente irraggiungibile (rete, outage, errore transitorio)."""
    pass


def get_calendar_service(tenant, db: Session):
    """
    Initializes and returns the Google Calendar API client using the Tenant's OAuth credentials.
    Auto-refreshes the access token if it is expired.
    """
    if not tenant.google_access_token:
        raise CalendarNotConnectedError(
            "Calendar non collegato. Il professionista deve autorizzare l'accesso tramite la pagina web di onboarding."
        )

    creds = Credentials(
        token=tenant.google_access_token,
        refresh_token=tenant.google_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        expiry=tenant.google_token_expiry
    )

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            tenant.google_access_token = creds.token
            tenant.google_token_expiry = creds.expiry
            db.commit()
            db.refresh(tenant)
        except Exception as e:
            print(f"Failed to refresh Google OAuth token for tenant {tenant.id}: {e}")
            raise CalendarNotConnectedError("Connessione a Google Calendar scaduta. E' necessario ripetere l'accesso.")

    try:
        return build('calendar', 'v3', credentials=creds)
    except Exception as e:
        print(f"Error building Google Calendar service: {e}")
        raise CalendarTemporarilyUnavailableError("Impossibile contattare Google Calendar in questo momento.")


def _to_local_naive(iso_str: str, tz_name: str) -> datetime:
    """
    Converte una stringa ISO (tipicamente in UTC, con 'Z') in un datetime "naive"
    (senza timezone) espresso pero' nell'ora locale del tenant. Cosi' possiamo
    confrontarlo direttamente con gli slot di lavoro, calcolati anch'essi in ora locale.
    """
    dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
    local_dt = dt.astimezone(ZoneInfo(tz_name))
    return local_dt.replace(tzinfo=None)


def get_busy_intervals(tenant, date_str: str, db: Session) -> list:
    """
    Retrieves all busy intervals for a given date (YYYY-MM-DD), usando l'endpoint
    freebusy.query di Google. Rispetto a events().list, questo endpoint:
    - ignora automaticamente gli eventi marcati come "disponibile/trasparente"
      (es. festivita', "Santo del giorno"), che quindi NON bloccano piu' lo slot
    - gestisce automaticamente anche gli eventi "tutto il giorno"
    - non richiede di leggere titoli/descrizioni degli eventi (piu' rispettoso
      della privacy del professionista)
    Ritorna una lista di tuple (start_datetime, end_datetime) in ora locale del tenant.
    """
    service = get_calendar_service(tenant, db)

    start_dt = datetime.strptime(date_str, "%Y-%m-%d")
    end_dt = start_dt + timedelta(days=1)

    # Rendiamo esplicito l'offset del fuso orario direttamente nel timestamp
    # (es. "...+02:00"), invece di affidarci solo al campo "timeZone" separato:
    # senza offset esplicito, Google a volte rifiuta la richiesta con 400 Bad Request.
    tz = ZoneInfo(TENANT_TIMEZONE)
    start_dt_aware = start_dt.replace(tzinfo=tz)
    end_dt_aware = end_dt.replace(tzinfo=tz)

    body = {
        "timeMin": start_dt_aware.isoformat(),
        "timeMax": end_dt_aware.isoformat(),
        "timeZone": TENANT_TIMEZONE,
        "items": [{"id": "primary"}],
    }

    try:
        result = service.freebusy().query(body=body).execute()
    except Exception as e:
        print(f"Error querying Google Calendar freebusy: {e}")
        raise CalendarTemporarilyUnavailableError("Impossibile leggere la disponibilita' dal calendario in questo momento.")

    busy_raw = result.get("calendars", {}).get("primary", {}).get("busy", [])

    busy = []
    for b in busy_raw:
        try:
            start_val = _to_local_naive(b["start"], TENANT_TIMEZONE)
            end_val = _to_local_naive(b["end"], TENANT_TIMEZONE)
            busy.append((start_val, end_val))
        except Exception as ex:
            print(f"Error parsing freebusy interval: {ex}")

    return busy


def get_available_slots(tenant, date_str: str, db: Session) -> list:
    """
    Calculates and returns available appointment slots for a given date (YYYY-MM-DD).
    Usa la configurazione del tenant: orari di lavoro, durata slot, buffer tra appuntamenti.
    Applica anche un margine minimo di preavviso se la data richiesta e' oggi.
    """
    slot_duration = getattr(tenant, "slot_duration_minutes", None) or 30
    buffer_minutes = getattr(tenant, "buffer_minutes", None) or 0
    work_start_str = getattr(tenant, "work_start_time", None) or "09:00"
    work_end_str = getattr(tenant, "work_end_time", None) or "17:00"

    busy_intervals = get_busy_intervals(tenant, date_str, db)
    # Il buffer viene applicato "spingendo" la fine di ogni evento occupato di N minuti:
    # cosi' il prossimo slot puo' iniziare solo dopo che il buffer e' trascorso.
    padded_busy = [(s, e + timedelta(minutes=buffer_minutes)) for s, e in busy_intervals]

    base_date = datetime.strptime(date_str, "%Y-%m-%d")
    wh, wm = map(int, work_start_str.split(":"))
    eh, em = map(int, work_end_str.split(":"))
    work_start = base_date.replace(hour=wh, minute=wm, second=0, microsecond=0)
    work_end = base_date.replace(hour=eh, minute=em, second=0, microsecond=0)

    # Margine minimo di preavviso, solo se la data richiesta e' oggi. Configurabile per tenant.
    min_lead_hours = getattr(tenant, "min_lead_time_hours", None)
    if min_lead_hours is None:
        min_lead_hours = 2
    now = datetime.now()
    earliest_allowed = None
    if base_date.date() == now.date():
        earliest_allowed = now + timedelta(hours=min_lead_hours)

    slots = []
    current_time = work_start
    slot_delta = timedelta(minutes=slot_duration)

    while current_time + slot_delta <= work_end:
        slot_start = current_time
        slot_end = current_time + slot_delta

        if earliest_allowed and slot_start < earliest_allowed:
            current_time += slot_delta
            continue

        is_busy = any(slot_start < b_end and slot_end > b_start for b_start, b_end in padded_busy)

        if not is_busy:
            slots.append(slot_start.strftime("%H:%M"))

        current_time += slot_delta

    return slots


def find_next_available_slots(tenant, start_date_str: str, db: Session, max_days_to_check: int = None):
    """
    Wrapper di ricerca multi-giorno: se il giorno richiesto e' pieno (o non ci sono slot),
    controlla automaticamente i giorni successivi finche' non trova disponibilita', fino al
    limite massimo di giorni prenotabili configurato dal tenant (max_booking_days_ahead).
    Ritorna (date_str, slots_del_giorno_trovato) oppure (None, []) se non trova nulla.
    """
    if max_days_to_check is None:
        max_days_to_check = getattr(tenant, "max_booking_days_ahead", None) or 30

    base_date = datetime.strptime(start_date_str, "%Y-%m-%d")

    for i in range(max_days_to_check):
        check_date_str = (base_date + timedelta(days=i)).strftime("%Y-%m-%d")
        slots = get_available_slots(tenant, check_date_str, db)
        if slots:
            return check_date_str, slots

    return None, []


def create_calendar_event(tenant, date_str: str, time_str: str, summary: str, description: str, db: Session) -> str:
    """
    Creates a new Google Calendar event under the Tenant's account.
    """
    service = get_calendar_service(tenant, db)

    start_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    end_dt = start_dt + timedelta(minutes=getattr(tenant, "slot_duration_minutes", None) or 30)

    event = {
        'summary': summary,
        'description': description,
        'start': {'dateTime': start_dt.isoformat(), 'timeZone': TENANT_TIMEZONE},
        'end': {'dateTime': end_dt.isoformat(), 'timeZone': TENANT_TIMEZONE},
    }

    try:
        created_event = service.events().insert(calendarId='primary', body=event).execute()
        return created_event.get('id')
    except (CalendarNotConnectedError, CalendarTemporarilyUnavailableError):
        raise
    except Exception as e:
        print(f"Error creating Google Calendar event: {e}")
        raise CalendarTemporarilyUnavailableError("Impossibile creare l'evento sul calendario in questo momento.")


def delete_calendar_event(tenant, event_id: str, db: Session) -> None:
    """
    Deletes an existing Google Calendar event.
    Used when an appointment is rescheduled or cancelled, to free up the old slot.
    """
    service = get_calendar_service(tenant, db)
    try:
        service.events().delete(calendarId='primary', eventId=event_id).execute()
    except Exception as e:
        # Se l'evento non esiste piu' (es. gia' cancellato manualmente), non blocchiamo il flusso.
        print(f"Warning: could not delete calendar event {event_id}: {e}")
