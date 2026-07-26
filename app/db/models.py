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

    # Business rules configurabili: fino a quanti giorni nel futuro si puo' prenotare,
    # e con quante ore minime di preavviso per il giorno stesso ("oggi").
    max_booking_days_ahead = Column(Integer, default=30, nullable=False)
    min_lead_time_hours = Column(Integer, default=2, nullable=False)

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
    temp_date = Column(String, nullable=True)  # YYYY-MM-DD in attesa di conferma/selezione
    temp_time = Column(String, nullable=True)  # HH:MM in attesa di conferma
    known_customer_name = Column(String, nullable=True)  # nome del cliente, se si e' presentato
    # Quale azione e' in sospeso mentre lo stato e' "select_time"/"confirming": es. "book_appointment"
    # o "reschedule_appointment". Serve per non confondere le due quando l'utente
    # risponde solo con un orario, senza ripetere l'intento.
    pending_action = Column(String, default="book_appointment", nullable=True)
    offered_slots = Column(String, nullable=True)  # es. "09:00,09:30,10:00" - slot proposti nell'ultimo messaggio
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


class ProcessedMessage(Base):
    """
    Tiene traccia dei messaggi WhatsApp (per wamid) gia' elaborati, per evitare di
    rispondere due volte quando Meta ri-consegna lo stesso webhook (retry per timeout).
    """
    __tablename__ = "processed_messages"
    id = Column(Integer, primary_key=True, index=True)
    wamid = Column(String, unique=True, index=True, nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
