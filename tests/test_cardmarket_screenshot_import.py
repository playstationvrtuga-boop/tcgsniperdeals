import unittest

from services.cardmarket_screenshot_import import parse_cardmarket_screenshot_text


class CardmarketScreenshotImportTests(unittest.TestCase):
    def test_parse_manual_text_into_best_sellers_and_bargains(self):
        text = """
        Best Sellers
        1. Meowth ex (POR 062) 5,90 €
        2. Poke Pad (POR 081) 0,02 €

        Best Bargains!
        1. Jigglypuff (MCD16 8) 0,40 €
        2. Kyurem (BW 44) 0,98 €
        """

        slots = parse_cardmarket_screenshot_text(text)

        self.assertEqual(len(slots), 4)
        self.assertEqual(slots[0].category, "best_sellers")
        self.assertEqual(slots[0].rank, 1)
        self.assertEqual(slots[0].product_name, "Meowth ex")
        self.assertEqual(slots[0].expansion, "POR")
        self.assertEqual(slots[0].card_number, "062")
        self.assertEqual(slots[0].price, 5.90)
        self.assertEqual(slots[2].category, "best_bargains")
        self.assertEqual(slots[2].product_name, "Jigglypuff")


if __name__ == "__main__":
    unittest.main()
