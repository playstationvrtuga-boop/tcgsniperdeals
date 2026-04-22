import tempfile
import unittest
from pathlib import Path

from services import free_alert_queue


class FreeAlertQueueTests(unittest.TestCase):
    def test_enqueue_creates_delayed_entry_and_dedupes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_path = free_alert_queue.QUEUE_PATH
            free_alert_queue.QUEUE_PATH = Path(temp_dir) / "free_queue.json"
            try:
                eligible_at_1 = free_alert_queue.enqueue_free_alert(
                    {
                        "listing_id": 321,
                        "platform": "eBay",
                        "tcg_type": "pokemon",
                        "partial_title": "Charizard EX (special edition)",
                        "listing_price_text": "12.00 EUR",
                        "free_message_text": "test",
                    },
                    delay_minutes=15,
                )
                eligible_at_2 = free_alert_queue.enqueue_free_alert(
                    {
                        "listing_id": 321,
                        "platform": "eBay",
                        "tcg_type": "pokemon",
                        "partial_title": "Charizard EX (special edition)",
                        "listing_price_text": "12.00 EUR",
                        "free_message_text": "test",
                    },
                    delay_minutes=15,
                )
                queue_data = free_alert_queue._read_queue()
            finally:
                free_alert_queue.QUEUE_PATH = original_path

        self.assertEqual(eligible_at_1, eligible_at_2)
        self.assertEqual(len(queue_data), 1)
        self.assertEqual(queue_data[0]["listing_id"], 321)


if __name__ == "__main__":
    unittest.main()
