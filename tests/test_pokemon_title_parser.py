import unittest

from services.pokemon_title_parser import (
    clean_pricing_query,
    classify_listing_kind,
    detect_pokemon_name,
    extract_card_signals,
    generate_generic_alias_queries,
    is_valid_query,
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

    def test_pokemon_word_is_never_auto_skipped(self):
        examples = [
            "Stufful Pokemon TCG AR",
            "Carte pokemon forces temporelles",
            "Assortimento carte Pokemon",
        ]

        for title in examples:
            with self.subTest(title=title):
                signals = extract_card_signals(title)
                self.assertNotEqual(signals.confidence, "UNKNOWN")
                self.assertEqual(signals.kind, "unknown_pokemon")
                self.assertEqual(signals.confidence, "LOW")
                self.assertEqual(signals.decision, "process")

    def test_known_name_without_pokemon_word_is_processed(self):
        signals = extract_card_signals("Gengar reverse vintage")

        self.assertEqual(signals.pokemon_name, "gengar")
        self.assertEqual(signals.confidence, "LOW")
        self.assertEqual(signals.decision, "process")

    def test_number_only_signal_is_processed_low_confidence(self):
        signals = extract_card_signals("Moramartik ex 003/182")

        self.assertEqual(signals.keyword_name, "moramartik")
        self.assertEqual(signals.full_number, "003/182")
        self.assertEqual(signals.variant, "ex")
        self.assertEqual(signals.confidence, "LOW")
        self.assertEqual(signals.decision, "process")

    def test_aggressive_query_cascade_for_specific_title(self):
        signals = extract_card_signals("Moramartik ex 003/182")

        self.assertGreaterEqual(len(signals.queries), 9)
        self.assertEqual(signals.queries[0], "moramartik ex 003/182")
        self.assertIn("moramartik 003/182", signals.queries)
        self.assertIn("moramartik ex 003", signals.queries)
        self.assertIn("moramartik 003", signals.queries)
        self.assertIn("pokemon moramartik", signals.queries)
        self.assertIn("pokemon moramartik", signals.queries)
        self.assertIn("pokemon 003/182", signals.queries)
        self.assertIn("pokemon 003", signals.queries)
        self.assertNotIn("pokemon", signals.queries)

    def test_pricing_query_cleaner_removes_stopwords(self):
        self.assertEqual(clean_pricing_query("pokemon des 9"), "pokemon 9")
        self.assertEqual(clean_pricing_query("pokemon premier 9"), "pokemon 9")
        self.assertEqual(clean_pricing_query("pokemon cards bundle"), "pokemon")
        self.assertEqual(clean_pricing_query("pokemon card moramartik"), "pokemon moramartik")

    def test_pricing_query_validator_blocks_junk_queries(self):
        self.assertFalse(is_valid_query("pokemon des 9"))
        self.assertFalse(is_valid_query("pokemon premier 9"))
        self.assertFalse(is_valid_query("pokemon cards bundle"))
        self.assertFalse(is_valid_query("pokemon card"))
        self.assertTrue(is_valid_query("moramartik 003"))
        self.assertTrue(is_valid_query("pokemon 003/182"))
        self.assertTrue(is_valid_query("lugia v"))
        self.assertTrue(is_valid_query("charizard pokemon card"))


if __name__ == "__main__":
    unittest.main()
