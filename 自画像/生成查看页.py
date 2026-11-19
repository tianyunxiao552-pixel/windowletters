import argparse
import sqlite3
from contextlib import closing
from html import escape
from pathlib import Path

SECTIONS = (
    (
        "资料条目",
        ("类别", "名称", "内容"),
        "SELECT category, label, statement FROM items ORDER BY category, id",
    ),
    (
        "作品短评",
        ("作品", "类型", "评分", "短评"),
        "SELECT title, media_type, personal_rating, personal_review FROM bangumi_reviews ORDER BY title",
    ),
    (
        "帖子摘记",
        ("日期", "标题", "内容"),
        "SELECT published_at, title, body FROM bilibili_posts ORDER BY published_at DESC",
    ),
)


def render(source: Path) -> str:
    sections = []
    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        for title, labels, query in SECTIONS:
            headers = "".join(f"<th>{escape(label)}</th>" for label in labels)
            rows = []
            for row in db.execute(query):
                cells = "".join(
                    f"<td>{escape(str(value)) if value is not None else ''}</td>"
                    for value in row
                )
                rows.append(f"<tr>{cells}</tr>")
            body = "".join(rows) or f'<tr><td colspan="{len(labels)}">暂无记录</td></tr>'
            sections.append(
                f"<section><h2>{escape(title)}</h2><table><thead><tr>{headers}</tr>"
                f"</thead><tbody>{body}</tbody></table></section>"
            )
    return (
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>窗边来信 · 自画像</title>"
        "<style>body{max-width:1050px;margin:2rem auto;padding:0 1rem;"
        "font:16px/1.6 system-ui;color:#29251f;background:#faf7f0}"
        "h2{margin-top:2rem}table{width:100%;border-collapse:collapse}"
        "th,td{border-bottom:1px solid #d8cebb;padding:.55rem;text-align:left;"
        "vertical-align:top;overflow-wrap:anywhere}</style>"
        "<main><h1>自画像</h1>" + "".join(sections) + "</main></html>"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a local, read-only profile viewer.")
    parser.add_argument("database", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.resolve() == args.database.resolve():
        parser.error("choose a separate output file")
    args.output.write_text(render(args.database), encoding="utf-8")


if __name__ == "__main__":
    main()
