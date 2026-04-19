import requests

print("Início do script...")

url = "https://www.vinted.pt/api/v2/catalog/items"

params = {
    "search_text": "pokemon",
    "order": "newest_first",
    "page": 1,
    "per_page": 5
}

headers = {
    "User-Agent": "Mozilla/5.0"
}

try:
    resposta = requests.get(url, params=params, headers=headers, timeout=15)

    print("Status code:", resposta.status_code)
    print("URL final:", resposta.url)

    if resposta.status_code == 200:
        dados = resposta.json()
        itens = dados.get("items", [])

        print(f"Foram encontrados {len(itens)} itens.\n")

        for item in itens:
            titulo = item.get("title", "Sem título")
            preco = item.get("price", "Sem preço")
            url_item = item.get("url", "Sem link")

            print("Título:", titulo)
            print("Preço:", preco)
            print("Link:", url_item)
            print("-" * 50)
    else:
        print("Erro ao aceder à Vinted:")
        print(resposta.text)

except Exception as e:
    print("Ocorreu um erro:", e)

input("Carrega Enter para sair...")