import requests
from config import TOKEN, CHAT_ID

mensagem = "Teste do bot Pokémon: está a funcionar."

url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

payload = {
    "chat_id": CHAT_ID,
    "text": mensagem
}

resposta = requests.post(url, data=payload)

print("Status code:", resposta.status_code)
print("Resposta:", resposta.text)
input("Carrega Enter para sair...")