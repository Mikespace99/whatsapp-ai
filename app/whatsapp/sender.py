import requests

def send_whatsapp_message(to: str, text: str, token: str, phone_id: str) -> dict:
    """
    Sends a text message using the WhatsApp Cloud API with tenant-specific credentials.
    Runs in MOCK mode if credentials are placeholder.
    """
    if not token or not phone_id or token.startswith("your_") or phone_id.startswith("your_"):
        print("\n=== [MOCK WHATSAPP SENDER] ===")
        print(f"Recipient: {to}")
        print(f"Message:   {text}")
        print("===============================\n")
        return {"status": "mock_sent", "recipient": to, "message": text}
        
    url = f"https://graph.facebook.com/v19.0/{phone_id}/messages"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text}
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response_data = response.json()
        
        if response.status_code != 200:
            print(f"WhatsApp Cloud API Error ({response.status_code}): {response_data}")
            
        return response_data
    except Exception as e:
        print(f"Error calling WhatsApp API: {e}")
        return {"status": "error", "message": str(e)}
