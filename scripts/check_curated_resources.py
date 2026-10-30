"""Check every link in dataset/curated_resources.json and print the broken ones.

    python scripts/check_curated_resources.py

Uses plain HTTP requests from your machine (some sites block bots and may show
a false alarm; open those in a browser). Exit code is 1 if any link failed.
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; LearningPathBot/1.0)"}


def check(entry):
    skill, item = entry
    url = item["url"]
    try:
        response = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True, stream=True)
        status = response.status_code
        response.close()
    except requests.exceptions.RequestException as exc:
        return skill, url, f"ERROR {type(exc).__name__}"
    return skill, url, "ok" if status < 400 else f"HTTP {status}"


def main() -> int:
    with open(os.path.join(ROOT, "dataset", "curated_resources.json"), encoding="utf-8") as handle:
        data = json.load(handle)["skills"]
    entries = [(skill, item) for skill, items in data.items() for item in items]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(check, entries))
    bad = [r for r in results if r[2] != "ok"]
    for skill, url, status in bad:
        print(f"{status:<24} {skill}: {url}")
    print(f"\n{len(results) - len(bad)}/{len(results)} links ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
