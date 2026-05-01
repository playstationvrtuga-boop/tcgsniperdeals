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
            "EBAY_SEEN_TTL_HOURS": bot.EBAY_SEEN_TTL_HOURS,
            "MAX_EBAY_SEEN_ITEMS": bot.MAX_EBAY_SEEN_ITEMS,
        }
        bot.FICHEIRO_VISTOS = str(self.seen_file)
        bot.FICHEIRO_VISTOS_EBAY_DEBUG = str(self.debug_seen_file)
        bot.EBAY_DEBUG_IGNORE_MAIN_VISTOS = False
        bot.EBAY_SEEN_TTL_HOURS = 6
        bot.MAX_EBAY_SEEN_ITEMS = 100

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

    def test_guardar_visto_writes_timestamped_ebay_entry(self):
        bot.guardar_visto("ebay_555555555555")

        raw = self.seen_file.read_text(encoding="utf-8").strip()
        self.assertTrue(raw.startswith("ebay_555555555555\t"))
        self.assertIn("ebay_555555555555", bot.carregar_vistos())

    def test_ebay_app_duplicate_does_not_mark_seen(self):
        marked = bot.mark_seen_after_app_delivery(
            {"id": "ebay_666666666666", "source": "ebay"},
            {"status": "duplicate"},
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


if __name__ == "__main__":
    unittest.main()
