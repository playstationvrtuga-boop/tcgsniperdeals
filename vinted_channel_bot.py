from playwright.sync_api import sync_playwright
from config import TOKEN, CHAT_ID
import requests
import os
import time
import re

URL = "https://www.vinted.pt/catalog?search_text=pokemon"
FICHEIRO_VISTOS = "vistos.txt"
CHECK_INTERVAL = 60

# ---------------- FILTROS ----------------

PALAVRAS_EXCLUIR = [
    "dont buy", "don't buy", "do not buy", "not for sale", "reserved",
    "não comprar", "nao comprar", "não vender", "nao vender", "reservado", "reservada",
    "no comprar", "no vender", "no disponible",
    "ne pas acheter", "pas acheter", "ne pas vendre", "réservé", "reserve", "réservée",
    "fake", "proxy", "falso", "fausse", "faux",
    "impressao 3d", "impressão 3d", "impresion 3d", "impresión 3d", "impression 3d",
    "peluche", "peluches", "figura", "figuras", "figure", "figurine",
    "minifigure", "minifigura", "minifiguras", "figurita", "figuritas",
    "t-shirt", "shirt", "tee", "camisola", "camiseta", "hoodie", "casaco",
    "jacket", "hat", "cap", "chapeu", "chapéu", "boné", "gorro",
    "shoes", "sapatilhas", "sneakers", "pants", "calças", "shorts",
    "dress", "skirt", "bag", "mochila", "backpack",
    "sold", "vendido", "agotado", "out of stock"
]

PALAVRAS_PRIORITARIAS = [
    "charizard", "psa", "bgs", "beckett", "cgc",
    "slab", "etb", "booster", "pikachu"
]

PALAVRAS_OBRIGATORIAS = [
    "pokemon", "pokémon", "card", "cards", "carta", "cartas",
    "booster", "etb", "psa", "slab", "gx", "ex", "vmax"
]

# ---------------- TELEGRAM ----------------

def enviar_telegram(mensagem):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": mensagem
    }

    try:
        requests.post(url, data=payload)
    except Exception as e:
        print("Erro Telegram:", e)

# ---------------- UTIL ----------------

def extrair_id(link):
    match = re.search(r"/items/(\d+)", link)
    return match.group(1) if match else None

def limpar_link(link):
    return link.split("?")[0]

def carregar_vistos():
    if not os.path.exists(FICHEIRO_VISTOS):
        return set()

    with open(FICHEIRO_VISTOS, "r") as f:
        return set(l.strip() for l in f)

def guardar_visto(id_item):
    with open(FICHEIRO_VISTOS, "a") as f:
        f.write(id_item + "\n")

def extrair_preco(texto):
    match = re.search(r"\d+(?:,\d{2})?\s*€", texto)
    return match.group(0) if match else "Sem preço"

# ---------------- VALIDAÇÃO ----------------

def titulo_valido(titulo):
    t = titulo.lower()

    for palavra in PALAVRAS_EXCLUIR:
        if palavra in t:
            return False

    return True

def titulo_relevante(titulo):
    t = titulo.lower()

    for palavra in PALAVRAS_OBRIGATORIAS:
        if palavra in t:
            return True

    return False

def anuncio_prioritario(titulo):
    t = titulo.lower()

    for palavra in PALAVRAS_PRIORITARIAS:
        if palavra in t:
            return True

    return False

# ---------------- EXTRAÇÃO ----------------

def extrair_detalhes(page, link):
    try:
        page.goto(link)
        page.wait_for_timeout(3000)

        titulo = page.query_selector("h1").inner_text()
        texto = page.locator("body").inner_text()

        preco = extrair_preco(texto)

        return titulo, preco

    except:
        return None, None

def obter_links(page):
    page.goto(URL)
    page.wait_for_timeout(8000)

    elementos = page.query_selector_all('a[href*="/items/"]')
    links = []

    for el in elementos[:20]:
        href = el.get_attribute("href")

        if not href:
            continue

        if not href.startswith("http"):
            href = "https://www.vinted.pt" + href

        links.append(limpar_link(href))

    return list(dict.fromkeys(links))

# ---------------- SCRAPER ----------------

def procurar_anuncios():
    vistos = carregar_vistos()
    novos = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        page_lista = browser.new_page()
        page_detalhe = browser.new_page()

        links = obter_links(page_lista)

        for link in links:
            id_item = extrair_id(link)

            if not id_item or id_item in vistos:
                continue

            titulo, preco = extrair_detalhes(page_detalhe, link)

            if not titulo:
                continue

            if not titulo_valido(titulo):
                continue

            if not titulo_relevante(titulo):
                continue

            prioridade = anuncio_prioritario(titulo)

            vistos.add(id_item)
            guardar_visto(id_item)

            novos.append({
                "titulo": titulo,
                "preco": preco,
                "link": link,
                "prioritario": prioridade
            })

        browser.close()

    novos.sort(key=lambda x: x["prioritario"], reverse=True)
    return novos

# ---------------- LOOP ----------------

def main():
    print("Bot ativo...")

    while True:
        try:
            novos = procurar_anuncios()

            for anuncio in novos:
                if anuncio["prioritario"]:
                    header = "🚨 DEAL PRIORITÁRIO 🚨"
                else:
                    header = "🔥 Novo anúncio"

                mensagem = (
                    f"{header}\n\n"
                    f"📌 {anuncio['titulo']}\n"
                    f"💰 {anuncio['preco']}\n\n"
                    f"🔗 {anuncio['link']}\n\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"🚨 ALERTA POKÉMON DEAL 🚨\n"
                    f"💎 OPORTUNIDADE DETETADA 💎\n"
                    f"━━━━━━━━━━━━━━━"
                )

                print(mensagem)
                enviar_telegram(mensagem)
                time.sleep(2)

        except Exception as e:
            print("Erro:", e)

        print("A aguardar...\n")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()