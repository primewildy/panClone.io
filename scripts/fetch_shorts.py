#!/usr/bin/env python3
"""Scrape YouTube shorts for a channel handle and emit JSON.

The script performs a simple HTTP GET on the shorts tab for a channel handle,
parses the embedded ``ytInitialData`` payload, and extracts unique video IDs.

Usage:

    python scripts/fetch_shorts.py --handle @EEUK --output data/ee-shorts.json

The resulting JSON file contains objects with the short id and canonical URL.
"""

from __future__ import annotations

import argparse
import json
from collections import deque
from pathlib import Path
from typing import Iterable, List

import requests


SHORT_URL_TEMPLATE = "https://www.youtube.com/shorts/{video_id}"


def fetch_shorts_page(handle: str) -> str:
    """Fetch the raw HTML for the shorts tab of a YouTube handle."""

    if not handle.startswith("@"):
        handle = f"@{handle}"

    url = f"https://www.youtube.com/{handle}/shorts"
    headers = {
        # Spoof curl to obtain the server-rendered page that includes
        # the ``ytInitialData`` payload. Modern desktop UAs often receive
        # a shell that relies on client-side JS, which is harder to parse.
        "User-Agent": "curl/7.88.1",
    }
    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()
    return response.text


def extract_ytinitialdata(html: str) -> dict:
    """Locate and decode the ``ytInitialData`` blob from the HTML."""

    marker = "var ytInitialData = "
    start = html.find(marker)
    if start == -1:
        raise ValueError("Could not locate ytInitialData in response")
    start = html.find("{", start)
    if start == -1:
        raise ValueError("Malformed ytInitialData payload")

    depth = 0
    for idx in range(start, len(html)):
        char = html[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = idx + 1
                break
    else:
        raise ValueError("Failed to determine end of ytInitialData payload")

    json_blob = html[start:end]
    return json.loads(json_blob)


def extract_video_ids(html: str, limit: int | None = 50) -> List[str]:
    """Extract unique shorts video IDs from the YouTube HTML payload."""

    data = extract_ytinitialdata(html)
    seen = set()
    ordered: List[str] = []
    queue = deque([data])

    while queue:
        node = queue.popleft()
        if isinstance(node, dict):
            endpoint = node.get("reelWatchEndpoint")
            if isinstance(endpoint, dict):
                video_id = endpoint.get("videoId")
                if video_id and video_id not in seen:
                    seen.add(video_id)
                    ordered.append(video_id)
                    if limit and len(ordered) >= limit:
                        break
            queue.extend(node.values())
        elif isinstance(node, list):
            queue.extend(node)

    return ordered


def write_json(output: Path, ids: Iterable[str]) -> None:
    """Persist the extracted shorts as a JSON array."""

    output.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "id": video_id,
            "url": SHORT_URL_TEMPLATE.format(video_id=video_id),
        }
        for video_id in ids
    ]
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch YouTube shorts list")
    parser.add_argument("--handle", required=True, help="Channel handle (e.g. @EEUK)")
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Path to write the JSON payload",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of shorts to record (default: 50)",
    )
    args = parser.parse_args()

    html = fetch_shorts_page(args.handle)
    video_ids = extract_video_ids(html, limit=args.limit)
    if not video_ids:
        raise SystemExit("No shorts were discovered in the supplied channel page")
    write_json(args.output, video_ids)
    print(f"Wrote {len(video_ids)} shorts to {args.output}")


if __name__ == "__main__":
    main()
