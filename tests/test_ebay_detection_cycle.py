import inspect
import unittest
from collections import deque

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


if __name__ == "__main__":
    unittest.main()
