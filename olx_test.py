from playwright.sync_api import sync_playwright
import re

URL = "https://www.olx.pt/ads/q-cartas-pokemon/"

PALAVRAS_EXCLUIR = [
    "fake", "proxy", "reservado", "reservada",
    "peluche", "peluches", "figura", "figuras",
    "minifigure", "minifigura", "minifiguras",
    "t-shirt", "shirt", "hoodie", "casaco", "hat", "cap",
    "chapeu", "chapéu", "boné", "mochila", "bag", "mala",
    "impressao 3d", "impressão 3d"
]

PALAVRAS_PRIORITARIAS = [
    "charizard", "psa", "bgs", "beckett", "cgc",
    "slab", "etb", "booster", "pikachu", "selado", "graded"
]

def limpar_link(link: str) -> str:
    return link.split("?")[0].strip()

def titulo_valido(titulo: str) -> bool:
    t = titulo.lower()
    return not any(p in t for p in PALAVRAS_EXCLUIR)

def anuncio_prioritario(titulo: str) -> bool:
    t = titulo.lower()
    return any(p in t for p in PALAVRAS_PRIORITARIAS)

def extrair_preco(texto: str) -> str:
    match = re.search(r"\d+(?:[.,]\d{2})?\s*€", texto)
    return match.group(0) if match else "Sem preço"

def limpar_titulo(titulo: str) -> str:
    if not titulo:
        return "Sem título"

    titulo = titulo.strip()

    # limpar sufixos comuns do title/meta
    remover = [
        "à venda no OLX",
        "a venda no OLX",
        "no OLX Portugal",
        "OLX Portugal",
        "| OLX",
        "- OLX",
    ]

    for trecho in remover:
        titulo = titulo.replace(trecho, "").strip()

    titulo = re.sub(r"\s+", " ", titulo).strip(" |-")
    return titulo if titulo else "Sem título"

def obter_titulo(detalhe_page) -> str:
    # 1) og:title
    try:
        meta = detalhe_page.query_selector('meta[property="og:title"]')
        if meta:
            content = meta.get_attribute("content")
            if content and content.strip():
                return limpar_titulo(content)
    except:
        pass

    # 2) title da página
    try:
        titulo_pagina = detalhe_page.title()
        if titulo_pagina and titulo_pagina.strip():
            return limpar_titulo(titulo_pagina)
    except:
        pass

    # 3) h1
    try:
        h1 = detalhe_page.query_selector("h1")
        if h1:
            texto = h1.inner_text().strip()
            if texto:
                return limpar_titulo(texto)
    except:
        pass

    return "Sem título"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()

    print("A abrir OLX...")
    page.goto(URL, timeout=60000, wait_until="domcontentloaded")
    page.wait_for_timeout(6000)

    links = []
    elementos = page.query_selector_all('a[href*="/d/anuncio/"], a[href*="/ads/"]')

    for el in elementos[:30]:
        try:
            href = el.get_attribute("href")
            if not href:
                continue
            if href.startswith("/"):
                href = "https://www.olx.pt" + href
            href = limpar_link(href)
            if href not in links:
                links.append(href)
        except:
            pass

    print(f"Links encontrados: {len(links)}\n")

    detalhe = browser.new_page()

    for link in links[:10]:
        try:
            detalhe.goto(link, timeout=30000, wait_until="domcontentloaded")
            detalhe.wait_for_timeout(2500)

            titulo = obter_titulo(detalhe)

            if not titulo_valido(titulo):
                print("Ignorado:", titulo)
                continue

            texto = detalhe.locator("body").inner_text()
            preco = extrair_preco(texto)

            prioridade = "SIM" if anuncio_prioritario(titulo) else "NÃO"

            print("Título:", titulo)
            print("Preço:", preco)
            print("Prioritário:", prioridade)
            print("Link:", link)
            print("-" * 60)

        except Exception as e:
            print("Erro no anúncio:", link, e)

    input("Carrega Enter para fechar...")
    browser.close()