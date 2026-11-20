"""Save a user's public Bangumi collections as a local JSON snapshot."""

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


def collect(username, user_agent, *, max_pages=100):
    if max_pages < 1:
        raise ValueError("--max-pages must be positive")
    root = "https://api.bgm.tv/v0/users/" + quote(username, safe="")

    def get(url):
        with urlopen(Request(url, headers={"User-Agent": user_agent}), timeout=20) as response:
            return json.load(response)

    profile = get(root)
    rows = {}
    offset = 0
    for _ in range(max_pages):
        page = get(root + "/collections?" + urlencode({"limit": 50, "offset": offset}))
        data = page["data"]
        if page["offset"] != offset:
            raise ValueError("Unexpected Bangumi page offset")
        for row in data:
            if not row.get("private"):
                rows[row["subject_id"]] = row
        offset += len(data)
        if offset >= page["total"]:
            break
        if not data:
            raise ValueError("Bangumi pagination stopped before the reported total")
        time.sleep(0.25)
    return {
        "profile_url": "https://bgm.tv/user/" + quote(username, safe=""),
        "profile": profile,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "rows": list(rows.values()),
        "total": page["total"],
        "complete": offset >= page["total"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("username")
    parser.add_argument("output", type=Path)
    parser.add_argument("--user-agent", required=True, help="Your identifiable application and contact")
    parser.add_argument("--max-pages", type=int, default=100)
    args = parser.parse_args()
    payload = collect(args.username, args.user_agent, max_pages=args.max_pages)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
    print(f"Saved {len(payload['rows'])} public collections")
    if not payload["complete"]:
        print("Reached --max-pages. The saved snapshot is partial.")


if __name__ == "__main__":
    main()
