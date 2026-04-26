from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
POKEMON_NAMES_PATH = PROJECT_ROOT / "data" / "pokemon_names.json"

BASE_POKEMON_NAMES = {
    "charizard", "pikachu", "mew", "mewtwo", "lugia", "ho-oh", "hooh",
    "rayquaza", "umbreon", "espeon", "gengar", "dragonite", "greninja",
    "lucario", "latias", "latios", "giratina", "arceus", "blastoise",
    "venusaur", "eevee", "sylveon", "leafeon", "glaceon", "flareon",
    "jolteon", "vaporeon", "snorlax", "magikarp", "gardevoir", "machamp",
    "alakazam", "lapras", "moltres", "zapdos", "articuno", "suicune",
    "entei", "raikou", "celebi", "jirachi", "deoxys", "darkrai",
    "zoroark", "ninetales", "tyranitar", "salamence", "metagross",
    "gyarados", "scizor", "mimikyu", "marshadow", "reshiram", "zekrom",
    "kyogre", "groudon", "inteleon", "zeraora", "absol", "aerodactyl",
    "arcanine", "bulbasaur", "charmander", "charmeleon", "ivysaur",
    "jigglypuff", "psyduck", "raichu", "squirtle",
}

NAME_ALIASES = {
    "dracaufeu": "charizard",
    "glurak": "charizard",
    "salameche": "charmander",
    "hooh": "ho-oh",
}

SET_CODES = {
    "PFL", "ME1", "SV8", "SFA", "PAL", "OBF", "TWM", "PAF", "TEF", "PAR",
    "SVI", "SCR", "SSP", "PRE", "MEW", "CRZ", "LOR", "SIT", "BRS", "ASR",
    "FST", "EVS", "BST", "VIV", "DAA", "RCL", "SSH", "CEL", "HIF", "SHF",
}

RARITIES = {"AR", "SAR", "SR", "UR", "IR", "SIR", "HR", "RR"}
VARIANTS = {"ex", "gx", "v", "vmax", "vstar", "mega", "tag team"}
SET_CODE_EXCLUDES = {"PSA", "CGC", "BGS", "ACE", "EX", "GX", "VMAX", "VSTAR", "TAG", "TEAM"}
POKEMON_KEYWORDS = {
    "pokemon", "tcg", "pokemon card", "carte pokemon", "carta pokemon",
    "tarjeta pokemon", "cartas pokemon", "cartes pokemon",
}
GENERIC_QUERY_TERMS = {
    "pokemon", "tcg", "card", "cards", "carta", "cartas", "carte", "cartes",
    "tarjeta", "tarjetas", "rare", "reverse", "holo", "ultra", "secret",
    "full", "art", "near", "mint", "nm", "played", "graded", "slab", "psa",
    "cgc", "bgs", "beckett", "ace", "aura", "japanese", "japonais",
    "japones", "english", "ingles", "francais", "french", "spanish",
    "espanol", "portuguese", "portugues", "lot", "bundle", "lote", "pack",
    "de", "des", "du", "la", "le", "les", "of", "the", "and", "with",
    "sem", "com", "sans", "avec", "originais", "variadas", "neuf", "neuve",
    "novo", "nova", "nuevo", "nueva", "condition", "edition",
}
LANGUAGE_HINTS = {
    "japanese": {"japanese", "japonais", "japones", "japonesas", "japan", "jp"},
    "english": {"english", "ingles", "anglais", "eng"},
    "portuguese": {"portuguese", "portugues", "pt"},
    "french": {"french", "francais", "francaise", "fr", "francês"},
    "spanish": {"spanish", "espanol", "español", "espagnol", "es"},
}
GRADING_HINTS = {"psa", "beckett", "bgs", "cgc", "ace", "aura", "graded", "slab"}
SEALED_TERMS = {
    "booster", "etb", "elite trainer box", "display", "booster box", "tin",
    "collection box", "sealed", "coffret", "blister",
}
LOT_TERMS = {
    "lot", "bundle", "lote", "pack de cartas", "sobre de cartas", "cartas variadas",
    "30 cartas", "variadas", "bulk",
}
SET_NAME_TERMS = {
    "mega evolution", "mega symphonia", "paldea evolved", "obsidian flames",
    "twilight masquerade", "prismatic evolutions", "surging sparks",
    "evolving skies", "brilliant stars", "lost origin", "silver tempest",
    "crown zenith", "flammes fantasmagoriques", "ascended heroes",
}


@dataclass
class CardSignals:
    raw_title: str
    normalized_title: str
    pokemon_name: str | None = None
    keyword_name: str | None = None
    card_number: str | None = None
    set_total: str | None = None
    full_number: str | None = None
    set_code: str | None = None
    set_name: str | None = None
    rarity: str | None = None
    variant: str | None = None
    language: str | None = None
    grading: str | None = None
    kind: str = "unknown_pokemon"
    confidence: str = "UNKNOWN"
    queries: list[str] = field(default_factory=list)
    decision: str = "skip"
    skip_reason: str | None = None


@dataclass
class ParsedListingIdentity:
    confidence: str
    query: str
    listing_kind: str | None = None
    extracted_name: str | None = None
    extracted_number: str | None = None
    extracted_set: str | None = None
    fallback_query_used: bool = False
    is_pokemon_related: bool = False
    signals: CardSignals | None = None


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(char for char in normalized if not unicodedata.combining(char))


def normalize_title(title: str) -> str:
    text = _strip_accents(title).lower()
    text = text.replace("pokémon", "pokemon").replace("pokèmon", "pokemon")
    text = re.sub(r"\bmega\s+(evolution|evolucion|evolucao|evolution)\b", "mega evolution", text)
    text = re.sub(r"\bmega\s+evolution\b", "mega evolution", text)
    text = re.sub(r"\b(?:nº|n°|no\.?|number)\s*(\d{1,4})\b", r"\1", text)
    text = re.sub(r"\b(?:card|carta|carte|tarjeta)\s*(\d{1,4})\b", r"\1", text)
    text = re.sub(r"\b(\d{1,3})\s*[/\\-]\s*(\d{1,3})\b", r"\1/\2", text)
    text = text.replace("×", "x")
    text = re.sub(r"[^a-z0-9/+\-.\s]", " ", text)
    text = re.sub(r"\b([a-z]{2,5})\s+(\d{1,3})(/\d{1,3})?\b", r"\1 \2\3", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _load_pokemon_names() -> set[str]:
    names = set(BASE_POKEMON_NAMES)
    if POKEMON_NAMES_PATH.exists():
        try:
            payload = json.loads(POKEMON_NAMES_PATH.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                names.update(normalize_title(str(name)) for name in payload if str(name).strip())
        except (OSError, ValueError):
            pass
    names.update(NAME_ALIASES)
    return {name for name in names if name}


def detect_pokemon_name(title: str) -> str | None:
    normalized = normalize_title(title)
    names = _load_pokemon_names()
    tokens = normalized.split()

    for token in tokens:
        if token in NAME_ALIASES:
            return NAME_ALIASES[token]
        if token in names:
            return token

    compact = normalized.replace(" ", "")
    for name in sorted(names, key=len, reverse=True):
        if len(name) >= 4 and name.replace("-", "") in compact:
            return NAME_ALIASES.get(name, name)
    return None


def _extract_numbers(normalized: str) -> tuple[str | None, str | None, str | None]:
    full_match = re.search(r"\b(\d{1,3})/(\d{1,3})\b", normalized)
    if full_match:
        card_number, set_total = full_match.group(1), full_match.group(2)
        return card_number, set_total, f"{card_number}/{set_total}"

    number_match = re.search(r"\b(\d{1,3})\b", normalized)
    if number_match:
        return number_match.group(1), None, None
    return None, None, None


def _extract_set_code(normalized: str) -> str | None:
    upper_text = normalized.upper()
    for code in sorted(SET_CODES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(code)}\s*\d{{1,3}}(?:/\d{{1,3}})?\b", upper_text):
            return code
        if re.search(rf"\b{re.escape(code)}\b", upper_text):
            return code
    code_match = re.search(r"\b([A-Z]{2,5}\d?)\s*\d{1,3}(?:/\d{1,3})?\b", upper_text)
    if code_match and code_match.group(1) not in SET_CODE_EXCLUDES:
        return code_match.group(1)
    return None


def _extract_first_known(normalized: str, values: set[str]) -> str | None:
    for value in sorted(values, key=len, reverse=True):
        if re.search(rf"\b{re.escape(normalize_title(value))}\b", normalized):
            return value
    return None


def _extract_variant(normalized: str) -> str | None:
    if re.search(r"\btag\s+team\b", normalized):
        return "tag team"
    if re.search(r"\bmega\b", normalized):
        return "mega"
    if re.search(r"\bx\b", normalized):
        return "ex"
    for variant in ("vmax", "vstar", "ex", "gx", "v"):
        if re.search(rf"\b{variant}\b", normalized):
            return variant
    return None


def _extract_language(normalized: str) -> str | None:
    for language, hints in LANGUAGE_HINTS.items():
        if any(re.search(rf"\b{re.escape(normalize_title(hint))}\b", normalized) for hint in hints):
            return language
    return None


def _extract_set_name(normalized: str) -> str | None:
    return _extract_first_known(normalized, SET_NAME_TERMS)


def _contains_pokemon_keyword(normalized: str) -> bool:
    return any(keyword in normalized for keyword in POKEMON_KEYWORDS)


def _extract_keyword_name(normalized: str, pokemon_name: str | None) -> str | None:
    if pokemon_name:
        return pokemon_name
    tokens = normalized.split()
    for token in tokens:
        if not token.isalpha():
            continue
        if len(token) < 3:
            continue
        if token in GENERIC_QUERY_TERMS:
            continue
        if token in VARIANTS:
            continue
        if token.upper() in SET_CODES or token.upper() in RARITIES or token.upper() in SET_CODE_EXCLUDES:
            continue
        return token
    return None


def classify_listing_kind(signals: CardSignals) -> str:
    text = signals.normalized_title
    if any(term in text for term in SEALED_TERMS):
        return "sealed_product"
    if any(re.search(rf"\b{re.escape(term)}\b", text) for term in GRADING_HINTS):
        return "graded_card"
    if any(term in text for term in LOT_TERMS) or re.search(r"\b\d{2,4}\s+cartas\b", text):
        return "lot_bundle"
    if signals.pokemon_name or signals.full_number or signals.card_number:
        return "single_card"
    if _contains_pokemon_keyword(text):
        return "unknown_pokemon"
    return "unknown"


def _classify_confidence(signals: CardSignals) -> str:
    has_pokemon_word = _contains_pokemon_keyword(signals.normalized_title)
    if signals.pokemon_name and signals.full_number:
        return "HIGH"
    if signals.pokemon_name and signals.set_code and signals.card_number:
        return "HIGH"
    if signals.kind == "graded_card" and signals.pokemon_name and signals.grading:
        return "HIGH"
    if signals.pokemon_name and signals.card_number:
        return "MEDIUM"
    if signals.set_code and signals.full_number:
        return "MEDIUM"
    if signals.full_number and has_pokemon_word:
        return "MEDIUM"
    if signals.pokemon_name and signals.variant:
        return "MEDIUM"
    if signals.kind in {"sealed_product", "lot_bundle"} and has_pokemon_word:
        return "LOW"
    if signals.pokemon_name:
        return "LOW"
    if has_pokemon_word and (signals.card_number or signals.set_code):
        return "LOW"
    if has_pokemon_word:
        return "LOW"
    if signals.full_number or signals.card_number:
        return "LOW"
    return "UNKNOWN"


def extract_card_signals(title: str) -> CardSignals:
    normalized = normalize_title(title)
    card_number, set_total, full_number = _extract_numbers(normalized)
    rarity_value = _extract_first_known(normalized, {rarity.lower() for rarity in RARITIES})
    rarity = rarity_value.upper() if rarity_value else None
    pokemon_name = detect_pokemon_name(normalized)
    keyword_name = None
    if pokemon_name or card_number or full_number or _contains_pokemon_keyword(normalized):
        keyword_name = _extract_keyword_name(normalized, pokemon_name)

    signals = CardSignals(
        raw_title=title or "",
        normalized_title=normalized,
        pokemon_name=pokemon_name,
        keyword_name=keyword_name,
        card_number=card_number,
        set_total=set_total,
        full_number=full_number,
        set_code=_extract_set_code(normalized),
        set_name=_extract_set_name(normalized),
        rarity=rarity,
        variant=_extract_variant(normalized),
        language=_extract_language(normalized),
        grading=_extract_first_known(normalized, GRADING_HINTS),
    )
    signals.kind = classify_listing_kind(signals)
    signals.confidence = _classify_confidence(signals)
    signals.queries = generate_generic_alias_queries(signals)
    signals.decision = "process" if signals.confidence != "UNKNOWN" else "skip"
    signals.skip_reason = None if signals.decision == "process" else "not_pokemon_related"
    return signals


def _append_unique(queries: list[str], value: str | None) -> None:
    clean = normalize_title(value or "")
    if clean and clean not in queries:
        queries.append(clean)


def generate_generic_alias_queries(signals: CardSignals) -> list[str]:
    queries: list[str] = []
    name = signals.pokemon_name or signals.keyword_name
    number = signals.card_number
    full_number = signals.full_number
    code = signals.set_code
    variant = signals.variant

    if name and variant and full_number:
        _append_unique(queries, f"{name} {variant} {full_number}")
        _append_unique(queries, f"{name} {full_number}")
        _append_unique(queries, f"{name} {variant} {number}")
        _append_unique(queries, f"{name} {number}")
        _append_unique(queries, f"pokemon {name}")
        _append_unique(queries, f"pokemon card {name}")
        _append_unique(queries, f"pokemon {full_number}")
        _append_unique(queries, f"pokemon {number}")
        _append_unique(queries, "pokemon card")

    if name and full_number:
        _append_unique(queries, f"{name} {full_number}")
        _append_unique(queries, f"{name} {number}")
        _append_unique(queries, f"pokemon {full_number}")
        _append_unique(queries, f"{full_number} {name}")

    if name and code and number:
        _append_unique(queries, f"{name} {code} {number}")
        _append_unique(queries, f"{name} {number}")
        _append_unique(queries, f"{code} {number}")
        _append_unique(queries, f"pokemon {code} {number}")

    if name and number:
        if variant:
            _append_unique(queries, f"{name} {variant} {number}")
        _append_unique(queries, f"{name} {number}")
        _append_unique(queries, f"pokemon {name} {number}")
        _append_unique(queries, f"pokemon {name}")
        _append_unique(queries, f"pokemon card {name}")

    if full_number:
        _append_unique(queries, f"pokemon {full_number}")
        _append_unique(queries, f"pokemon card {full_number}")
        _append_unique(queries, f"carta pokemon {full_number}")
        _append_unique(queries, f"carte pokemon {full_number}")
        _append_unique(queries, f"tarjeta pokemon {full_number}")

    if name and variant:
        _append_unique(queries, f"{name} {variant}")
        _append_unique(queries, f"pokemon {name} {variant}")
        _append_unique(queries, f"pokemon {name}")

    if signals.kind == "sealed_product":
        if signals.set_name:
            _append_unique(queries, f"pokemon {signals.set_name}")
        if "etb" in signals.normalized_title or "elite trainer box" in signals.normalized_title:
            _append_unique(queries, "pokemon etb")
            _append_unique(queries, "pokemon elite trainer box")
        elif "booster" in signals.normalized_title or "display" in signals.normalized_title:
            _append_unique(queries, "pokemon booster box")
            _append_unique(queries, "pokemon booster")

    if signals.kind == "lot_bundle":
        _append_unique(queries, "pokemon card lot")
        _append_unique(queries, "pokemon cards bundle")

    if name:
        _append_unique(queries, f"pokemon {name} card")
        _append_unique(queries, f"pokemon {name}")
    if code:
        _append_unique(queries, f"pokemon {code}")
    is_pokemon_candidate = bool(
        name or number or full_number or code or _contains_pokemon_keyword(signals.normalized_title)
    )
    if number:
        _append_unique(queries, f"pokemon {number}")
    if is_pokemon_candidate:
        _append_unique(queries, "pokemon card")
    if not queries and _contains_pokemon_keyword(signals.normalized_title):
        _append_unique(queries, signals.normalized_title)
        _append_unique(queries, "pokemon card")

    return queries[:12]


def parse_listing_identity(title: str) -> ParsedListingIdentity:
    signals = extract_card_signals(title)
    query = signals.queries[0] if signals.queries else signals.normalized_title
    return ParsedListingIdentity(
        confidence=signals.confidence,
        query=query,
        listing_kind=signals.kind if signals.kind != "unknown" else None,
        extracted_name=signals.pokemon_name or signals.keyword_name,
        extracted_number=signals.full_number or signals.card_number,
        extracted_set=signals.set_code or signals.set_name,
        fallback_query_used=signals.confidence == "LOW",
        is_pokemon_related=signals.confidence != "UNKNOWN",
        signals=signals,
    )
