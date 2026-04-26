import unittest

from services.pokemon_title_parser import (
    classify_listing_kind,
    detect_pokemon_name,
    extract_card_signals,
    generate_generic_alias_queries,
    normalize_title,
)


class PokemonTitleParserTests(unittest.TestCase):
    def test_normalize_title_handles_accents_emojis_and_numbers(self):
        title = "🔥 Marshadow 080 / 132 Reverse. Me1. Méga évolution. Pokémon."

        normalized = normalize_title(title)

        self.assertNotIn("🔥", normalized)
        self.assertIn("pokemon", normalized)
        self.assertIn("mega evolution", normalized)
        self.assertIn("080/132", normalized)

    def test_normalize_title_handles_number_prefixes(self):
        self.assertIn("125", normalize_title("No.125 Charizard"))
        self.assertIn("125", normalize_title("nº125 Charizard"))
        self.assertIn("125", normalize_title("Card 125 Charizard"))
        self.assertIn("125", normalize_title("Carta 125 Charizard"))

    def test_detect_pokemon_name_uses_base_and_aliases(self):
        self.assertEqual(detect_pokemon_name("Dracaufeu 125 Pokemon"), "charizard")
        self.assertEqual(detect_pokemon_name("Gengar VMAX 271"), "gengar")

    def test_charizard_x_is_treated_as_ex_variant(self):
        signals = extract_card_signals("🔥 Charizard x 125 PFL rare Pokémon card")

        self.assertEqual(signals.pokemon_name, "charizard")
        self.assertEqual(signals.card_number, "125")
        self.assertEqual(signals.set_code, "PFL")
        self.assertEqual(signals.variant, "ex")
        self.assertEqual(signals.confidence, "HIGH")
        self.assertEqual(signals.decision, "process")

    def test_marshadow_full_number_set_code_and_french_text(self):
        signals = extract_card_signals("Marshadow 080 / 132 Reverse. Me1. Méga évolution. Pokémon.")

        self.assertEqual(signals.pokemon_name, "marshadow")
        self.assertEqual(signals.card_number, "080")
        self.assertEqual(signals.full_number, "080/132")
        self.assertEqual(signals.set_code, "ME1")
        self.assertEqual(signals.variant, "mega")
        self.assertEqual(signals.confidence, "HIGH")

    def test_trainer_card_with_full_number_is_medium_not_skipped(self):
        signals = extract_card_signals("Compassion de Timmy 085/063 SR - Mega Symphonia - Pokémon Japonais")

        self.assertIsNone(signals.pokemon_name)
        self.assertEqual(signals.card_number, "085")
        self.assertEqual(signals.full_number, "085/063")
        self.assertEqual(signals.rarity, "SR")
        self.assertEqual(signals.set_name, "mega symphonia")
        self.assertEqual(signals.language, "japanese")
        self.assertEqual(signals.confidence, "MEDIUM")
        self.assertEqual(signals.decision, "process")

    def test_lot_bundle_is_low_and_processed(self):
        signals = extract_card_signals("Sobre de 30 Cartas Pokémon Originais - Variadas")

        self.assertEqual(signals.kind, "lot_bundle")
        self.assertEqual(signals.confidence, "LOW")
        self.assertEqual(signals.decision, "process")

    def test_inteleon_number_and_set_name_is_medium(self):
        signals = extract_card_signals("Pokémon Inteleon 142 Mega evolution")

        self.assertEqual(signals.pokemon_name, "inteleon")
        self.assertEqual(signals.card_number, "142")
        self.assertEqual(signals.set_name, "mega evolution")
        self.assertEqual(signals.confidence, "MEDIUM")

    def test_query_generation_multiple_aliases(self):
        signals = extract_card_signals("Pikachu 025/198")
        queries = generate_generic_alias_queries(signals)

        self.assertIn("pikachu 025/198", queries)
        self.assertIn("pokemon 025/198", queries)
        self.assertIn("025/198 pikachu", queries)
        self.assertGreaterEqual(len(queries), 4)

    def test_classify_sealed_and_graded(self):
        sealed = extract_card_signals("Pokemon ETB Ascended Heroes sealed")
        graded = extract_card_signals("Charizard PSA 10 slab")

        self.assertEqual(classify_listing_kind(sealed), "sealed_product")
        self.assertEqual(classify_listing_kind(graded), "graded_card")
        self.assertEqual(graded.confidence, "HIGH")

    def test_unknown_without_pokemon_signals_is_skipped(self):
        signals = extract_card_signals("Vintage football shirt")

        self.assertEqual(signals.confidence, "UNKNOWN")
        self.assertEqual(signals.decision, "skip")


if __name__ == "__main__":
    unittest.main()
