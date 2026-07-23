from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from app.db.models import UserSession, Appointment
from app.ai.engine import extract_intent_and_entities, generate_conversational_reply
from app.tools.calendar import get_available_slots, create_calendar_event, delete_calendar_event
from app.whatsapp.sender import send_whatsapp_message


def get_active_appointment(tenant, phone_number, db):
    """Trova il prossimo appuntamento attivo (non cancellato, non ancora passato) del cliente."""
    return db.query(Appointment).filter(
        Appointment.tenant_id == tenant.id,
        Appointment.customer_phone == phone_number,
        Appointment.status == "confirmed",
        Appointment.start_time >= datetime.now()
    ).order_by(Appointment.start_time.asc()).first()


def process_incoming_message(phone_number: str, customer_name: str, message: str, tenant, db: Session) -> str:
    """
    State machine and booking logic running under a specific Tenant context.
    Updates tenant-isolated user sessions, queries the tenant's Google Calendar,
    and replies using the tenant's WhatsApp API credentials.
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

    # 2. Extract intent and entities (using AI Engine)
    try:
        extracted = extract_intent_and_entities(message)
    except Exception as e:
        print(f"AI Engine Error: {e}")
        error_msg = "Siamo spiacenti, il servizio di intelligenza artificiale non e' al momento configurato o disponibile."
        send_whatsapp_message(phone_number, error_msg, tenant.whatsapp_access_token, tenant.whatsapp_phone_number_id)
        return error_msg

    intent = extracted.get("intent", "other")
    extracted_date = extracted.get("date")
    extracted_time = extracted.get("time")
    extracted_name = extracted.get("name")

    print(f"[Tenant: {tenant.name}] Extracted -> Intent: {intent}, Date: {extracted_date}, Time: {extracted_time}, Name: {extracted_name}")

    # Update customer name if provided
    if extracted_name:
        session.temp_time = extracted_name
        db.commit()

    # 3. Contextual override: if we are expecting a time slot selection
    # and the user responds with something containing a time, force booking intent
    if session.state == "select_time" and extracted_time and intent in ["other", "book_appointment"]:
        intent = "book_appointment"
        if not extracted_date:
            extracted_date = session.temp_date

    # 4. Handle State/Intent Flow
    reply_text = ""

    if intent == "greeting":
        session.state = "idle"
        session.temp_date = None
        session.temp_time = None
        db.commit()
        reply_text = generate_conversational_reply("greeting", message)

    elif intent == "check_availability":
        target_date = extracted_date or session.temp_date
        if not target_date:
            target_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

        try:
            slots = get_available_slots(tenant, target_date, db)
            slots = slots[:3]

            if not slots:
                reply_text = generate_conversational_reply(f"no_slots for {target_date}", message)
                session.state = "idle"
                session.temp_date = None
            else:
                session.state = "select_time"
                session.temp_date = target_date
                slots_str = "\n".join([f"- {s}" for s in slots])
                reply_context = f"available_slots for {target_date}:\n{slots_str}"
                reply_text = generate_conversational_reply(reply_context, message)

            db.commit()
        except RuntimeError as re_err:
            print(f"Calendar Configuration Warning for Tenant {tenant.name}: {re_err}")
            reply_text = (
                f"Calendario non configurato.\n"
                f"L'assistente di {tenant.name} non e' al momento in grado di accedere al calendario."
            )
        except Exception as e:
            print(f"Error handling availability check: {e}")
            reply_text = "Si e' verificato un errore nel controllo della disponibilita'. Riprova piu' tardi."

    elif intent == "book_appointment":
        target_date = extracted_date or session.temp_date
        target_time = extracted_time

        if not target_date:
            reply_text = "Per quale giorno desideri prenotare l'appuntamento?"
            session.state = "select_time"
            db.commit()
        elif not target_time:
            try:
                slots = get_available_slots(tenant, target_date, db)
                slots = slots[:3]
                if not slots:
                    reply_text = f"Non ci sono fasce orarie disponibili per il giorno {target_date}. Prova con un'altra data."
                    session.state = "idle"
                else:
                    session.state = "select_time"
                    session.temp_date = target_date
                    slots_str = "\n".join([f"- {s}" for s in slots])
                    reply_text = f"Per il giorno {target_date} ho queste disponibilita':\n{slots_str}\n\nQuale orario preferisci?"
                db.commit()
            except Exception as e:
                reply_text = "Non sono riuscito a verificare gli orari per quel giorno. Riprova."
        else:
            try:
                summary = f"Appuntamento con {customer_name}"
                description = f"Creato tramite Assistente WhatsApp AI\nCliente: {phone_number}"

                event_id = create_calendar_event(
                    tenant=tenant,
                    date_str=target_date,
                    time_str=target_time,
                    summary=summary,
                    description=description,
                    db=db
                )

                start_dt = datetime.strptime(f"{target_date} {target_time}", "%Y-%m-%d %H:%M")
                end_dt = start_dt + timedelta(minutes=30)

                appointment = Appointment(
                    tenant_id=tenant.id,
                    customer_phone=phone_number,
                    customer_name=customer_name,
                    start_time=start_dt,
                    end_time=end_dt,
                    google_event_id=event_id,
                    status="confirmed"
                )
                db.add(appointment)

                session.state = "idle"
                session.temp_date = None
                session.temp_time = None
                db.commit()

                reply_text = generate_conversational_reply(f"confirmed: {target_date} alle {target_time}", message)

            except RuntimeError as re_err:
                print(f"Calendar Configuration Warning: {re_err}")
                reply_text = (
                    f"Calendario non configurato.\n"
                    f"L'assistente di {tenant.name} non ha potuto completare la prenotazione."
                )
            except Exception as e:
                print(f"Error creating appointment: {e}")
                reply_text = (
                    f"Ho provato a prenotare per il {target_date} alle {target_time}, ma c'e' stato un problema. "
                    "Per favore riprova."
                )

    elif intent == "check_my_appointment":
        appt = get_active_appointment(tenant, phone_number, db)
        if appt:
            reply_text = generate_conversational_reply(
                f"customer_appointment_found: {appt.start_time.strftime('%Y-%m-%d %H:%M')}",
                message
            )
        else:
            reply_text = generate_conversational_reply("customer_appointment_not_found", message)

    elif intent == "cancel_appointment":
        appt = get_active_appointment(tenant, phone_number, db)
        if not appt:
            reply_text = generate_conversational_reply("cancel_failed_no_appointment_found", message)
        else:
            try:
                if appt.google_event_id:
                    delete_calendar_event(tenant, appt.google_event_id, db)
                appt.status = "cancelled"
                db.commit()
                reply_text = generate_conversational_reply(
                    f"cancel_confirmed: era il {appt.start_time.strftime('%Y-%m-%d %H:%M')}",
                    message
                )
            except Exception as e:
                print(f"Error cancelling appointment: {e}")
                reply_text = "C'e' stato un problema nel cancellare l'appuntamento. Riprova piu' tardi."

    elif intent == "reschedule_appointment":
        existing_appt = get_active_appointment(tenant, phone_number, db)
        if not existing_appt:
            reply_text = generate_conversational_reply("reschedule_failed_no_appointment_found", message)
        elif not extracted_date or not extracted_time:
            reply_text = "Per quando vuoi spostare l'appuntamento? (data e orario)"
            session.state = "select_time"
            db.commit()
        else:
            try:
                if existing_appt.google_event_id:
                    delete_calendar_event(tenant, existing_appt.google_event_id, db)
                existing_appt.status = "cancelled"
                db.commit()

                summary = f"Appuntamento con {customer_name}"
                description = f"Creato tramite Assistente WhatsApp AI\nCliente: {phone_number}"

                event_id = create_calendar_event(
                    tenant=tenant,
                    date_str=extracted_date,
                    time_str=extracted_time,
                    summary=summary,
                    description=description,
                    db=db
                )

                start_dt = datetime.strptime(f"{extracted_date} {extracted_time}", "%Y-%m-%d %H:%M")
                end_dt = start_dt + timedelta(minutes=30)

                new_appt = Appointment(
                    tenant_id=tenant.id,
                    customer_phone=phone_number,
                    customer_name=customer_name,
                    start_time=start_dt,
                    end_time=end_dt,
                    google_event_id=event_id,
                    status="confirmed"
                )
                db.add(new_appt)

                session.state = "idle"
                session.temp_date = None
                session.temp_time = None
                db.commit()

                reply_text = generate_conversational_reply(
                    f"reschedule_confirmed: nuovo appuntamento {extracted_date} alle {extracted_time}",
                    message
                )
            except Exception as e:
                print(f"Error rescheduling appointment: {e}")
                reply_text = "C'e' stato un problema nello spostare l'appuntamento. Riprova piu' tardi."

    else:  # intent == "other"
        if session.state == "select_time" and session.temp_date:
            reply_text = f"Sto aspettando la tua scelta per un orario il giorno {session.temp_date}. Quale orario preferisci?"
        else:
            reply_text = generate_conversational_reply("fallback_instruction", message)

    # 5. Send message back to user via WhatsApp using tenant-specific credentials
    send_whatsapp_message(
        to=phone_number,
        text=reply_text,
        token=tenant.whatsapp_access_token,
        phone_id=tenant.whatsapp_phone_number_id
    )

    return reply_text
