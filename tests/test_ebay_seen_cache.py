import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import vinted_olx_bot as bot


class EbaySeenCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.seen_file = Path(self.temp_dir.name) / "vistos.txt"
        self.debug_seen_file = Path(self.temp_dir.name) / "vistos_ebay_debug.txt"
        self.originals = {
            "FICHEIRO_VISTOS": bot.FICHEIRO_VISTOS,
            "FICHEIRO_VISTOS_EBAY_DEBUG": bot.FICHEIRO_VISTOS_EBAY_DEBUG,
            "EBAY_DEBUG_IGNORE_MAIN_VISTOS": bot.EBAY_DEBUG_IGNORE_MAIN_VISTOS,
            "EBAY_DEBUG_MODE": bot.EBAY_DEBUG_MODE,
            "EBAY_SEEN_TTL_HOURS": bot.EBAY_SEEN_TTL_HOURS,
            "MAX_EBAY_SEEN_ITEMS": bot.MAX_EBAY_SEEN_ITEMS,
            "MAX_VISTOS_EBAY_DEBUG_ITEMS": bot.MAX_VISTOS_EBAY_DEBUG_ITEMS,
            "FICHEIRO_TRACKING": bot.FICHEIRO_TRACKING,
        }
        bot.FICHEIRO_VISTOS = str(self.seen_file)
        bot.FICHEIRO_VISTOS_EBAY_DEBUG = str(self.debug_seen_file)
        bot.FICHEIRO_TRACKING = str(Path(self.temp_dir.name) / "tracked_listings.json")
        bot.EBAY_DEBUG_IGNORE_MAIN_VISTOS = False
        bot.EBAY_DEBUG_MODE = False
        bot.EBAY_SEEN_TTL_HOURS = 6
        bot.MAX_EBAY_SEEN_ITEMS = 100
        bot.MAX_VISTOS_EBAY_DEBUG_ITEMS = 100

    def tearDown(self):
        for key, value in self.originals.items():
            setattr(bot, key, value)
        self.temp_dir.cleanup()

    def test_ebay_seen_id_uses_item_id_from_url(self):
        cases = {
            "https://www.ebay.com/itm/123456789012?hash=abc": "ebay_123456789012",
            "https://www.ebay.com/itm/Pokemon-Charizard/123456789012?hash=abc": "ebay_123456789012",
            "https://www.ebay.es/itm/Booster-Box/987654321098": "ebay_987654321098",
        }

        for url, expected in cases.items():
            with self.subTest(url=url):
                self.assertEqual(bot.ebay_seen_id_from_link(url), expected)

    def test_seen_cache_expires_legacy_and_old_ebay_entries(self):
        now = datetime.now(timezone.utc)
        old_seen_at = (now - timedelta(hours=7)).isoformat(timespec="seconds")
        recent_seen_at = (now - timedelta(hours=1)).isoformat(timespec="seconds")
        self.seen_file.write_text(
            "\n".join(
                [
                    "ebay_111111111111",
                    f"ebay_222222222222\t{old_seen_at}",
                    f"ebay_333333333333\t{recent_seen_at}",
                    "vinted_444444",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        vistos = bot.carregar_vistos()

        self.assertNotIn("ebay_111111111111", vistos)
        self.assertNotIn("ebay_222222222222", vistos)
        self.assertIn("ebay_333333333333", vistos)
        self.assertIn("vinted_444444", vistos)

    def test_expired_seen_item_can_be_processed_again(self):
        old_seen_at = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat(timespec="seconds")
        self.seen_file.write_text(f"ebay_121212121212\t{old_seen_at}\n", encoding="utf-8")

        self.assertNotIn("ebay_121212121212", bot.carregar_vistos())

    def test_fresh_ebay_item_is_not_seen_by_default(self):
        self.assertNotIn("ebay_343434343434", bot.carregar_vistos())

    def test_guardar_visto_writes_timestamped_ebay_entry(self):
        bot.guardar_visto("ebay_555555555555")

        raw = self.seen_file.read_text(encoding="utf-8").strip()
        self.assertTrue(raw.startswith("ebay_555555555555\t"))
        self.assertIn("ebay_555555555555", bot.carregar_vistos())

    def test_ebay_app_duplicate_marks_seen(self):
        marked = bot.mark_seen_after_app_delivery(
            {"id": "ebay_666666666666", "source": "ebay"},
            {"status": "duplicate"},
        )

        self.assertTrue(marked)
        self.assertIn("ebay_666666666666", bot.carregar_vistos())

    def test_rejected_ebay_item_does_not_mark_seen(self):
        marked = bot.mark_seen_after_app_delivery(
            {"id": "ebay_686868686868", "source": "ebay"},
            {"status": "invalid_payload"},
        )

        self.assertFalse(marked)
        self.assertFalse(self.seen_file.exists())

    def test_placeholder_ebay_item_does_not_mark_seen(self):
        marked = bot.mark_seen_after_app_delivery(
            {"id": "ebay_787878787878", "source": "ebay"},
            {"status": "placeholder_item"},
        )

        self.assertFalse(marked)
        self.assertFalse(self.seen_file.exists())

    def test_ebay_app_inserted_marks_seen(self):
        marked = bot.mark_seen_after_app_delivery(
            {"id": "ebay_777777777777", "source": "ebay"},
            {"status": "inserted"},
        )

        self.assertTrue(marked)
        self.assertIn("ebay_777777777777", bot.carregar_vistos())

    def test_ebay_debug_seen_cache_expires_legacy_entries(self):
        recent_seen_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
        self.debug_seen_file.write_text(
            "\n".join(
                [
                    "ebay_888888888888",
                    f"ebay_999999999999\t{recent_seen_at}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        vistos = bot.carregar_vistos_ebay_debug()

        self.assertNotIn("ebay_888888888888", vistos)
        self.assertIn("ebay_999999999999", vistos)

    def test_inserted_ebay_debug_seen_is_timestamped(self):
        bot.EBAY_DEBUG_MODE = True
        bot.EBAY_DEBUG_IGNORE_MAIN_VISTOS = True

        marked = bot.mark_seen_after_app_delivery(
            {"id": "ebay_101010101010", "source": "ebay"},
            {"status": "inserted"},
        )

        self.assertTrue(marked)
        raw = self.debug_seen_file.read_text(encoding="utf-8").strip()
        self.assertTrue(raw.startswith("ebay_101010101010\t"))
        self.assertIn("ebay_101010101010", bot.carregar_vistos_ebay_debug())

    def test_ebay_tracking_duplicate_blocks_seen(self):
        now = bot.now_iso()
        bot.guardar_tracking(
            {
                "items": {
                    "ebay_202020202020": {
                        "platform": "ebay",
                        "app_sync_status": "duplicate",
                        "last_seen": now,
                    },
                    "ebay_303030303030": {
                        "platform": "ebay",
                        "app_sync_status": "inserted",
                        "last_seen": now,
                    },
                    "ebay_505050505050": {
                        "app_sync_status": "duplicate",
                        "last_seen": now,
                    },
                    "vinted_404040": {
                        "platform": "vinted",
                        "app_sync_status": "duplicate",
                        "last_seen": now,
                    },
                }
            }
        )

        synced = bot.carregar_ids_app_sincronizados()

        self.assertIn("ebay_202020202020", synced)
        self.assertIn("ebay_505050505050", synced)
        self.assertIn("ebay_303030303030", synced)
        self.assertIn("vinted_404040", synced)

    def test_ebay_search_queries_are_broader_buy_it_now(self):
        queries = [query for _category, query in bot.EBAY_SEARCH_QUERIES_POKEMON]

        self.assertIn("pokemon card holo rare ex gx v vmax vstar full art", queries)
        self.assertIn("pokemon psa cgc bgs graded card", queries)
        self.assertIn("pokemon booster box etb elite trainer box sealed booster bundle", queries)
        self.assertIn("charizard pokemon card", queries)
        self.assertIn("pokemon 151 booster bundle", queries)
        self.assertIn("pokemon elite trainer box", queries)
        self.assertTrue(all("LH_BIN=1" in url and "_sop=10" in url and "_ipg=100" in url for url in bot.EBAY_SEARCH_URLS_POKEMON))
        self.assertFalse(any(term in " ".join(bot.EBAY_SEARCH_EXCLUDE_TERMS) for term in ["-japanese", "-french", "-german", "-spanish"]))


if __name__ == "__main__":
    unittest.main()
