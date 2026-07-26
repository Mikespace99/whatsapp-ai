from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from app.db.models import UserSession, Appointment
from app.ai.engine import extract_intent, extract_datetime, generate_conversational_reply
from app.tools.calendar import (
    get_available_slots,
    find_next_available_slots,
    create_calendar_event,
    delete_calendar_event,
    CalendarNotConnectedError,
    CalendarTemporarilyUnavailableError,
)
from app.tools.slot_filter import filter_slots_by_preference
from app.whatsapp.sender import send_whatsapp_message

IT_WEEKDAYS = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
IT_MONTHS = [
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"
]

TIME_PREFERENCE_IT = {"morning": "la mattina", "afternoon": "il pomeriggio", "evening": "la sera"}


# ---------------------------------------------------------------------------
# Helper di formattazione
# ---------------------------------------------------------------------------

def _format_date_it(date_str: str) -> str:
    """Formatta una data YYYY-MM-DD in italiano, es. 'lunedì 27 luglio', senza dipendere dal locale del server."""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return f"{IT_WEEKDAYS[d.weekday()]} {d.day} {IT_MONTHS[d.month - 1]}"


def _slot_duration(tenant) -> int:
    return getattr(tenant, "slot_duration_minutes", None) or 30


# ---------------------------------------------------------------------------
# Messaggi deterministici (Response Generator "fedele ai fatti"):
# nessuno di questi passa dall'AI — sono costruiti in codice con i dati reali,
# cosi' non c'e' possibilita' che vengano inventate date/orari inesistenti.
# ---------------------------------------------------------------------------

def _msg_calendar_not_connected(tenant) -> str:
    return (
        f"Calendario non configurato.\n"
        f"L'assistente di {tenant.name} non e' al momento in grado di accedere al calendario."
    )


def _msg_calendar_unavailable() -> str:
    return "Spiacenti, il sistema di prenotazione e' momentaneamente fuori servizio. Riprova tra qualche minuto."


def _msg_no_availability(max_days: int) -> str:
    return (
        f"Mi dispiace, non trovo disponibilita' nei prossimi {max_days} giorni. "
        f"Ti consiglio di contattare direttamente lo studio per altre opzioni."
    )


def _msg_propose_slots(date_str: str, slots: list, is_different_day: bool = False) -> str:
    date_fmt = _format_date_it(date_str)
    slots_str = "\n".join(f"- {s}" for s in slots)
    if is_different_day:
        return (
            f"Il giorno richiesto era pieno. La prima data disponibile e' {date_fmt}, con questi orari:\n"
            f"{slots_str}\n\nQuale preferisci?"
        )
    return f"Per {date_fmt} ho queste disponibilita':\n{slots_str}\n\nQuale orario preferisci?"


def _msg_no_preference_slots(date_str: str, preference: str, fallback_slots: list) -> str:
    date_fmt = _format_date_it(date_str)
    pref_it = TIME_PREFERENCE_IT.get(preference, "quella fascia oraria")
    slots_str = "\n".join(f"- {s}" for s in fallback_slots)
    return f"Non ho disponibilita' {pref_it} per {date_fmt}. Questi sono gli orari liberi:\n{slots_str}\n\nQuale preferisci?"


def _msg_slot_no_longer_available(date_str: str, slots: list) -> str:
    date_fmt = _format_date_it(date_str)
    if not slots:
        return f"Mi dispiace, quell'orario per {date_fmt} non e' piu' disponibile e non ci sono altre fasce libere quel giorno."
    slots_str = "\n".join(f"- {s}" for s in slots)
    return f"Mi dispiace, quell'orario per {date_fmt} non e' piu' disponibile. Fasce libere aggiornate:\n{slots_str}"


def _msg_confirmation_prompt(date_str: str, time_str: str, action: str) -> str:
    date_fmt = _format_date_it(date_str)
    verbo = "spostare l'appuntamento a" if action == "reschedule_appointment" else "prenotare per"
    return f"Perfetto, vuoi {verbo} {date_fmt} alle {time_str}? Rispondi 'sì' per confermare, oppure dimmi un altro giorno/orario."

def _msg_booking_confirmed(date_str: str, time_str: str) -> str:
    return f"✅ Appuntamento confermato per {_format_date_it(date_str)} alle {time_str}."


def _msg_reschedule_confirmed(date_str: str, time_str: str) -> str:
    return f"✅ Appuntamento spostato: nuovo orario {_format_date_it(date_str)} alle {time_str}."


def _msg_cancel_confirmed(date_str: str, time_str: str) -> str:
    return f"✅ Appuntamento del {_format_date_it(date_str)} alle {time_str} cancellato."


def _msg_appointment_found(date_str: str, time_str: str) -> str:
    return f"Il tuo prossimo appuntamento e' per {_format_date_it(date_str)} alle {time_str}."


def _msg_appointment_not_found() -> str:
    return "Non risulta nessun appuntamento attivo a tuo nome. Vuoi prenotarne uno?"


def _msg_cancel_failed_no_appointment() -> str:
    return "Non trovo nessun appuntamento attivo da cancellare a tuo nome."


def _msg_reschedule_failed_no_appointment() -> str:
    return "Non trovo nessun appuntamento attivo da spostare a tuo nome. Vuoi prenotarne uno nuovo?"


def _msg_nothing_to_confirm() -> str:
    return "Non ho nessuna prenotazione in sospeso da confermare al momento. Vuoi fissare un appuntamento?"


def _msg_denied_ask_again() -> str:
    return "Va bene, nessun problema! Per quale giorno e orario preferisci allora?"


# ---------------------------------------------------------------------------
# Logica di dominio
# ---------------------------------------------------------------------------

def get_active_appointment(tenant, phone_number, db):
    """Trova il prossimo appuntamento attivo (non cancellato, non ancora passato) del cliente."""
    return db.query(Appointment).filter(
        Appointment.tenant_id == tenant.id,
        Appointment.customer_phone == phone_number,
        Appointment.status == "confirmed",
        Appointment.start_time >= datetime.now()
    ).order_by(Appointment.start_time.asc()).first()


def _resolve_slots_for_day(tenant, target_date, db, time_preference):
    """
    Trova gli slot per il giorno richiesto. Se quel giorno e' completamente pieno,
    cerca automaticamente nei giorni successivi (fino al limite max_booking_days_ahead
    del tenant). Applica poi il filtro di preferenza oraria, se espresso.

    Ritorna: (resolved_date, slots_da_proporre, all_slots_del_giorno_trovato, is_different_day)
    """
    all_slots = get_available_slots(tenant, target_date, db)
    resolved_date = target_date
    is_different_day = False

    if not all_slots:
        found_date, multi_slots = find_next_available_slots(tenant, target_date, db)
        if not multi_slots:
            return resolved_date, [], [], False
        resolved_date = found_date
        all_slots = multi_slots
        is_different_day = (found_date != target_date)

    slots = filter_slots_by_preference(all_slots, time_preference)
    return resolved_date, slots, all_slots, is_different_day


def _create_appointment_record(tenant, phone_number, customer_name, target_date, target_time, db):
    """Crea l'evento su Google Calendar e il record Appointment nel DB. Ritorna l'oggetto Appointment."""
    summary = f"Appuntamento con {customer_name}"
    description = f"Creato tramite Assistente WhatsApp AI\nCliente: {phone_number}"

    event_id = create_calendar_event(
        tenant=tenant, date_str=target_date, time_str=target_time,
        summary=summary, description=description, db=db
    )

    start_dt = datetime.strptime(f"{target_date} {target_time}", "%Y-%m-%d %H:%M")
    end_dt = start_dt + timedelta(minutes=_slot_duration(tenant))

    appointment = Appointment(
        tenant_id=tenant.id, customer_phone=phone_number, customer_name=customer_name,
        start_time=start_dt, end_time=end_dt, google_event_id=event_id, status="confirmed"
    )
    db.add(appointment)
    return appointment


def _reset_session(session):
    session.state = "idle"
    session.temp_date = None
    session.temp_time = None
    session.pending_action = None


def process_incoming_message(phone_number: str, customer_name: str, message: str, tenant, db: Session) -> str:
    """
    State machine and booking logic running under a specific Tenant context.

    Flusso per creare/spostare un appuntamento:
    select_time (scelta data/ora) -> awaiting_confirmation (conferma esplicita) -> evento creato.
    Nessun evento viene mai creato senza un "si" esplicito dell'utente sull'orario proposto.
    """
    # 1. Retrieve or create tenant-isolated user session
    session = db.query(UserSession).filter(
        UserSession.tenant_id == tenant.id,
        UserSession.customer_phone == phone_number
    ).first()

    if not session:
        session = UserSession(tenant_id=tenant.id, customer_phone=phone_number, state="idle")
        db.add(session)
        db.commit()
        db.refresh(session)

    is_awaiting_confirmation = (session.state == "awaiting_confirmation")

    # 2. Livello 2 (LLM): estrae SOLO intent + entita' grezze, incluso il testo
    # dell'espressione temporale (nessun calcolo di date qui).
    try:
        parsed_intent = extract_intent(message, awaiting_confirmation=is_awaiting_confirmation)
    except Exception as e:
        print(f"AI Engine Error: {e}")
        error_msg = "Siamo spiacenti, il servizio di intelligenza artificiale non e' al momento configurato o disponibile."
        send_whatsapp_message(phone_number, error_msg, tenant.whatsapp_access_token, tenant.whatsapp_phone_number_id)
        return error_msg

    intent = parsed_intent.intent
    extracted_name = parsed_intent.customer_name

    # 2b. Livello 3 (dateparser, deterministico): trasforma la time_expression
    # grezza in data/ora/fascia strutturate. Nessun LLM coinvolto in questo passo.
    date_info = extract_datetime(parsed_intent.time_expression)
    extracted_date = date_info["date"]
    extracted_time = date_info["time"]
    extracted_time_preference = date_info["period"]

    print(
        f"[Tenant: {tenant.name}] Extracted -> Intent: {intent}, TimeExpr: '{parsed_intent.time_expression}' "
        f"-> Date: {extracted_date}, Time: {extracted_time}, Preference: {extracted_time_preference}, Name: {extracted_name}"
    )

    if extracted_name:
        session.known_customer_name = extracted_name
        db.commit()
    if session.known_customer_name:
        customer_name = session.known_customer_name

    # 3. Contextual override: se siamo in attesa della scelta di un orario (non ancora della
    # conferma), usa pending_action per sapere se completare un booking o un reschedule.
    if session.state == "select_time" and extracted_time and intent in ["other", "book_appointment", "reschedule_appointment"]:
        pending = getattr(session, "pending_action", None) or "book_appointment"
        intent = pending
        if not extracted_date:
            extracted_date = session.temp_date

    reply_text = ""

    if intent == "greeting":
        _reset_session(session)
        db.commit()
        reply_text = generate_conversational_reply("greeting", message, tenant)

    elif intent == "check_availability":
        target_date = extracted_date or session.temp_date
        if not target_date:
            target_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

        try:
            resolved_date, slots, all_slots, is_different_day = _resolve_slots_for_day(
                tenant, target_date, db, extracted_time_preference
            )
            max_days = getattr(tenant, "max_booking_days_ahead", None) or 30

            if not all_slots:
                reply_text = _msg_no_availability(max_days)
                _reset_session(session)
            elif not slots:
                fallback_slots = filter_slots_by_preference(all_slots, None)
                reply_text = _msg_no_preference_slots(resolved_date, extracted_time_preference, fallback_slots)
                session.state = "select_time"
                session.temp_date = resolved_date
                session.pending_action = "book_appointment"
            else:
                reply_text = _msg_propose_slots(resolved_date, slots, is_different_day)
                session.state = "select_time"
                session.temp_date = resolved_date
                session.pending_action = "book_appointment"

            db.commit()
        except CalendarNotConnectedError:
            reply_text = _msg_calendar_not_connected(tenant)
        except CalendarTemporarilyUnavailableError:
            reply_text = _msg_calendar_unavailable()
        except Exception as e:
            print(f"Error handling availability check: {e}")
            reply_text = "Si e' verificato un errore nel controllo della disponibilita'. Riprova piu' tardi."

    elif intent == "book_appointment":
        target_date = extracted_date or session.temp_date
        if not target_date:
            # Non chiediamo MAI al cliente "che giorno vuoi?" alla cieca: è compito
            # nostro proporre le disponibilità reali, non del cliente indovinarle.
            # Di default proponiamo a partire da domani, come in check_availability.
            target_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        target_time = extracted_time

        if not target_time:
            try:
                resolved_date, slots, all_slots, is_different_day = _resolve_slots_for_day(
                    tenant, target_date, db, extracted_time_preference
                )
                max_days = getattr(tenant, "max_booking_days_ahead", None) or 30

                if not all_slots:
                    reply_text = _msg_no_availability(max_days)
                    _reset_session(session)
                elif not slots:
                    fallback_slots = filter_slots_by_preference(all_slots, None)
                    reply_text = _msg_no_preference_slots(resolved_date, extracted_time_preference, fallback_slots)
                    session.state = "select_time"
                    session.temp_date = resolved_date
                    session.pending_action = "book_appointment"
                else:
                    reply_text = _msg_propose_slots(resolved_date, slots, is_different_day)
                    session.state = "select_time"
                    session.temp_date = resolved_date
                    session.pending_action = "book_appointment"
                db.commit()
            except CalendarNotConnectedError:
                reply_text = _msg_calendar_not_connected(tenant)
            except CalendarTemporarilyUnavailableError:
                reply_text = _msg_calendar_unavailable()
            except Exception as e:
                print(f"Error fetching slots: {e}")
                reply_text = "Non sono riuscito a verificare gli orari per quel giorno. Riprova."
        else:
            # Data e ora presenti: NON prenotiamo ancora. Verifichiamo che lo slot sia
            # davvero disponibile, poi chiediamo conferma esplicita prima di creare l'evento.
            try:
                current_slots = get_available_slots(tenant, target_date, db)
                if target_time not in current_slots:
                    reply_text = _msg_slot_no_longer_available(target_date, current_slots)
                    session.state = "select_time" if current_slots else "idle"
                    session.temp_date = target_date if current_slots else None
                    session.pending_action = "book_appointment" if current_slots else None
                else:
                    session.state = "awaiting_confirmation"
                    session.temp_date = target_date
                    session.temp_time = target_time
                    session.pending_action = "book_appointment"
                    reply_text = _msg_confirmation_prompt(target_date, target_time, "book_appointment")
                db.commit()
            except CalendarNotConnectedError:
                reply_text = _msg_calendar_not_connected(tenant)
            except CalendarTemporarilyUnavailableError:
                reply_text = _msg_calendar_unavailable()
            except Exception as e:
                print(f"Error checking slot before confirmation: {e}")
                reply_text = "Non sono riuscito a verificare quell'orario. Riprova."

    elif intent == "reschedule_appointment":
        existing_appt = get_active_appointment(tenant, phone_number, db)
        if not existing_appt:
            reply_text = _msg_reschedule_failed_no_appointment()
        elif not extracted_date or not extracted_time:
            # Non chiediamo "per quando vuoi spostarlo" alla cieca: proponiamo
            # direttamente le prime disponibilità utili (default: da domani).
            target_date = extracted_date or (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
            try:
                resolved_date, slots, all_slots, is_different_day = _resolve_slots_for_day(
                    tenant, target_date, db, extracted_time_preference
                )
                max_days = getattr(tenant, "max_booking_days_ahead", None) or 30

                if not all_slots:
                    reply_text = _msg_no_availability(max_days)
                    session.state = "idle"
                    session.temp_date = None
                    session.pending_action = None
                elif not slots:
                    fallback_slots = filter_slots_by_preference(all_slots, None)
                    reply_text = _msg_no_preference_slots(resolved_date, extracted_time_preference, fallback_slots)
                    session.state = "select_time"
                    session.temp_date = resolved_date
                    session.pending_action = "reschedule_appointment"
                else:
                    reply_text = _msg_propose_slots(resolved_date, slots, is_different_day)
                    session.state = "select_time"
                    session.temp_date = resolved_date
                    session.pending_action = "reschedule_appointment"
                db.commit()
            except CalendarNotConnectedError:
                reply_text = _msg_calendar_not_connected(tenant)
            except CalendarTemporarilyUnavailableError:
                reply_text = _msg_calendar_unavailable()
            except Exception as e:
                print(f"Error fetching slots for reschedule: {e}")
                reply_text = "Non sono riuscito a verificare gli orari disponibili. Riprova."
        else:
            try:
                current_slots = get_available_slots(tenant, extracted_date, db)
                if extracted_time not in current_slots:
                    reply_text = _msg_slot_no_longer_available(extracted_date, current_slots)
                    session.state = "select_time" if current_slots else "idle"
                    session.temp_date = extracted_date if current_slots else None
                    session.pending_action = "reschedule_appointment" if current_slots else None
                else:
                    session.state = "awaiting_confirmation"
                    session.temp_date = extracted_date
                    session.temp_time = extracted_time
                    session.pending_action = "reschedule_appointment"
                    reply_text = _msg_confirmation_prompt(extracted_date, extracted_time, "reschedule_appointment")
                db.commit()
            except CalendarNotConnectedError:
                reply_text = _msg_calendar_not_connected(tenant)
            except CalendarTemporarilyUnavailableError:
                reply_text = _msg_calendar_unavailable()
            except Exception as e:
                print(f"Error checking slot before reschedule confirmation: {e}")
                reply_text = "Non sono riuscito a verificare quell'orario. Riprova."

    elif intent == "confirm_appointment":
        if session.state != "awaiting_confirmation" or not session.temp_date or not session.temp_time:
            reply_text = _msg_nothing_to_confirm()
        else:
            action = getattr(session, "pending_action", None) or "book_appointment"
            target_date = session.temp_date
            target_time = session.temp_time
            try:
                if action == "reschedule_appointment":
                    existing_appt = get_active_appointment(tenant, phone_number, db)
                    if existing_appt:
                        if existing_appt.google_event_id:
                            delete_calendar_event(tenant, existing_appt.google_event_id, db)
                        existing_appt.status = "cancelled"
                        db.commit()

                _create_appointment_record(tenant, phone_number, customer_name, target_date, target_time, db)
                _reset_session(session)
                db.commit()

                reply_text = (
                    _msg_reschedule_confirmed(target_date, target_time)
                    if action == "reschedule_appointment"
                    else _msg_booking_confirmed(target_date, target_time)
                )
            except CalendarNotConnectedError:
                reply_text = _msg_calendar_not_connected(tenant)
            except CalendarTemporarilyUnavailableError:
                reply_text = _msg_calendar_unavailable()
            except Exception as e:
                print(f"Error finalizing confirmed appointment: {e}")
                reply_text = "C'e' stato un problema nel confermare l'appuntamento. Riprova piu' tardi."

    elif intent == "deny_appointment":
        if session.state == "awaiting_confirmation":
            session.state = "select_time"
            session.temp_time = None
            session.pending_action = session.pending_action or "book_appointment"
            db.commit()
            reply_text = _msg_denied_ask_again()
        else:
            reply_text = generate_conversational_reply("fallback_instruction", message, tenant)

    elif intent == "check_my_appointment":
        appt = get_active_appointment(tenant, phone_number, db)
        reply_text = (
            _msg_appointment_found(appt.start_time.strftime("%Y-%m-%d"), appt.start_time.strftime("%H:%M"))
            if appt else _msg_appointment_not_found()
        )

    elif intent == "cancel_appointment":
        appt = get_active_appointment(tenant, phone_number, db)
        if not appt:
            reply_text = _msg_cancel_failed_no_appointment()
        else:
            try:
                if appt.google_event_id:
                    delete_calendar_event(tenant, appt.google_event_id, db)
                appt.status = "cancelled"
                db.commit()
                reply_text = _msg_cancel_confirmed(appt.start_time.strftime("%Y-%m-%d"), appt.start_time.strftime("%H:%M"))
            except Exception as e:
                print(f"Error cancelling appointment: {e}")
                reply_text = "C'e' stato un problema nel cancellare l'appuntamento. Riprova piu' tardi."

    else:  # intent == "other"
        if session.state == "select_time" and session.temp_date:
            reply_text = f"Sto aspettando la tua scelta per un orario il giorno {_format_date_it(session.temp_date)}. Quale orario preferisci?"
        elif session.state == "awaiting_confirmation" and session.temp_date and session.temp_time:
            reply_text = _msg_confirmation_prompt(session.temp_date, session.temp_time, session.pending_action or "book_appointment")
        else:
            reply_text = generate_conversational_reply("fallback_instruction", message, tenant)

    send_whatsapp_message(
        to=phone_number, text=reply_text,
        token=tenant.whatsapp_access_token, phone_id=tenant.whatsapp_phone_number_id
    )

    return reply_text
