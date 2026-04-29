import unittest

from services.wallapop_scraper import (
    derive_wallapop_external_id,
    filter_wallapop_candidates,
    should_send_wallapop_to_telegram,
)
from vip_app.app.api import normalize_platform


class WallapopScraperTests(unittest.TestCase):
    def test_source_wallapop_is_accepted(self):
        [item] = filter_wallapop_candidates(
            [
                {
                    "title": "Pokemon TCG Charizard 125/197",
                    "price": "20 €",
                    "url": "https://es.wallapop.com/item/pokemon-charizard-123",
                }
            ],
            max_items=2,
        )

        self.assertEqual(item["source"], "wallapop")
        self.assertEqual(item["platform"], "Wallapop")
        self.assertEqual(item["external_id"], "wallapop_pokemon-charizard-123")
        self.assertEqual(normalize_platform("wallapop"), "Wallapop")

    def test_max_two_items_per_cycle(self):
        candidates = [
            {"title": f"Pokemon TCG card {idx}/100", "price": "10 €", "url": f"https://es.wallapop.com/item/card-{idx}"}
            for idx in range(5)
        ]

        self.assertEqual(len(filter_wallapop_candidates(candidates, max_items=2)), 2)

    def test_dedupe_uses_external_id_or_url(self):
        url = "https://es.wallapop.com/item/pokemon-pikachu-999"
        seen_id = derive_wallapop_external_id(url)
        items = filter_wallapop_candidates(
            [
                {"title": "Pokemon TCG Pikachu 25/25", "price": "12 €", "url": url},
                {"title": "Pokemon TCG Mewtwo 56/165", "price": "18 €", "url": "https://es.wallapop.com/item/mewtwo-56"},
            ],
            seen_ids={seen_id},
            max_items=2,
        )

        self.assertEqual(len(items), 1)
        self.assertIn("mewtwo", items[0]["external_id"])

    def test_rejects_non_tcg_junk(self):
        items = filter_wallapop_candidates(
            [
                {"title": "Pokemon Funko Pop Charizard", "price": "9 €", "url": "https://es.wallapop.com/item/funko"},
                {"title": "Nintendo Switch Pokemon game", "price": "25 €", "url": "https://es.wallapop.com/item/switch-game"},
            ],
            max_items=2,
        )

        self.assertEqual(items, [])

    def test_wallapop_telegram_disabled_by_default_flag(self):
        self.assertFalse(should_send_wallapop_to_telegram({"source": "wallapop"}, send_enabled=False))
        self.assertTrue(should_send_wallapop_to_telegram({"source": "vinted"}, send_enabled=False))


if __name__ == "__main__":
    unittest.main()
