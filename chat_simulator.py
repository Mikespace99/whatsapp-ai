import sys
import os
from datetime import datetime, timedelta

# Ensure workspace is in python path
workspace_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, workspace_dir)

from sqlalchemy.orm import Session
from app.db.database import SessionLocal, engine, Base
from app.db.models import Tenant, UserSession, Appointment
from app.tools.booking import process_incoming_message


# Mock functions for Offline Mode
def offline_mock_extract_intent(message: str) -> dict:
    msg_lower = message.lower()
    
    # 1. Greetings
    if any(g in msg_lower for g in ["ciao", "hello", "hi", "salve", "buongiorno", "buonasera"]):
        return {"intent": "greeting", "date": None, "time": None, "name": None}
        
    # 2. Check availability
    if any(k in msg_lower for k in ["orari", "disponib", "quando", "libero", "liberi", "slots", "ore"]):
        target_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        if "oggi" in msg_lower:
            target_date = datetime.now().strftime("%Y-%m-%d")
        elif "dopo domani" in msg_lower:
            target_date = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
        return {"intent": "check_availability", "date": target_date, "time": None, "name": None}
        
    # 3. Booking appointment
    # Simple regex extraction for HH:MM
    import re
    time_match = re.search(r'\b(\d{2})[:\.](\d{2})\b', msg_lower)
    if time_match or any(h in msg_lower for h in ["ore 9", "ore 10", "ore 11", "ore 12", "ore 14", "ore 15", "ore 16"]):
        # Extract date
        target_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        if "oggi" in msg_lower:
            target_date = datetime.now().strftime("%Y-%m-%d")
            
        # Extract time
        time_str = "10:00"
        if time_match:
            time_str = f"{int(time_match.group(1)):02d}:{int(time_match.group(2)):02d}"
        else:
            for h in [9, 10, 11, 12, 14, 15, 16]:
                if f"ore {h}" in msg_lower or f"alle {h}" in msg_lower:
                    time_str = f"{h:02d}:00"
                    break
        return {"intent": "book_appointment", "date": target_date, "time": time_str, "name": None}
        
    # 4. Other
    return {"intent": "other", "date": None, "time": None, "name": None}

def offline_mock_generate_reply(context_msg: str, user_message: str) -> str:
    if "greeting" in context_msg:
        return "Ciao! Sono l'assistente virtuale per le prenotazioni. Desideri verificare gli orari disponibili o fissare un appuntamento?"
    elif "available_slots" in context_msg:
        # Extract slots block from context
        slots_part = context_msg.split("available_slots for ")[1]
        date_str = slots_part.split(":\n")[0]
        slots = slots_part.split(":\n")[1]
        return f"Per il giorno {date_str} ho i seguenti orari disponibili:\n{slots}\n\nQuale preferisci? Rispondi indicando l'orario (es. 10:00)."
    elif "no_slots" in context_msg:
        return "Purtroppo non ci sono orari disponibili per la data richiesta. Ti va di provare un altro giorno?"
    elif "confirmed" in context_msg:
        details = context_msg.replace("confirmed: ", "")
        return f"Perfetto! Appuntamento registrato per il giorno {details}. Ti arriverà la conferma via email/calendario."
    else:
        return "Non ho capito bene la tua richiesta. Puoi chiedermi gli orari disponibili (es. 'orari per domani') o prenotare uno slot (es. 'prenota domani alle 15:00')."

def setup_database_and_seed():
    """Create database tables and seed test tenants if empty."""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    
    # Check if tenants exist
    count = db.query(Tenant).count()
    if count == 0:
        print("\n[DB] Database vuoto. Aggiunta dei professionisti di test...")
        rossi = Tenant(
            name="Dr. Rossi (Dentista)",
            whatsapp_phone_number_id="WABA-ROSSI-111",
            whatsapp_access_token="rossi_mock_token"
        )
        bianchi = Tenant(
            name="Avv. Bianchi (Legale)",
            whatsapp_phone_number_id="WABA-BIANCHI-222",
            whatsapp_access_token="bianchi_mock_token"
        )
        db.add(rossi)
        db.add(bianchi)
        db.commit()
        print("[DB] Aggiunti Dr. Rossi (ID=1) e Avv. Bianchi (ID=2) con successo.")
    db.close()

def main():
    setup_database_and_seed()
    db = SessionLocal()
    
    print("\n" + "="*50)
    print("      SIMULATORE CHAT WHATSAPP OFFLINE (SaaS)")
    print("="*50)
    
    # 1. Select Tenant
    tenants = db.query(Tenant).all()
    print("\nProfessionisti Registrati nella Piattaforma:")
    for idx, t in enumerate(tenants, 1):
        print(f" {idx}. {t.name} (WhatsApp Phone ID: {t.whatsapp_phone_number_id})")
        
    choice = input("\nSeleziona il professionista con cui chattare (es. 1 o 2): ").strip()
    try:
        tenant_idx = int(choice) - 1
        tenant = tenants[tenant_idx]
    except (ValueError, IndexError):
        print("Scelta non valida. Uscito.")
        db.close()
        return

    # 2. Select AI Mode
    print("\nModalità AI:")
    print(" 1. Live AI (Richiede OPENAI_API_KEY impostata nel file .env)")
    print(" 2. Mock Offline AI (100% offline, simula le risposte dell'AI localmente)")
    mode = input("Scegli la modalità (1 o 2): ").strip()
    
    if mode == "2":
        print("\n[INFO] Modalità offline attivata. Gli intenti e le risposte sono simulati in locale.")
        # Apply patch
        import app.tools.booking
        app.tools.booking.extract_intent_and_entities = offline_mock_extract_intent
        app.tools.booking.generate_conversational_reply = offline_mock_generate_reply
    else:
        print("\n[INFO] Modalità Live AI attivata. Utilizzo della chiave OpenAI nel file .env.")

    # 3. Simulate Chat Loop
    print("\n" + "-"*50)
    print(f"Chat avviata con: {tenant.name}")
    print("Digita 'esci' per terminare.")
    print("Prova a dire: 'Ciao', 'Quali sono gli orari per domani?', 'Prenota per domani alle 15:00'")
    print("-"*50 + "\n")
    
    customer_phone = "39333999999"
    customer_name = "Mario Rossi"
    
    # Retrieve or create session for debug info
    session = db.query(UserSession).filter(
        UserSession.tenant_id == tenant.id,
        UserSession.customer_phone == customer_phone
    ).first()
    state_str = session.state if session else "idle"
    print(f"[INFO] Stato iniziale sessione DB per {customer_name}: '{state_str}'\n")

    while True:
        try:
            message = input("Tu > ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nUscita...")
            break
            
        if not message:
            continue
        if message.lower() in ["esci", "exit", "quit"]:
            print("Chat terminata. Ciao!")
            break
            
        # Process the message
        print("\n[Elaborazione...]")
        reply = process_incoming_message(
            phone_number=customer_phone,
            customer_name=customer_name,
            message=message,
            tenant=tenant,
            db=db
        )
        
        # Load updated session details for debugging
        db.expire_all()
        session = db.query(UserSession).filter(
            UserSession.tenant_id == tenant.id,
            UserSession.customer_phone == customer_phone
        ).first()
        
        print(f"\nRisposta WhatsApp -> {reply}")
        print(f"[DEBUG DB Sessione] Stato: '{session.state}' | Data Temp: '{session.temp_date}' | Orario Temp: '{session.temp_time}'")
        print("-" * 50 + "\n")
        
    db.close()

if __name__ == "__main__":
    main()
