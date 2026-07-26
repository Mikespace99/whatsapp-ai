from fastapi import APIRouter, Request, Depends, Response, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.db.database import get_db
from app.db.models import Tenant, ProcessedMessage
from app.core.config import settings
from app.tools.booking import process_incoming_message

router = APIRouter()


@router.get("")
async def verify_webhook(request: Request):
    """
    GET endpoint for Meta Webhook verification (global for the platform app).
    """
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode and token:
        if mode == "subscribe" and token == settings.VERIFY_TOKEN:
            print("Webhook verified successfully!")
            return Response(content=challenge, media_type="text/plain")
        else:
            print("Webhook verification failed: token mismatch.")
            return Response(content="Forbidden", status_code=403)

    return Response(content="Bad Request", status_code=400)


@router.post("")
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    POST endpoint to receive incoming messages.
    Risponde subito a Meta (evitando retry per timeout) e processa il messaggio
    in background. Deduplica per wamid: se Meta ri-manda lo stesso messaggio
    (retry), viene ignorato silenziosamente invece di generare una doppia risposta.
    """
    try:
        data = await request.json()
    except Exception as e:
        print(f"Error parsing JSON payload: {e}")
        return {"status": "error", "message": "Invalid JSON"}

    print(f"=== WEBHOOK PAYLOAD RECEIVED ===")
    print(f"Full data: {data}")

    entry = data.get("entry", [])
    if not entry:
        return {"status": "ok"}

    changes = entry[0].get("changes", [])
    if not changes:
        return {"status": "ok"}

    value = changes[0].get("value", {})
    messages = value.get("messages", [])

    if not messages:
        # Ignore status updates (sent, delivered, read)
        print(f"No messages in payload (status update). Value: {value}")
        return {"status": "ok"}

    metadata = value.get("metadata", {})
    recipient_phone_id = metadata.get("phone_number_id")

    print(f"=== RECEIVED phone_number_id from Meta: {recipient_phone_id} ===")

    if not recipient_phone_id:
        print("Webhook error: missing phone_number_id in metadata.")
        return {"status": "error", "message": "missing phone_number_id"}

    tenant = db.query(Tenant).filter(
        Tenant.whatsapp_phone_number_id == recipient_phone_id,
        Tenant.is_active == True
    ).first()

    if not tenant:
        print(f"Ignoring message: No active tenant found with whatsapp_phone_number_id={recipient_phone_id}")
        return {"status": "tenant_not_found"}

    message_obj = messages[0]
    sender_phone = message_obj.get("from")
    message_type = message_obj.get("type")
    wamid = message_obj.get("id")

    # --- Deduplica: se questo wamid e' gia' stato processato, ignora silenziosamente ---
    if wamid:
        already_processed = db.query(ProcessedMessage).filter(ProcessedMessage.wamid == wamid).first()
        if already_processed:
            print(f"Duplicate webhook delivery ignored for wamid={wamid} (Meta retry).")
            return {"status": "duplicate_ignored"}

        try:
            db.add(ProcessedMessage(wamid=wamid, tenant_id=tenant.id))
            db.commit()
        except IntegrityError:
            # Race condition: due retry quasi simultanei. Il primo ha gia' vinto, ignoriamo questo.
            db.rollback()
            print(f"Duplicate webhook delivery (race) ignored for wamid={wamid}.")
            return {"status": "duplicate_ignored"}

    if message_type == "text":
        message_body = message_obj.get("text", {}).get("body", "")
        contact_name = value.get("contacts", [{}])[0].get("profile", {}).get("name", "Cliente")

        print(f"Tenant '{tenant.name}' received message from {sender_phone} ({contact_name}): {message_body}")

        # Rispondiamo subito a Meta con 200 OK; l'elaborazione vera (AI, calendario,
        # invio della risposta WhatsApp) avviene in background, cosi' Meta non rischia
        # di considerare la consegna fallita e ri-mandare lo stesso messaggio.
        background_tasks.add_task(
            process_incoming_message, sender_phone, contact_name, message_body, tenant, db
        )

        return {"status": "accepted"}

    return {"status": "ok", "message": "Ignored non-text message"}
