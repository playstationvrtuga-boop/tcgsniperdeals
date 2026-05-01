import json
import unittest

from services.telegram_alerts import _build_inline_button


class TelegramAlertsTests(unittest.TestCase):
    def test_inline_button_hides_url_behind_button_text(self):
        markup = json.loads(_build_inline_button("Get VIP Access", "https://tcgsniperdeals.com"))
        button = markup["inline_keyboard"][0][0]
        self.assertEqual(button["text"], "Get VIP Access")
        self.assertEqual(button["url"], "https://tcgsniperdeals.com")


if __name__ == "__main__":
    unittest.main()
