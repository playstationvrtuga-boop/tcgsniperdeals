import inspect
import unittest
from collections import deque
from types import SimpleNamespace

import vinted_olx_bot as bot


class EbayDetectionCycleTests(unittest.TestCase):
    def test_ebay_cycle_continues_after_first_round(self):
        originals = {
            "LIGHT_MODE": bot.LIGHT_MODE,
            "EBAY_FETCH_EVERY": bot.EBAY_FETCH_EVERY,
            "EBAY_FORCE_ALWAYS_ON_DEBUG": bot.EBAY_FORCE_ALWAYS_ON_DEBUG,
        }
        try:
            bot.LIGHT_MODE = True
            bot.EBAY_FETCH_EVERY = 1
            bot.EBAY_FORCE_ALWAYS_ON_DEBUG = False

            self.assertTrue(bot.should_process_ebay_cycle(1))
            self.assertTrue(bot.should_process_ebay_cycle(2))
            self.assertTrue(bot.should_process_ebay_cycle(50))
        finally:
            for key, value in originals.items():
                setattr(bot, key, value)

    def test_search_page_urls_keep_newest_sort_and_add_pagination(self):
        search_url = bot.build_ebay_search_url("pokemon charizard card")

        page_urls = bot.ebay_search_page_urls(search_url, max_pages=3)

        self.assertEqual(len(page_urls), 3)
        self.assertTrue(all("_sop=10" in url for url in page_urls))
        self.assertTrue(all("LH_BIN=1" in url for url in page_urls))
        self.assertIn("_pgn=1", page_urls[0])
        self.assertIn("_pgn=2", page_urls[1])
        self.assertIn("_pgn=3", page_urls[2])

    def test_search_page_urls_are_capped_to_three_pages(self):
        search_url = bot.build_ebay_search_url("pokemon booster box")

        page_urls = bot.ebay_search_page_urls(search_url, max_pages=10)

        self.assertEqual(len(page_urls), 3)
        self.assertIn("_pgn=3", page_urls[-1])

    def test_already_seen_warning_requires_several_stale_cycles(self):
        history = deque(
            [
                {"results": 10, "already_seen": 9},
                {"results": 20, "already_seen": 18},
                {"results": 11, "already_seen": 10},
            ],
            maxlen=3,
        )

        self.assertTrue(bot.ebay_stale_seen_warning_active(history))

    def test_already_seen_warning_does_not_block_new_ids(self):
        history = deque(
            [
                {"results": 10, "already_seen": 9},
                {"results": 20, "already_seen": 18},
                {"results": 11, "already_seen": 8},
            ],
            maxlen=3,
        )

        self.assertFalse(bot.ebay_stale_seen_warning_active(history))

    def test_rate_limit_error_is_detected_without_raising(self):
        self.assertTrue(bot.ebay_error_is_rate_limit(Exception("HTTP 429 Too Many Requests")))
        self.assertTrue(bot.ebay_error_is_rate_limit(Exception("captcha required")))
        self.assertFalse(bot.ebay_error_is_rate_limit(Exception("selector timeout")))

    def test_detector_does_not_use_pricing_cache_for_search_detection(self):
        source = inspect.getsource(bot.obter_ebay_links)

        self.assertNotIn("price_cache", source)
        self.assertNotIn("cache_ebay_sold", source)

    def test_duplicate_seen_is_checked_without_marking_seen_during_detection(self):
        source = inspect.getsource(bot.obter_ebay_links)

        self.assertIn("if id_item in vistos", source)
        self.assertNotIn("guardar_visto(", source)
        self.assertNotIn("guardar_visto_ebay_debug(", source)

    def test_search_title_uses_real_card_line_not_empty_anchor(self):
        card_text = "\n".join(
            [
                "New low price",
                "Random Pokemon Graded Card From Years 1996 & Up PSA | BGS | CGC",
                "Opens in a new window or tab",
                "Brand New",
                "US $15.29",
            ]
        )

        self.assertEqual(
            bot.ebay_search_title_from_card(card_text),
            "Random Pokemon Graded Card From Years 1996 & Up PSA | BGS | CGC",
        )

    def test_search_payload_can_skip_detail_page(self):
        candidate = {
            "use_search_payload": True,
            "search_title": "Pokemon Charizard ex 125/197 TCG Card",
            "search_price": "US $12.99",
            "image_url": "https://example.com/card.jpg",
            "search_english_validation": {"passed": True, "reason": "english_title_signal"},
            "excluded_keyword_value": None,
        }

        title, price, image, _published_at, tcg_type, reject, debug, _seller = bot.ebay_candidate_search_payload(candidate)

        self.assertTrue(bot.ebay_candidate_has_usable_search_payload(candidate))
        self.assertEqual(title, "Pokemon Charizard ex 125/197 TCG Card")
        self.assertEqual(price, "US $12.99")
        self.assertEqual(image, "https://example.com/card.jpg")
        self.assertEqual(tcg_type, "pokemon")
        self.assertIsNone(reject)
        self.assertEqual(debug["classification"], "buy_now_search_result")

    def test_api_item_builds_search_payload_candidate(self):
        item = SimpleNamespace(
            title="Pokemon Charizard ex 125/197 TCG Card",
            price_value="12.99",
            price_currency="USD",
            item_url="https://www.ebay.com/itm/123456789012",
            item_id="v1|123456789012|0",
            image_url="https://example.com/card.jpg",
            item_creation_date="2026-05-01T18:30:00.000Z",
            buying_options=["FIXED_PRICE"],
            seller_username="seller",
        )

        candidate = bot.ebay_api_candidate_from_item(item, "pokemon charizard", "raw", 1)

        self.assertEqual(candidate["link"], "https://www.ebay.com/itm/123456789012")
        self.assertEqual(candidate["search_price"], "US $12.99")
        self.assertEqual(candidate["_seen_id"], "ebay_123456789012")
        self.assertTrue(bot.ebay_candidate_has_usable_search_payload(candidate))

    def test_allocation_fills_unused_slots_from_available_category(self):
        originals = {
            "EBAY_MAX_CANDIDATES_PER_CYCLE": bot.EBAY_MAX_CANDIDATES_PER_CYCLE,
            "EBAY_ALLOCATION": bot.EBAY_ALLOCATION.copy(),
        }
        try:
            bot.EBAY_MAX_CANDIDATES_PER_CYCLE = 8
            bot.EBAY_ALLOCATION = {"raw": 4, "sealed": 2, "graded": 2}
            candidates = {
                "raw": [],
                "sealed": [],
                "graded": [
                    {"link": f"https://www.ebay.com/itm/{100000000000 + idx}"}
                    for idx in range(6)
                ],
            }

            selected = bot.select_ebay_candidates_by_allocation(candidates)

            self.assertEqual(len(selected), 6)
        finally:
            bot.EBAY_MAX_CANDIDATES_PER_CYCLE = originals["EBAY_MAX_CANDIDATES_PER_CYCLE"]
            bot.EBAY_ALLOCATION = originals["EBAY_ALLOCATION"]


if __name__ == "__main__":
    unittest.main()
