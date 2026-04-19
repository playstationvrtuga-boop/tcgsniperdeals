import re
from dataclasses import dataclass

from core.filters import reject_reason
from core.normalizer import normalize_text


STRONG_POKEMON = [
    "charizard", "pikachu", "gengar", "mew", "mewtwo",
    "umbreon", "rayquaza", "lugia", "blastoise", "venusaur",
    "dragonite", "eevee", "gyarados", "alakazam", "snorlax",
    "poncho", "poncho pikachu",
]

RARITY_TERMS = [
    "gx", "ex", "vmax", "vstar", "full art", "alt art",
    "illustration rare", "special illustration rare", " sir ",
    " ir ", "trainer gallery", "secret rare", "hyper rare",
    "gold", "rainbow", "holo", "reverse holo", "master ball",
]

GRADED_TERMS = ["psa", "bgs", "beckett", "cgc", "slab", "graded", "grade"]
SEALED_TERMS = [
    "sealed", "selado", "etb", "elite trainer box", "booster",
    "booster box", "booster pack", "blister", "display", "tin",
]
CARD_TERMS = ["carta", "cartas", "card", "cards", "tcg"]
LOT_TERMS = ["lote", "lot", "bundle", "colecao", "collection", "bulk"]
INVALID_SET_CODES = {
    "psa", "bgs", "cgc", "bulk", "lote", "lot", "pack", "packs",
    "card", "cards", "carta", "cartas", "grade", "graded",
}


@dataclass
class ListingAssessment:
    is_valid: bool
    score: int
    category: str
    confidence: str
    reasons: list
    reject_reason: str = None


def has_card_number(normalized_title):
    if re.search(r"\b\d{1,3}\s*/\s*\d{1,3}\b", normalized_title):
        return True

    code_patterns = [
        r"\b([a-z]{2,5}\d?[a-z]?)\s*[- ]\s*(\d{1,3}[a-z]?)\b",
        r"\b(sv\d+[a-z]?)\s*[- ]\s*(\d{1,3}[a-z]?)\b",
    ]

    for pattern in code_patterns:
        match = re.search(pattern, normalized_title)
        if not match:
            continue

        set_code = match.group(1)
        if set_code in INVALID_SET_CODES:
            continue

        if set_code.startswith(("sv", "swsh", "sm", "xy", "bw", "dp", "hgss")):
            return True

    return False


def has_set_code_card_number(normalized_title):
    code_patterns = [
        r"\b([a-z]{2,5}\d?[a-z]?)\s*[- ]\s*(\d{1,3}[a-z]?)\b",
        r"\b(sv\d+[a-z]?)\s*[- ]\s*(\d{1,3}[a-z]?)\b",
    ]

    valid_prefixes = (
        "sv", "swsh", "sm", "xy", "bw", "dp", "hgss",
        "mew", "teu", "pfa", "jtg", "pal", "obf", "par", "sfa",
        "scr", "ssp", "twm", "tem", "pre", "cel", "evs", "crz",
    )

    for pattern in code_patterns:
        match = re.search(pattern, normalized_title)
        if not match:
            continue

        set_code = match.group(1)
        if set_code in INVALID_SET_CODES:
            continue

        if set_code.startswith(valid_prefixes):
            return True

    return False


def has_fraction_only_number(normalized_title):
    return bool(re.search(r"\b\d{1,3}\s*/\s*\d{1,3}\b", normalized_title))


def detect_category(normalized_title):
    if any(term in normalized_title for term in GRADED_TERMS):
        return "graded_card"

    if any(term in normalized_title for term in SEALED_TERMS):
        return "sealed_product"

    if any(term in normalized_title for term in LOT_TERMS):
        return "lot_collection"

    if has_card_number(normalized_title):
        return "single_card"

    if any(term in normalized_title for term in STRONG_POKEMON):
        return "single_card"

    if any(term in normalized_title for term in CARD_TERMS):
        return "single_card"

    return "unknown"


def assess_listing(title, price_text=None, source=None):
    normalized = normalize_text(title)
    reason = reject_reason(title, source)
    if reason:
        return ListingAssessment(
            is_valid=False,
            score=0,
            category="rejected",
            confidence="none",
            reasons=[],
            reject_reason=reason,
        )

    score = 0
    reasons = []
    category = detect_category(normalized)

    if "pokemon" in normalized or "tcg" in normalized:
        score += 12
        reasons.append("pokemon_tcg")

    if has_card_number(normalized):
        score += 30
        reasons.append("card_number")

    if any(term in normalized for term in STRONG_POKEMON):
        score += 22
        reasons.append("strong_pokemon")

    if any(term in normalized for term in RARITY_TERMS):
        score += 16
        reasons.append("rarity")

    if category == "graded_card":
        score += 26
        reasons.append("graded")
    elif category == "sealed_product":
        score += 22
        reasons.append("sealed")
    elif category == "single_card":
        score += 14
        reasons.append("single_card")
    elif category == "lot_collection":
        score += 4
        reasons.append("lot")

    if price_text and "sem pre" not in normalize_text(price_text):
        score += 8
        reasons.append("price_detected")

    if category == "unknown":
        score -= 12
        reasons.append("generic_title")

    if category == "lot_collection" and not any(term in normalized for term in STRONG_POKEMON):
        score -= 8
        reasons.append("generic_lot")

    is_valid = True

    if score >= 70:
        confidence = "high"
    elif score >= 45:
        confidence = "medium"
    elif score >= 20:
        confidence = "low"
    else:
        confidence = "none"

    return ListingAssessment(
        is_valid=is_valid,
        score=max(score, 0),
        category=category,
        confidence=confidence,
        reasons=reasons,
        reject_reason=None,
    )


def is_priority(assessment):
    return assessment.score >= 55 or assessment.confidence == "high"


def should_consult_cardmarket(title, assessment):
    if not assessment.is_valid:
        return False

    normalized = normalize_text(title)

    if assessment.category == "lot_collection":
        return False

    if has_set_code_card_number(normalized):
        return True

    if has_fraction_only_number(normalized):
        return False

    if assessment.category == "sealed_product" and assessment.score >= 40:
        return True

    if assessment.category == "graded_card":
        return any(term in normalized for term in STRONG_POKEMON)

    if any(term in normalized for term in STRONG_POKEMON):
        return True

    return False
