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

    # Fuso orario del professionista (per ora usato solo come riferimento futuro;
    # la logica attuale in calendar.py usa ancora una costante fissa Europe/Rome)
    timezone = Column(String, default="Europe/Rome", nullable=False)

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
