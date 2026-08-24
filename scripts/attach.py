"""
Interactive raw CDP attach & inspect utility.
"""

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.models import Target
from core.session import CDPSession


async def inspect_target(ws_url: str, expression: str = "document.title"):
    print(f"Connecting to CDP endpoint: {ws_url}")
    dummy_target = Target(
        id="manual",
        type="page",
        title="",
        url="",
        engine="generic",
        websocket_endpoint=ws_url
    )
    session = CDPSession(dummy_target)
    try:
        await session.connect()
        await session.enable_domains(["DOM", "Runtime", "Page"])
        print(f"Connected. Evaluating: '{expression}'...")
        val = await session.evaluate_js(expression)
        print(f"Result: {json.dumps(val, indent=2)}")
    finally:
        await session.close()


def main():
    parser = argparse.ArgumentParser(description="CDP Attach & Inspect CLI")
    parser.add_argument("--ws-url", default=None, help="Explicit WebSocket URL")
    parser.add_argument("--ws-file", default="desktop_ws_url.txt", help="File containing WebSocket URL")
    parser.add_argument("--eval", default="document.title", help="JavaScript expression to evaluate")

    args = parser.parse_args()

    ws_url = args.ws_url
    if not ws_url:
        target_file = args.ws_file
        if not os.path.exists(target_file) and os.path.exists("qt_ws_url.txt"):
            target_file = "qt_ws_url.txt"

        if not os.path.exists(target_file):
            print(f"Error: WebSocket URL file '{target_file}' not found. Run discover.py first.")
            sys.exit(1)
        with open(target_file, "r") as f:
            ws_url = f.read().strip()

    if not ws_url:
        print("Error: Empty WebSocket URL.")
        sys.exit(1)

    asyncio.run(inspect_target(ws_url, args.eval))


if __name__ == "__main__":
    main()
