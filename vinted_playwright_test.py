from playwright.sync_api import sync_playwright
import re

URL = "https://www.vinted.pt/catalog?search_text=pokemon"

def extrair_dados_cartao(texto):
    linhas = [linha.strip() for linha in texto.split("\n") if linha.strip()]

    # Remover primeira linha se for apenas número (likes/favoritos)
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

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()

    print("A abrir Vinted...")
    page.goto(URL, timeout=60000)

    page.wait_for_timeout(8000)
    page.wait_for_selector('a[href*="/items/"]', timeout=20000)

    print("A extrair anúncios...\n")

    cards = page.query_selector_all('div[data-testid="grid-item"]')

    print(f"Encontrados {len(cards)} cartões.\n")

    for card in cards[:10]:
        try:
            texto = card.inner_text()
            titulo, estado, preco = extrair_dados_cartao(texto)

            link_element = card.query_selector("a")
            link = link_element.get_attribute("href") if link_element else None

            if link and not link.startswith("http"):
                link = "https://www.vinted.pt" + link

            print("Título:", titulo)
            print("Estado:", estado)
            print("Preço:", preco)
            print("Link:", link)
            print("-" * 60)

        except Exception as e:
            print("Erro num item:", e)

    input("\nCarrega Enter para fechar...")
    browser.close()