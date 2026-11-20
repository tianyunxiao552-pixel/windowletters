"""Export a local text reference for editing a persona card."""

import argparse
import sqlite3
from contextlib import closing
from pathlib import Path


def write_reference(db, stream, post_limit):
    def line(text=""):
        print(text, file=stream)

    line("# 人格卡参考素材")
    line()
    line("档案条目包含本人陈述、观点和归纳。短评、原帖及引文用于核对说法和语言习惯。")
    line()
    line("## 资料条目")
    line()
    for item in db.execute("SELECT * FROM items ORDER BY category, id"):
        line(f"### {item['label']}（{item['category']} · {item['basis']}）")
        line(item["statement"])
        if item["context"]:
            line(item["context"])
        quotes = db.execute(
            """SELECT e.quote, s.url FROM item_evidence AS i
               JOIN evidence AS e ON e.id = i.evidence_id
               JOIN sources AS s ON s.post_id = e.post_id
               WHERE i.item_id = ? ORDER BY i.sort_order""",
            (item["id"],),
        )
        for quote, url in quotes:
            line(f"- 引文：{quote}（{url}）")
        line()
    line("## Bangumi 评分和短评")
    line()
    for row in db.execute(
        """SELECT title, personal_rating, personal_review, work_url
           FROM bangumi_reviews ORDER BY personal_rating DESC, title"""
    ):
        title, rating, review, url = row
        score = f"{rating}/10" if rating is not None else "无评分"
        line(f"- {title}（{score}）{url}")
        if review:
            line(f"  {review}")
    line()
    line("## B 站动态和文章")
    line()
    for title, body, url, status in db.execute(
        """SELECT title, body, source_url, detail_status FROM bilibili_posts
           WHERE TRIM(body) <> '' ORDER BY published_at DESC, post_id DESC LIMIT ?""",
        (post_limit,),
    ):
        detail = "全文" if status == "full" else "预览"
        line(f"### {title or '无标题'}（{detail}）")
        line(url)
        line(body)
        line()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--post-limit", type=int, default=30, help="Use -1 to include all posts")
    args = parser.parse_args()
    if args.post_limit < -1:
        parser.error("--post-limit must be -1 or a nonnegative number")
    uri = args.database.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.row_factory = sqlite3.Row
        with args.output.open("x", encoding="utf-8") as stream:
            write_reference(db, stream, args.post_limit)


if __name__ == "__main__":
    main()
