import json
import tempfile
from pathlib import Path
import unittest

import services.free_promos as free_promos


class FreePromosTests(unittest.TestCase):
    def test_reply_markup_hides_url_in_button(self):
        markup = free_promos._build_reply_markup("Open App", "https://example.com")
        self.assertIn('"text": "Open App"', markup)
        self.assertIn('"url": "https://example.com"', markup)

    def test_pick_image_avoids_last_image_when_possible(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            img1 = tmp_path / "promo_a.png"
            img2 = tmp_path / "promo_b.jpg"
            img1.write_bytes(b"a")
            img2.write_bytes(b"b")

            state_file = tmp_path / "state.json"
            state_file.write_text(
                json.dumps({"last_image": str(img1), "last_sent_at": "", "sent_count": 1}),
                encoding="utf-8",
            )

            old_state_file = free_promos.STATE_FILE
            try:
                free_promos.STATE_FILE = state_file
                chosen = free_promos._pick_image([img1, img2])
                self.assertEqual(chosen, img2)
            finally:
                free_promos.STATE_FILE = old_state_file

    def test_load_promo_images_filters_supported_extensions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            (tmp_path / "promo_1.png").write_bytes(b"1")
            (tmp_path / "promo_2.webp").write_bytes(b"2")
            (tmp_path / "ignore.txt").write_text("x", encoding="utf-8")

            old_folder = free_promos.FREE_PROMO_FOLDER
            try:
                free_promos.FREE_PROMO_FOLDER = str(tmp_path)
                images = free_promos._load_promo_images()
                self.assertEqual([path.name for path in images], ["promo_1.png", "promo_2.webp"])
            finally:
                free_promos.FREE_PROMO_FOLDER = old_folder


if __name__ == "__main__":
    unittest.main()
