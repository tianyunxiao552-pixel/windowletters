"""Collect public Bilibili posts and articles. Store results locally as JSONL."""

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = "https://api.bilibili.com"
DYNAMIC_FEED = "/x/polymer/web-dynamic/v1/feed/space"
DYNAMIC_DETAIL = "/x/polymer/web-dynamic/v1/detail"
OPUS_DETAIL = "/x/polymer/web-dynamic/v1/opus/detail"
ARTICLE_LIST = "/x/space/article"


def get(path, **params):
    url = API + path + "?" + urlencode(params)
    request = Request(url, headers={
        "User-Agent": "Windowletters/1.0",
        "Referer": "https://www.bilibili.com/",
        "Accept": "application/json",
    })
    with urlopen(request, timeout=18) as response:
        payload = json.load(response)
    if payload.get("code") != 0:
        raise ValueError(f"Bilibili API code {payload.get('code')} at {path}")
    return payload["data"]


def timestamp(value):
    if isinstance(value, (int, float)) and value > 0:
        return datetime.fromtimestamp(value, timezone.utc).isoformat()
    return ""


def text_parts(value):
    """Yield text fields from Opus rich-text nodes without copying metadata."""
    if isinstance(value, list):
        for item in value:
            yield from text_parts(item)
    elif isinstance(value, dict):
        for key in ("text", "words", "word", "nodes", "rich_text_nodes", "paragraphs", "content"):
            field = value.get(key)
            if isinstance(field, str) and field:
                yield field
                return
            if field:
                parts = list(text_parts(field))
                if parts:
                    yield from parts
                    return


def normalize(item, *, fallback_id=None, source_url=None):
    modules = item.get("modules") or {}
    post_id = str(item.get("id_str") or fallback_id or "")
    if not post_id:
        raise ValueError("A Bilibili post is missing its ID")
    title, body, published = "", "", ""
    article_id = None
    if isinstance(modules, list):
        for module in modules:
            if value := module.get("module_title"):
                title = value.get("text") or value.get("title") or title
            if value := module.get("module_author"):
                published = timestamp(value.get("pub_ts")) or published
            if value := module.get("module_content"):
                paragraphs = value.get("paragraphs") or []
                blocks = ["".join(text_parts(p.get("text") or p)).strip() for p in paragraphs]
                body = "\n".join(filter(None, blocks)) or body
        kind = "opus"
    else:
        dyn = modules.get("module_dynamic") or {}
        major = dyn.get("major") or {}
        published = timestamp((modules.get("module_author") or {}).get("pub_ts"))
        opus = major.get("opus") or {}
        article = major.get("article") or {}
        title = opus.get("title") or article.get("title") or ""
        description = dyn.get("desc") or opus.get("summary") or {}
        body = description.get("text") or article.get("desc") or ""
        article_id = article.get("id")
        kind = "article" if article else "dynamic"
    return {
        "post_id": post_id, "article_id": str(article_id) if article_id else None,
        "kind": kind, "published_at": published, "title": title, "body": body,
        "detail_status": "full" if body and not article_id else "preview",
        "source_url": source_url or f"https://www.bilibili.com/opus/{post_id}",
        "blocks_json": [{"kind": "text", "text": block} for block in body.splitlines() if block.strip()],
    }


def article_preview(row):
    article_id = str(row["id"])
    body = row.get("summary") or ""
    return {
        "post_id": f"cv{article_id}", "article_id": article_id, "kind": "article",
        "published_at": timestamp(row.get("publish_time") or row.get("ctime")),
        "title": row.get("title") or "", "body": body, "detail_status": "preview",
        "source_url": f"https://www.bilibili.com/read/cv{article_id}",
        "blocks_json": [{"kind": "text", "text": body}] if body else [],
    }


def collect(uid, max_pages, detail, *, articles=False):
    """Yield rows incrementally. Errors leave a usable partial local snapshot."""
    seen = set()
    cursor = ""
    for page_number in range(1, max_pages + 1):
        if articles:
            data = get(ARTICLE_LIST, mid=uid, pn=page_number, ps=30)
            items = data.get("articles") or []
        else:
            data = get(DYNAMIC_FEED, host_mid=uid, offset=cursor)
            items = data.get("items") or []
        for item in items:
            key = str((item.get("id") if articles else item.get("id_str")) or "")
            if not key or key in seen:
                continue
            seen.add(key)
            if articles:
                yield article_preview(item)
                continue
            row = normalize(item)
            row["detail_status"] = "preview"
            if detail:
                try:
                    modules = item.get("modules") or {}
                    major = modules.get("module_dynamic") or {} if isinstance(modules, dict) else {}
                    if (major.get("major") or {}).get("opus"):
                        extra = get(OPUS_DETAIL, id=key)["item"]
                    else:
                        extra = get(DYNAMIC_DETAIL, id=key)["item"]
                    result = normalize(extra, fallback_id=key)
                    if result["body"]:
                        row = result
                except (ValueError, KeyError, URLError, TimeoutError) as error:
                    print(f"Detail unavailable for {key}: {error}")
                time.sleep(0.30)
            yield row
        if articles:
            total = data.get("count")
            if len(items) < 30 or total is not None and page_number * 30 >= int(total):
                return
        else:
            if not data.get("has_more"):
                return
            next_cursor = str(data.get("offset") or "")
            if not next_cursor or next_cursor == cursor:
                raise ValueError("Bilibili returned a missing or repeated pagination cursor")
            cursor = next_cursor
        time.sleep(0.45)
    print("Reached --max-pages. The saved snapshot may be partial.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("uid")
    parser.add_argument("output", type=Path)
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--detail", action="store_true")
    parser.add_argument("--articles", action="store_true", help="Collect the public article index")
    args = parser.parse_args()
    if not args.uid.isascii() or not args.uid.isdecimal() or args.max_pages < 1:
        parser.error("UID must be numeric and --max-pages must be positive")
    with args.output.open("x", encoding="utf-8") as stream:
        for row in collect(args.uid, args.max_pages, args.detail, articles=args.articles):
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            stream.flush()


if __name__ == "__main__":
    main()
