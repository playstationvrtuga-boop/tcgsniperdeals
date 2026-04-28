from __future__ import annotations

import argparse
import time

import config
from services.ai_market_intel import collect_cardmarket_trends_once, should_collect
from vip_app.app import create_app


def _sleep_seconds() -> int:
    interval_hours = max(int(getattr(config, "CARDMARKET_TRENDS_INTERVAL_HOURS", 24)), 1)
    return interval_hours * 3600


def run_once() -> int:
    app = create_app()
    with app.app_context():
        if not getattr(config, "CARDMARKET_TRENDS_ENABLED", True):
            print("[ai_market_intel] disabled by CARDMARKET_TRENDS_ENABLED", flush=True)
            return 0
        return collect_cardmarket_trends_once(
            source_url=config.CARDMARKET_TRENDS_SOURCE_URL,
            timeout_seconds=config.CARDMARKET_TRENDS_TIMEOUT_SECONDS,
            user_agent=config.CARDMARKET_TRENDS_USER_AGENT,
            max_items=config.CARDMARKET_TRENDS_MAX_ITEMS,
        )


def run_forever() -> None:
    app = create_app()
    with app.app_context():
        while True:
            if not getattr(config, "CARDMARKET_TRENDS_ENABLED", True):
                print("[ai_market_intel] disabled - sleeping", flush=True)
            elif should_collect(config.CARDMARKET_TRENDS_INTERVAL_HOURS):
                collect_cardmarket_trends_once(
                    source_url=config.CARDMARKET_TRENDS_SOURCE_URL,
                    timeout_seconds=config.CARDMARKET_TRENDS_TIMEOUT_SECONDS,
                    user_agent=config.CARDMARKET_TRENDS_USER_AGENT,
                    max_items=config.CARDMARKET_TRENDS_MAX_ITEMS,
                )
            else:
                print(
                    f"[ai_market_intel] snapshot fresh - next check in {_sleep_seconds() // 60}m",
                    flush=True,
                )
            time.sleep(_sleep_seconds())


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect daily Cardmarket public trend snapshots.")
    parser.add_argument("--once", action="store_true", help="Collect once and exit.")
    args = parser.parse_args()
    if args.once:
        run_once()
        return
    run_forever()


if __name__ == "__main__":
    main()
