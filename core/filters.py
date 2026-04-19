from core.normalizer import normalize_text


NOISE_TERMS = [
    "fake", "proxy", "falso", "fausse", "faux",
    "reservado", "reservada", "dont buy", "don't buy",
    "nao comprar", "no comprar", "ne pas acheter", "pas acheter",
    "troco", "troca", "yugioh", "yu gi oh", "one piece",
    "peluche", "peluches", "plush",
    "figura", "figuras", "figure", "figures", "figurine",
    "minifigure", "minifigura", "minifiguras",
    "funko", "statue", "doll", "toy", "toys",
    "t shirt", "shirt", "tee", "hoodie", "sweatshirt",
    "casaco", "jacket", "hat", "cap", "caps", "chapeu", "bone", "gorro",
    "sapatos", "shoes", "sapatilhas", "sneakers",
    "mochila", "backpack", "bag", "mala",
    "keychain", "socks", "watch", "mug", "poster", "sticker",
    "impressao 3d", "impresion 3d", "impression 3d",
    "sold", "vendido", "agotado", "out of stock",
]


EBAY_NOISE_TERMS = [
    "presale", "preorder", "pokemon center",
    "digital", "code card only", "empty box",
]


def reject_reason(title, source=None):
    normalized = normalize_text(title)
    if not normalized:
        return "empty_title"

    terms = list(NOISE_TERMS)
    if source == "ebay":
        terms.extend(EBAY_NOISE_TERMS)

    for term in terms:
        if term in normalized:
            return "noise:" + term

    return None


def is_valid_listing(title, source=None):
    return reject_reason(title, source) is None
