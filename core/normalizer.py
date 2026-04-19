import re
import unicodedata


def normalize_text(text):
    if not text:
        return ""

    text = fix_common_mojibake(str(text))
    text = text.lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9/%+.-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def fix_common_mojibake(text):
    replacements = {
        "pokÃ©mon": "pokemon",
        "PokÃ©mon": "Pokemon",
        "nÃ£o": "nao",
        "preÃ§o": "preco",
        "tÃ­tulo": "titulo",
        "chapÃ©u": "chapeu",
        "bonÃ©": "bone",
        "leilÃ£o": "leilao",
        "comprar jÃ¡": "comprar ja",
        "mÃ©dia": "media",
        "DiferenÃ§a": "Diferenca",
        "PRIORITÃRIO": "PRIORITARIO",
        "anÃºncio": "anuncio",
    }

    for bad, good in replacements.items():
        text = text.replace(bad, good)

    return text


def contains_any(text, terms):
    normalized = normalize_text(text)
    return any(term in normalized for term in terms)

