from fastapi import APIRouter, Request, Depends, Response
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db.models import Tenant
from app.core.config import settings
from app.tools.booking import process_incoming_message

router = APIRouter()

@router.post("")
def whatsapp_webhook(request: Request, db: Session = Depends(get_db)):
    """
    POST endpoint to receive incoming messages. 
    Routes dynamically to the correct Tenant based on recipient's phone_number_id.
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
    def whatsapp_webhook(request: Request, db: Session = Depends(get_db)):
    """
    POST endpoint to receive incoming messages. 
    Routes dynamically to the correct Tenant based on recipient's phone_number_id.
    """
    try:
        data = await request.json()
    except Exception as e:
        print(f"Error parsing JSON payload: {e}")
        return {"status": "error", "message": "Invalid JSON"}
        
    # LOG COMPLETO del payload ricevuto da Meta
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
        
    # Extract recipient WhatsApp phone number ID (used to identify our tenant)
    metadata = value.get("metadata", {})
    recipient_phone_id = metadata.get("phone_number_id")
    
    print(f"=== RECEIVED phone_number_id from Meta: {recipient_phone_id} ===")
    
    if not recipient_phone_id:
        print("Webhook error: missing phone_number_id in metadata.")
        return {"status": "error", "message": "missing phone_number_id"}
        
    # Query corresponding Tenant
    tenant = db.query(Tenant).filter(
        Tenant.whatsapp_phone_number_id == recipient_phone_id,
        Tenant.is_active == True
    ).first()
    
    if not tenant:
        print(f"Ignoring message: No active tenant found with whatsapp_phone_number_id={recipient_phone_id}")
        print(f"Tenants in DB: {[t.whatsapp_phone_number_id for t in db.query(Tenant).all()]}")
        return {"status": "tenant_not_found"}
        
    message_obj = messages[0]
    sender_phone = message_obj.get("from")
    message_type = message_obj.get("type")
    
    if message_type == "text":
        message_body = message_obj.get("text", {}).get("body", "")
        contact_name = value.get("contacts", [{}])[0].get("profile", {}).get("name", "Cliente")
        
        print(f"Tenant '{tenant.name}' received message from {sender_phone} ({contact_name}): {message_body}")
        
        # Route processing using the specific tenant context
        reply = process_incoming_message(sender_phone, contact_name, message_body, tenant, db)
        
        return {"status": "ok", "reply_sent": reply}
        
    return {"status": "ok", "message": "Ignored non-text message"}
