from playwright.sync_api import sync_playwright

def limpar_link(link):
    return link.split("?")[0].strip()

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()

    url = "https://www.ebay.com/sch/i.html?_nkw=pokemon+cards+psa+etb+booster&_sop=10&LH_BIN=1"

    print("A abrir eBay...")
    page.goto(url, timeout=60000, wait_until="domcontentloaded")
    page.wait_for_timeout(10000)

    print("Título da página:", page.title())
    print("URL atual:", page.url)

    links = []

    seletores = [
        'a[href*="/itm/"]',
        'a[href*="itm/"]',
        'a.s-item__link'
    ]

    for seletor in seletores:
        elementos = page.query_selector_all(seletor)
        print(f"Seletor {seletor} -> {len(elementos)} elementos")

        for el in elementos[:50]:
            try:
                href = el.get_attribute("href")
                if not href:
                    continue

                if "/itm/" in href or "ebay." in href:
                    href = limpar_link(href)
                    if href not in links:
                        links.append(href)

            except Exception as e:
                print("Erro num link:", e)

    print("\nLinks finais encontrados:", len(links))

    for link in links[:15]:
        print("LINK:", link)

    input("Carrega Enter para fechar...")
    browser.close()