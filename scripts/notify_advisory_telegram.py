#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from quant_advisor_research.notifications import format_telegram_message, send_telegram_message  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Send a non-personalized advisory report summary to Telegram.")
    parser.add_argument("--report", required=True, help="Advisory report JSON path")
    parser.add_argument("--site-url", default="https://quantstrategylab.github.io/QuantAdvisorResearch")
    parser.add_argument(
        "--lang",
        default=os.environ.get("NOTIFY_LANG", "zh"),
        help="Notification language: zh or en. Defaults to NOTIFY_LANG or zh.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the message instead of sending")
    args = parser.parse_args(argv)

    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    message = format_telegram_message(report, site_url=args.site_url, lang=args.lang)
    if args.dry_run:
        print(message)
        return 0

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("Telegram notification skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is not configured.")
        return 0

    result = send_telegram_message(bot_token=token, chat_id=chat_id, text=message)
    if result.get("ok") is not True:
        raise RuntimeError("Telegram API did not acknowledge the message")
    print("Telegram notification sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
