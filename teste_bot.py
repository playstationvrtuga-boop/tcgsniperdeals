import requests
from config import TOKEN, VIP_CHAT_ID

print("TOKEN:", TOKEN[:10] + "..." if TOKEN else "VAZIO")
print("VIP_CHAT_ID:", VIP_CHAT_ID)

url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
payload = {
    "chat_id": VIP_CHAT_ID,
    "text": "TESTE DIRETO TELEGRAM"
}

r = requests.post(url, data=payload, timeout=20)
print("STATUS:", r.status_code)
print("RESPOSTA:", r.text)