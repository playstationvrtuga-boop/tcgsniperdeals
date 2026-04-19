from playwright.sync_api import sync_playwright
from config import TOKEN, CHAT_ID
import requests
import os
import time

URL = "https://www.vinted.pt/catalog?search_text=pokemon"
FICHEIRO_VISTOS = "vistos.txt"


def enviar_telegram(mensagem):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": mensagem
    }

    try:
        resposta = requests.post(url, data=payload, timeout=15)
        print("Telegram status:", resposta.status_code)
    except Exception as e:
        print("Erro ao enviar para Telegram:", e)


def carregar_vistos():
    if not os.path.exists(FICHEIRO_VISTOS):
        return set()

    with open(FICHEIRO_VISTOS, "r", encoding="utf-8") as f:
        return set(linha.strip() for linha in f if linha.strip())


def guardar_visto(link):
    with open(FICHEIRO_VISTOS, "a", encoding="utf-8") as f:
        f.write(link + "\n")


def extrair_dados_cartao(texto):
    linhas = [linha.strip() for linha in texto.split("\n") if linha.strip()]

    if linhas and linhas[0].isdigit():
        linhas.pop(0)

    titulo = "Sem título"
    estado = "Sem estado"
    preco = "Sem preço"

    if len(linhas) >= 1:
        titulo = linhas[0]

    if len(linhas) >= 2 and "€" not in linhas[1]:
        estado = linhas[1]

    for linha in linhas:
        if "€" in linha:
            preco = linha
            break

    return titulo, estado, preco


def procurar_anuncios():
    vistos = carregar_vistos()
    novos = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        print("A abrir Vinted...")
        page.goto(URL, timeout=60000)

        page.wait_for_timeout(8000)
        page.wait_for_selector('a[href*="/items/"]', timeout=20000)

        cards = page.query_selector_all('div[data-testid="grid-item"]')
        print(f"Encontrados {len(cards)} cartões.")

        for card in cards[:15]:
            try:
                texto = card.inner_text()
                titulo, estado, preco = extrair_dados_cartao(texto)

                link_element = card.query_selector("a")
                link = link_element.get_attribute("href") if link_element else None

                if not link:
                    continue

                if not link.startswith("http"):
                    link = "https://www.vinted.pt" + link

                if link in vistos:
                    continue

                vistos.add(link)
                guardar_visto(link)

                anuncio = {
                    "titulo": titulo,
                    "estado": estado,
                    "preco": preco,
                    "link": link
                }

                novos.append(anuncio)

            except Exception as e:
                print("Erro num cartão:", e)

        browser.close()

    return novos


def main():
    print("À procura de anúncios novos...")
    novos = procurar_anuncios()

    if not novos:
        print("Nenhum anúncio novo encontrado.")
        return

    print(f"Foram encontrados {len(novos)} anúncios novos.")

    for anuncio in novos:
        mensagem = (
            f"Novo anúncio Pokémon\n\n"
            f"Título: {anuncio['titulo']}\n"
            f"Estado: {anuncio['estado']}\n"
            f"Preço: {anuncio['preco']}\n"
            f"Link: {anuncio['link']}"
        )

        print(mensagem)
        print("-" * 60)

        enviar_telegram(mensagem)
        time.sleep(2)


if __name__ == "__main__":
    main()