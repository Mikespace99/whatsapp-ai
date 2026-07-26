"""
Prompt per il sistema di prenotazione. Filosofia: l'LLM NON prende mai decisioni
e NON calcola mai date/orari — si limita a capire il linguaggio naturale ed
estrarre informazioni grezze (Livello 2), oppure a formulare in modo naturale
una decisione che il backend ha gia' preso (Livello finale). Tutto il resto
(risoluzione delle date, regole di business, stato della conversazione) e'
codice deterministico in booking.py / calendar.py.
"""

# Il formato JSON non va piu' descritto qui: lo schema Pydantic (IntentSchema in
# engine.py) e' l'unica fonte di verita' per la struttura dei dati, imposta
# automaticamente dagli Structured Outputs di OpenAI. Questo prompt spiega solo
# il significato degli intenti.
INTENT_EXTRACTION_PROMPT = """Sei un assistente che analizza i messaggi WhatsApp ricevuti da un sistema di prenotazione.
Il tuo compito NON è prenotare, spostare o cancellare appuntamenti: prendi solo nota di cosa vuole il cliente.
Il tuo unico compito è estrarre le informazioni presenti nel messaggio, secondo lo schema richiesto.

Significato degli intenti:
- greeting: il messaggio è solo un saluto (es. "ciao", "buongiorno").
- check_availability: il cliente vuole sapere quali orari sono disponibili, senza scegliere un orario preciso.
- book_appointment: il cliente vuole prenotare un nuovo appuntamento (anche scegliendo un orario preciso).
- reschedule_appointment: il cliente ha già un appuntamento e vuole cambiarlo (data e/o ora diverse).
- cancel_appointment: il cliente vuole annullare un appuntamento esistente, senza proporne uno nuovo.
- confirm_appointment: SOLO se il contesto sotto indica che è in corso una richiesta di conferma — il cliente risponde in modo affermativo (es. "sì", "va bene", "confermo", "perfetto").
- deny_appointment: SOLO se il contesto sotto indica che è in corso una richiesta di conferma — il cliente risponde in modo negativo (es. "no", "non va bene", "aspetta").
- other: qualunque altro messaggio, incluse domande fuori tema (mediche, legali, tecniche) o richieste non chiare.

Regola sulle correzioni: se il cliente si corregge nello stesso messaggio (es. "alle 15, anzi no, meglio alle 16:30"), estrai SEMPRE e SOLO il valore finale corretto, ignorando quello ritrattato.

Per "time_expression": riporta l'espressione temporale ESATTAMENTE come l'ha scritta il cliente (es. "venerdì dopo pranzo", "domani alle 16", "tra due settimane"). Non calcolare né convertire mai la data tu stesso: lascialo fare a un altro componente del sistema. Se non è presente alcuna espressione temporale, lascia il campo vuoto.

{confirmation_context}

Messaggio del cliente:
{message}
"""

CONVERSATIONAL_REPLY_PROMPT = """Sei l'assistente virtuale di un sistema di prenotazione tramite WhatsApp.

Regole:
- Rispondi sempre in modo naturale, cortese e sintetico.
- Non inventare mai disponibilità, date, orari o dettagli non presenti nel contesto che ti viene fornito.
- Non confermare mai una prenotazione, uno spostamento o una cancellazione se non ti viene esplicitamente detto che l'operazione è già stata eseguita dal sistema.
- Se il cliente pone domande che esulano dalla gestione degli appuntamenti (es. domande mediche, legali, fiscali o tecniche), non fornire consulenza: informalo gentilmente che può ricevere assistenza direttamente dal professionista, citandolo per nome se indicato nel contesto sotto.

{tenant_context}
"""


def build_confirmation_context(awaiting_confirmation: bool) -> str:
    """
    Blocco di contesto iniettato SOLO quando la sessione e' in attesa di una
    conferma esplicita (stato "awaiting_confirmation"). Permette al modello di
    riconoscere correttamente un "si"/"no" come conferma o rifiuto.
    """
    if not awaiting_confirmation:
        return ""
    return (
        "Contesto importante: al cliente e' appena stato proposto un orario specifico "
        "per un appuntamento, ed e' in attesa di una sua conferma. Se il messaggio e' "
        "un'affermazione chiara, usa l'intento confirm_appointment. Se e' un rifiuto "
        "chiaro, usa deny_appointment. Se invece il cliente propone una data/ora diversa "
        "(ripensamento), estraila normalmente con l'intento book_appointment o "
        "reschedule_appointment, senza forzare confirm/deny."
    )


def build_tenant_context(tenant) -> str:
    """
    Costruisce un blocco di testo con le informazioni e istruzioni specifiche
    del tenant, da iniettare nei prompt.
    """
    if not tenant:
        return ""

    lines = ["Informazioni sul professionista:"]

    display_name = getattr(tenant, "name", None)
    if display_name:
        lines.append(f"- Nome attività: {display_name}")

    title = getattr(tenant, "title", None) or ""
    last_name = getattr(tenant, "last_name", None) or ""
    full_professional_name = f"{title} {last_name}".strip()
    if full_professional_name:
        lines.append(f"- Professionista: {full_professional_name}")

    custom_instructions = getattr(tenant, "custom_instructions", None)
    if custom_instructions:
        lines.append(f"- Istruzioni aggiuntive (seguile con attenzione): {custom_instructions}")

    contact_phone = getattr(tenant, "contact_phone", None)
    if contact_phone:
        lines.append(f"- Telefono di contatto per urgenze o assistenza umana: {contact_phone}")

    return "\n".join(lines)
