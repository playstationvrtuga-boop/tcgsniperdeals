import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from services.wallapop_scraper import (
    WALLAPOP_BASE_URL,
    WALLAPOP_QUERIES,
    _auto_install_playwright_browser,
    _extract_wallapop_link_urls_from_html,
    _extract_items_from_page,
    _read_wallapop_body_text,
    _wait_for_wallapop_results,
    derive_wallapop_external_id,
    filter_wallapop_candidates,
    should_send_wallapop_to_telegram,
    wallapop_candidate_reason,
    wallapop_max_items,
    wallapop_max_queries_per_run,
)
from vip_app.app.api import normalize_platform


class WallapopScraperTests(unittest.TestCase):
    def test_uses_collectibles_search_for_primary_pokemon_query(self):
        self.assertEqual(WALLAPOP_QUERIES[:3], ["pokemon", "cartas pokemon", "pokemon tcg"])
        self.assertEqual(WALLAPOP_BASE_URL.format(query="pokemon"), "https://pt.wallapop.com/colecionismo?keywords=pokemon")

    def test_memory_safe_defaults_limit_wallapop_work(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(wallapop_max_items(), 1)
            self.assertEqual(wallapop_max_queries_per_run(), 2)

    def test_playwright_install_is_cached_by_flag_file(self):
        class Result:
            returncode = 0
            stdout = "installed"

        with tempfile.TemporaryDirectory() as tmpdir:
            flag = Path(tmpdir) / "playwright_installed"
            output = io.StringIO()
            with patch.dict(
                "os.environ",
                {
                    "WALLAPOP_AUTO_INSTALL_PLAYWRIGHT": "true",
                    "WALLAPOP_PLAYWRIGHT_INSTALL_FLAG": str(flag),
                },
            ):
                with patch("services.wallapop_scraper._PLAYWRIGHT_INSTALL_LOGGED", False):
                    with patch("services.wallapop_scraper.subprocess.run", return_value=Result()) as run_mock:
                        with redirect_stdout(output):
                            self.assertTrue(_auto_install_playwright_browser())
                            self.assertTrue(_auto_install_playwright_browser())

            run_mock.assert_called_once()
            self.assertTrue(flag.exists())
            logs = output.getvalue()
            self.assertIn("[WALLAPOP_PLAYWRIGHT_INSTALL] status=starting", logs)
            self.assertIn("[WALLAPOP_PLAYWRIGHT_INSTALL] status=ok", logs)
            self.assertIn("[WALLAPOP_PLAYWRIGHT_INSTALL] status=skipped_cached", logs)

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

    def test_duplicate_rejections_are_counted_in_stats(self):
        url = "https://es.wallapop.com/item/pokemon-pikachu-999"
        stats = {"accepted": 0, "rejected": 0, "duplicates": 0, "timeouts": 0, "query_errors": 0}

        items = filter_wallapop_candidates(
            [{"title": "Pokemon TCG Pikachu 25/25", "price": "12 â‚¬", "url": url}],
            seen_ids={derive_wallapop_external_id(url)},
            max_items=2,
            stats=stats,
        )

        self.assertEqual(items, [])
        self.assertEqual(stats["duplicates"], 1)
        self.assertEqual(stats["rejected"], 1)

    def test_duplicate_first_result_continues_to_next_candidates(self):
        duplicate_url = "https://es.wallapop.com/item/pokemon-pikachu-999"
        stats = {"accepted": 0, "rejected": 0, "duplicates": 0, "timeouts": 0, "query_errors": 0}
        output = io.StringIO()

        with redirect_stdout(output):
            items = filter_wallapop_candidates(
                [
                    {"title": "Pokemon TCG Pikachu 25/25", "price": "12 â‚¬", "url": duplicate_url},
                    {"title": "Pokemon TCG Mewtwo 56/165", "price": "18 â‚¬", "url": "https://es.wallapop.com/item/mewtwo-56"},
                    {"title": "Pokemon booster sealed", "price": "6 â‚¬", "url": "https://es.wallapop.com/item/booster-6"},
                ],
                seen_ids={derive_wallapop_external_id(duplicate_url)},
                max_items=2,
                stats=stats,
            )

        self.assertEqual(len(items), 2)
        self.assertEqual(stats["duplicates"], 1)
        self.assertIn("[WALLAPOP_CANDIDATE]", output.getvalue())
        self.assertIn("[WALLAPOP_DUPLICATE]", output.getvalue())

    def test_extract_items_uses_dom_item_links_with_scan_limit(self):
        class Anchor:
            def __init__(self, idx):
                self.idx = idx

            def get_attribute(self, name):
                if name == "href":
                    return f"https://pt.wallapop.com/item/pokemon-card-{self.idx}"
                if name == "src":
                    return f"https://img.example/{self.idx}.jpg"
                return ""

            def query_selector(self, _selector):
                return self

            def inner_text(self):
                return f"{10 + self.idx} €\nPokemon TCG card {self.idx}/100\nEnvio disponível"

        class Page:
            def query_selector_all(self, selector):
                self.selector = selector
                return [Anchor(idx) for idx in range(14)]

        page = Page()

        items = _extract_items_from_page(page, "pokemon tcg")

        self.assertEqual(len(items), 12)
        self.assertEqual(items[0]["price"], "10 €")
        self.assertEqual(items[0]["title"], "Pokemon TCG card 0/100")
        self.assertEqual(page.selector, 'a[href*="/item/"]')

    def test_html_link_fallback_extracts_item_urls_without_card_text(self):
        html = """
        <a href="/item/pokemon-charizard-123"></a>
        <a href="https://es.wallapop.com/app/item/pokemon-booster-456"></a>
        <a href="/app/search?keywords=pokemon"></a>
        """

        urls = _extract_wallapop_link_urls_from_html(html)

        self.assertEqual(
            urls,
            [
                "https://es.wallapop.com/item/pokemon-charizard-123",
                "https://es.wallapop.com/app/item/pokemon-booster-456",
            ],
        )

    def test_rejects_non_tcg_junk(self):
        items = filter_wallapop_candidates(
            [
                {"title": "Pokemon Funko Pop Charizard", "price": "9 €", "url": "https://es.wallapop.com/item/funko"},
                {"title": "Nintendo Switch Pokemon game", "price": "25 €", "url": "https://es.wallapop.com/item/switch-game"},
            ],
            max_items=2,
        )

        self.assertEqual(items, [])

    def test_candidate_reason_accepts_card_signal_objects(self):
        ok, reason = wallapop_candidate_reason("Charizard 4/102")

        self.assertTrue(ok)
        self.assertIn(reason, {"card_signals", "tcg_terms"})

    def test_wallapop_telegram_disabled_by_default_flag(self):
        self.assertFalse(should_send_wallapop_to_telegram({"source": "wallapop"}, send_enabled=False))
        self.assertTrue(should_send_wallapop_to_telegram({"source": "vinted"}, send_enabled=False))

    def test_body_text_timeout_does_not_abort_scrape(self):
        class FailingPage:
            def evaluate(self, _script):
                raise TimeoutError("body timed out")

        self.assertEqual(_read_wallapop_body_text(FailingPage(), "pokemon tcg"), "")

    def test_results_wait_timeout_is_non_critical(self):
        class FailingPage:
            def wait_for_selector(self, _selector, timeout):
                self.timeout = timeout
                raise TimeoutError("Page.wait_for_selector: Timeout 9000ms exceeded\nlong details")

        page = FailingPage()

        self.assertFalse(_wait_for_wallapop_results(page, "pokemon tcg"))
        self.assertGreaterEqual(page.timeout, 8000)
        self.assertLessEqual(page.timeout, 10000)


if __name__ == "__main__":
    unittest.main()
