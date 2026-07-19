import os
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from sqlalchemy.orm import Session
from app.core.config import settings

def get_calendar_service(tenant, db: Session):
    """
    Initializes and returns the Google Calendar API client using the Tenant's OAuth credentials.
    Auto-refreshes the access token if it is expired.
    """
    if not tenant.google_access_token:
        raise RuntimeError(
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
    
    # Check if expired and refresh
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            # Update DB with new token & expiry
            tenant.google_access_token = creds.token
            tenant.google_token_expiry = creds.expiry
            db.commit()
            db.refresh(tenant)
        except Exception as e:
            print(f"Failed to refresh Google OAuth token for tenant {tenant.id}: {e}")
            raise RuntimeError("Connessione a Google Calendar scaduta. È necessario ripetere l'accesso.")
            
    return build('calendar', 'v3', credentials=creds)

def get_busy_intervals(tenant, date_str: str, db: Session) -> list:
    """
    Retrieves all busy intervals (existing events) for a given date (YYYY-MM-DD).
    Returns a list of tuples: (start_time_datetime, end_time_datetime).
    """
    try:
        service = get_calendar_service(tenant, db)
    except RuntimeError as re_err:
        # Propagate credentials authorization/refresh warnings
        raise re_err
    except Exception as e:
        print(f"Calendar Service Error: {e}")
        return []

    # Define start and end of the query day
    start_dt = datetime.strptime(date_str, "%Y-%m-%d")
    end_dt = start_dt + timedelta(days=1)
    
    time_min = start_dt.isoformat() + "Z"
    time_max = end_dt.isoformat() + "Z"
    
    try:
        # Using primary calendar as default
        events_result = service.events().list(
            calendarId='primary',
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        busy = []
        for event in events:
            start = event['start'].get('dateTime') or event['start'].get('date')
            end = event['end'].get('dateTime') or event['end'].get('date')
            
            if start and end:
                start_clean = start.split('+')[0].split('Z')[0]
                end_clean = end.split('+')[0].split('Z')[0]
                
                try:
                    start_val = datetime.fromisoformat(start_clean)
                    end_val = datetime.fromisoformat(end_clean)
                    busy.append((start_val, end_val))
                except Exception as ex:
                    print(f"Error parsing date format: {ex}")
        return busy
    except Exception as e:
        print(f"Error querying Google Calendar events: {e}")
        return []

def get_available_slots(tenant, date_str: str, db: Session, slot_duration_minutes: int = 30) -> list:
    """
    Calculates and returns available appointment slots for a given date (YYYY-MM-DD).
    Working hours are fixed between 09:00 and 17:00.
    """
    busy_intervals = get_busy_intervals(tenant, date_str, db)
    
    # Define working hours
    base_date = datetime.strptime(date_str, "%Y-%m-%d")
    work_start = base_date.replace(hour=9, minute=0, second=0, microsecond=0)
    work_end = base_date.replace(hour=17, minute=0, second=0, microsecond=0)
    
    slots = []
    current_time = work_start
    slot_delta = timedelta(minutes=slot_duration_minutes)
    
    while current_time + slot_delta <= work_end:
        slot_start = current_time
        slot_end = current_time + slot_delta
        
        # Check if the slot overlaps with any busy intervals
        is_busy = False
        for b_start, b_end in busy_intervals:
            if slot_start < b_end and slot_end > b_start:
                is_busy = True
                break
                
        if not is_busy:
            slots.append(slot_start.strftime("%H:%M"))
            
        current_time += slot_delta
        
    return slots

def create_calendar_event(tenant, date_str: str, time_str: str, summary: str, description: str, db: Session) -> str:
    """
    Creates a new Google Calendar event under the Tenant's account.
    """
    service = get_calendar_service(tenant, db)
    
    start_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    end_dt = start_dt + timedelta(minutes=30)
    
    event = {
        'summary': summary,
        'description': description,
        'start': {
            'dateTime': start_dt.isoformat(),
            'timeZone': 'UTC',
        },
        'end': {
            'dateTime': end_dt.isoformat(),
            'timeZone': 'UTC',
        },
    }
    
    try:
        created_event = service.events().insert(
            calendarId='primary',
            body=event
        ).execute()
        return created_event.get('id')
    except Exception as e:
        print(f"Error creating Google Calendar event: {e}")
        raise e
