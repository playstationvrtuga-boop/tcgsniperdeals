from playwright.sync_api import sync_playwright
from config import TOKEN, VIP_CHAT_ID
import requests
import os
import time
import re

PESQUISAS = [
    {"pais": "Portugal", "url": "https://www.vinted.pt/catalog?search_text=pokemon", "base": "https://www.vinted.pt"},
    {"pais": "Espanha", "url": "https://www.vinted.es/catalog?search_text=pokemon", "base": "https://www.vinted.es"},
    {"pais": "França", "url": "https://www.vinted.fr/catalog?search_text=pokemon", "base": "https://www.vinted.fr"},
]

FICHEIRO_VISTOS = "vistos.txt"


# ---------------- TELEGRAM ----------------
def enviar_telegram(mensagem):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": VIP_CHAT_ID,
        "text": mensagem,
        "disable_web_page_preview": False
    }

    try:
        resposta = requests.post(url, data=payload, timeout=20)
        print("Telegram:", resposta.status_code)
    except Exception as e:
        print("Erro Telegram:", e)


# ---------------- HISTÓRICO ----------------
def extrair_id(link):
    match = re.search(r"/items/(\d+)", link)
    return match.group(1) if match else None


def limpar_link(link):
    return link.split("?")[0].strip()


def carregar_vistos():
    if not os.path.exists(FICHEIRO_VISTOS):
        return set()

    with open(FICHEIRO_VISTOS, "r", encoding="utf-8") as f:
        return set(linha.strip() for linha in f if linha.strip())


def guardar_visto(chave):
    with open(FICHEIRO_VISTOS, "a", encoding="utf-8") as f:
        f.write(chave + "\n")


# ---------------- TEXTO / LIMPEZA ----------------
def limpar_espacos(texto):
    return re.sub(r"\s+", " ", texto).strip()


def extrair_primeiro_preco(texto):
    if not texto:
        return "Sem preço"

    linhas = [linha.strip() for linha in texto.split("\n") if linha.strip()]
    padrao = r"\d{1,3}(?:\.\d{3})*(?:,\d{2})?\s*€"

    for linha in linhas:
        match = re.search(padrao, linha)
        if match:
            return match.group(0).strip()

    return "Sem preço"


def obter_texto_seletor(page, seletor):
    try:
        el = page.query_selector(seletor)
        if el:
            texto = el.inner_text().strip()
            if texto:
                return texto
    except:
        pass
    return None


# ---------------- EXTRAIR LINKS NOVOS ----------------
def obter_links_novos(page, base_url, pais, vistos):
    page.wait_for_timeout(8000)
    page.wait_for_selector('a[href*="/items/"]', timeout=25000)

    links = page.query_selector_all('a[href*="/items/"]')
    novos_links = []

    for elemento in links:
        href = elemento.get_attribute("href")
        if not href:
            continue

        if not href.startswith("http"):
            href = base_url + href

        href = limpar_link(href)

        id_item = extrair_id(href)
        if not id_item:
            continue

        chave_unica = f"{pais}:{id_item}"
        if chave_unica in vistos:
            continue

        vistos.add(chave_unica)
        guardar_visto(chave_unica)
        novos_links.append(href)

    # remover duplicados mantendo ordem
    vistos_local = set()
    links_finais = []

    for link in novos_links:
        if link not in vistos_local:
            vistos_local.add(link)
            links_finais.append(link)

    return links_finais[:15]


# ---------------- EXTRAIR DETALHES DO ANÚNCIO ----------------
def extrair_estado(texto_pagina):
    estados_possiveis = [
        "Novo com etiquetas",
        "Novo sem etiquetas",
        "Muito bom",
        "Bom",
        "Satisfatório",
        "Nuevo con etiquetas",
        "Nuevo sin etiquetas",
        "Muy bueno",
        "Bueno",
        "Satisfactorio",
        "Neuf avec étiquettes",
        "Neuf sans étiquette",
        "Très bon état",
        "Bon état",
        "Satisfaisant"
    ]

    for estado in estados_possiveis:
        if estado in texto_pagina:
            return estado

    return "Sem estado"


def extrair_detalhes(page, link):
    page.goto(link, timeout=60000)
    page.wait_for_timeout(5000)

    titulo = (
        obter_texto_seletor(page, "h1") or
        obter_texto_seletor(page, '[data-testid="item-title"]') or
        "Sem título"
    )
    titulo = limpar_espacos(titulo)

    try:
        texto_pagina = page.locator("body").inner_text()
    except:
        texto_pagina = ""

    preco = extrair_primeiro_preco(texto_pagina)
    estado = extrair_estado(texto_pagina)

    descricao = (
        obter_texto_seletor(page, '[data-testid="item-description"]') or
        obter_texto_seletor(page, 'div[class*="description"]') or
        obter_texto_seletor(page, 'p[class*="description"]') or
        "Sem descrição"
    )
    descricao = limpar_espacos(descricao)

    lixo_descricao = [
        "Continuar para o conteúdo",
        "Criar conta",
        "Iniciar sessão",
        "Vender agora",
        "Catálogo",
        "Peças de estilista",
        "Eletrónica",
        "Entretenimento",
        "Hobbies e Coleções",
        "Desporto",
        "Ir al contenido",
        "Registrarte",
        "Inicia sesión",
        "Vender ya",
        "Catálogo",
        "Electrónica",
        "Entretenimiento",
        "Coleccionismo",
        "Sport",
        "Accéder au contenu",
        "S'inscrire",
        "Se connecter",
        "Vends tes articles",
        "Catalogue",
        "Électronique",
        "Divertissement",
        "Loisirs"
    ]

    for termo in lixo_descricao:
        if termo.lower() in descricao.lower():
            descricao = "Sem descrição"
            break

    if len(descricao) > 220:
        descricao = descricao[:220] + "..."

    return titulo, preco, estado, descricao


# ---------------- PROCESSAR UM PAÍS ----------------
def processar_pais(page, pesquisa, vistos):
    pais = pesquisa["pais"]
    url = pesquisa["url"]
    base = pesquisa["base"]

    print(f"\nA processar {pais}...")
    page.goto(url, timeout=60000)

    novos_links = obter_links_novos(page, base, pais, vistos)
    print(f"{pais}: encontrados {len(novos_links)} novos links.")

    resultados = []

    for link in novos_links:
        try:
            titulo, preco, estado, descricao = extrair_detalhes(page, link)

            resultados.append({
                "pais": pais,
                "titulo": titulo,
                "preco": preco,
                "estado": estado,
                "descricao": descricao,
                "link": link
            })

        except Exception as e:
            print(f"Erro ao processar anúncio em {pais}:", e)

    return resultados


# ---------------- MAIN ----------------
def main():
    print("À procura de novos anúncios multi-país...")

    vistos = carregar_vistos()
    todos_os_resultados = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        for pesquisa in PESQUISAS:
            resultados = processar_pais(page, pesquisa, vistos)
            todos_os_resultados.extend(resultados)

        browser.close()

    if not todos_os_resultados:
        print("Nenhum anúncio novo encontrado.")
        return

    print(f"\nTotal de novos anúncios: {len(todos_os_resultados)}")

    for anuncio in todos_os_resultados:
        mensagem = (
            f"🌍 {anuncio['pais']}\n"
            f"🔥 NOVO ALERTA POKÉMON 🔥\n\n"
            f"📌 {anuncio['titulo']}\n"
            f"💰 {anuncio['preco']}\n"
            f"📦 {anuncio['estado']}\n\n"
            f"📝 {anuncio['descricao']}\n\n"
            f"🔗 {anuncio['link']}"
        )

        print("\n" + mensagem)
        print("-" * 60)

        enviar_telegram(mensagem)
        time.sleep(2)


if __name__ == "__main__":
    main()