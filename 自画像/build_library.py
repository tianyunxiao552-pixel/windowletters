"""Build a local SQLite library from public snapshots and hand-curated notes."""

import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from collect_bilibili import article_preview, normalize, timestamp

MEDIA = {1: "书籍", 2: "动画", 3: "音乐", 4: "游戏", 6: "三次元"}
STATUS = {1: "想看", 2: "看过", 3: "在看", 4: "搁置", 5: "抛弃"}
POST_FIELDS = (
    "post_id", "article_id", "kind", "published_at", "title", "body",
    "detail_status", "source_url", "blocks_json",
)
DETAIL_FILES = (
    "details-more.jsonl", "details.jsonl", "details-final.jsonl", "details-api.jsonl",
)


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def jsonl(path):
    with path.open(encoding="utf-8-sig") as stream:
        for number, line in enumerate(stream, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except ValueError as error:
                    raise ValueError(f"{path.name}, line {number}: invalid JSON") from error


def bangumi_rows(snapshot):
    profile_url = snapshot.get("profile_url", "")
    result = {}
    for item in snapshot["rows"]:
        rating = item.get("rate") or None
        review = (item.get("comment") or "").strip()
        if item.get("private") or (not rating and not review):
            continue
        sid = item["subject_id"]
        subject = item.get("subject") or {}
        original = subject.get("name") or ""
        result[sid] = (
            sid, MEDIA.get(item.get("subject_type"), "其他"),
            subject.get("name_cn") or original or str(sid), original,
            STATUS.get(item.get("type"), "其他"), rating, review,
            item.get("updated_at"), f"https://bgm.tv/subject/{sid}", profile_url,
        )
    return result.values()


def cached_item(row):
    for field in ("api_response", "dynamic_response"):
        if row.get(field):
            payload = row[field]
            if isinstance(payload, str):
                payload = json.loads(payload)
            return (payload.get("data") or {}).get("item")
    state = row.get("state")
    if not state and row.get("state_tail"):
        state, _ = json.JSONDecoder().raw_decode(row["state_tail"].lstrip())
    return state.get("detail") if isinstance(state, dict) else None


def cached_posts(folder):
    """Read index/JSONL from the earlier separate collection passes."""
    index = load_json(folder / "index.json")
    rows = {}
    for post_id, entry in index.get("listed", {}).items():
        body = entry.get("content") or ""
        if not isinstance(body, str):
            body = ""
        rows[post_id] = {
            "post_id": post_id, "article_id": None, "kind": "dynamic",
            "published_at": timestamp(entry.get("pub_time")), "title": "",
            "body": body, "detail_status": "preview",
            "source_url": f"https://www.bilibili.com/opus/{post_id}",
            "blocks_json": [{"kind": "text", "text": body}] if body else [],
        }
    for item in index.get("articles", {}).values():
        row = article_preview(item)
        rows[row["post_id"]] = row
    skipped = 0
    for name in DETAIL_FILES:
        path = folder / name
        if not path.is_file():
            continue
        for record in jsonl(path):
            try:
                item = cached_item(record)
                if not item:
                    continue
                requested = str(record.get("requested_id") or "")
                is_article = record.get("kind") == "article"
                key = f"cv{requested}" if is_article and requested else requested
                row = normalize(item, fallback_id=key, source_url=record.get("url"))
                if not row["body"]:
                    continue
                if key in rows:
                    earlier = rows[key]
                    row["post_id"] = key
                    row["article_id"] = earlier["article_id"] or row["article_id"]
                    row["kind"] = earlier["kind"]
                    for field in ("published_at", "title"):
                        row[field] = row[field] or earlier[field]
                if rows.get(row["post_id"], {}).get("detail_status") == "full" and row["detail_status"] == "preview":
                    continue
                rows[row["post_id"]] = row
            except (TypeError, ValueError, KeyError, AttributeError):
                skipped += 1
    if skipped:
        print(f"{skipped} cached details could not be decoded; index previews were kept.")
    return rows.values()


def existing_posts(path):
    uri = path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as source:
        source.row_factory = sqlite3.Row
        columns = ", ".join(POST_FIELDS)
        for row in source.execute(f"SELECT {columns} FROM posts"):
            yield dict(row)


def insert_post(db, row):
    entry = dict(row)
    blocks = entry.get("blocks_json") or []
    if isinstance(blocks, str):
        blocks = json.loads(blocks)
    entry["blocks_json"] = json.dumps(
        [block for block in blocks if block.get("kind") != "images"], ensure_ascii=False
    )
    pid = entry["post_id"]
    existing = db.execute("SELECT detail_status FROM bilibili_posts WHERE post_id=?", (pid,)).fetchone()
    if existing and existing[0] == "full" and entry["detail_status"] == "preview":
        return
    db.execute("INSERT OR REPLACE INTO bilibili_posts VALUES (?,?,?,?,?,?,?,?,?)",
               tuple(entry.get(key) for key in POST_FIELDS))
    db.execute(
        """INSERT INTO sources VALUES (?,?,?,?,?) ON CONFLICT(post_id) DO UPDATE SET
        published_at=excluded.published_at, type=excluded.type,
        page_title=excluded.page_title, url=excluded.url""",
        (pid, entry.get("published_at") or "", entry["kind"], entry["title"], entry["source_url"]),
    )


def insert_notes(db, notes):
    for key, value in notes.get("profile", {}).items():
        db.execute("INSERT INTO profile VALUES (?,?)", (key, value))
    for item in notes.get("items", []):
        fields = ("category", "label", "statement", "basis", "context")
        row = db.execute("INSERT INTO items(category,label,statement,basis,context) VALUES (?,?,?,?,?)",
                         tuple(item[key] for key in fields))
        for number, evidence in enumerate(item.get("evidence", [])):
            post_id, quote = evidence["post_id"], evidence["quote"]
            original = db.execute("SELECT body FROM bilibili_posts WHERE post_id=?", (post_id,)).fetchone()
            if not original or not quote.strip() or quote not in original[0]:
                raise ValueError(f"Note {item['label']!r} quotes absent source text")
            db.execute("INSERT OR IGNORE INTO evidence(post_id,quote) VALUES (?,?)", (post_id, quote))
            evidence_id, = db.execute("SELECT id FROM evidence WHERE post_id=? AND quote=?", (post_id, quote)).fetchone()
            db.execute("INSERT INTO item_evidence VALUES (?,?,?)", (row.lastrowid, number, evidence_id))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="Path to a new SQLite database")
    parser.add_argument("--bangumi", type=Path)
    parser.add_argument("--bilibili", type=Path, action="append", default=[])
    parser.add_argument("--bilibili-cache", type=Path)
    parser.add_argument("--bilibili-db", type=Path, help="Earlier local archive with a posts table")
    parser.add_argument("--notes", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; choose a new database path")
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    with TemporaryDirectory(dir=args.output.resolve().parent) as folder:
        temporary = Path(folder) / "library.sqlite3"
        with closing(sqlite3.connect(temporary)) as db, db:
            db.executescript(schema)
            db.execute("PRAGMA foreign_keys=ON")
            if args.bangumi:
                db.executemany("INSERT INTO bangumi_reviews VALUES (?,?,?,?,?,?,?,?,?,?)",
                               bangumi_rows(load_json(args.bangumi)))
            if args.bilibili_cache:
                for row in cached_posts(args.bilibili_cache):
                    insert_post(db, row)
            if args.bilibili_db:
                for row in existing_posts(args.bilibili_db):
                    insert_post(db, row)
            for path in args.bilibili:
                for row in jsonl(path):
                    insert_post(db, row)
            if args.notes:
                insert_notes(db, load_json(args.notes))
            for table in ("bangumi_reviews", "bilibili_posts", "items"):
                print(table, db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        temporary.rename(args.output.resolve())


if __name__ == "__main__":
    main()
