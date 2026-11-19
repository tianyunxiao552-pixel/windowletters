"""Group-history and delivery logic for Ito's Beijing-time daily report."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

BEIJING = timezone(timedelta(hours=8), "北京时间")


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime


def due_window(now: datetime) -> Window | None:
    local = now.astimezone(BEIJING)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=23)
    return Window(start, end) if local >= end else None


def today_window(now: datetime) -> Window:
    local = now.astimezone(BEIJING)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return Window(start, local)


def compute_stats(rows: list[dict]) -> dict:
    if not rows:
        return {"total_messages": 0, "active_members": 0, "peak_hour": ""}
    members = {r.get("sender") for r in rows if r.get("sender") and r.get("sender") != "群友"}
    hour_counts: dict[int, int] = {}
    for row in rows:
        hhmm = str(row.get("time") or "")
        if len(hhmm) >= 2 and hhmm[:2].isdigit():
            h = int(hhmm[:2])
            if 0 <= h <= 23:
                hour_counts[h] = hour_counts.get(h, 0) + 1
    peak_hour = ""
    if hour_counts:
        top_h = max(hour_counts, key=lambda h: (hour_counts[h], -h))
        peak_hour = f"{top_h:02d}:00–{(top_h + 1) % 24:02d}:00"
    return {
        "total_messages": len(rows),
        "active_members": len(members) if members else 1,
        "peak_hour": peak_hour,
    }


def format_stats_line(stats: dict) -> str:
    total = stats.get("total_messages", 0)
    if not total:
        return "暂无同步文字"
    parts = [f"共 {total} 条文字", f"{stats.get('active_members', 0)} 人冒泡"]
    if stats.get("peak_hour"):
        parts.append(f"最热闹 {stats['peak_hour']}")
    return " · ".join(parts)


async def collect(
    client,
    account: str,
    group: str,
    window: Window,
    bot_id: str = "",
    *,
    names: dict[str, str] | None = None,
):
    records = {}
    cursor = ""
    cursors = set()
    partial = False
    name_map = names or {}
    for _ in range(100):
        page = await client.messages(group, limit=50, cursor=cursor)
        items = page["items"]
        partial |= (page.get("coverage") or {}).get("partial") is True
        older_page = bool(items)
        for item in items:
            if item.get("accountId") != account or item.get("threadId") != group:
                raise ValueError("unexpected history scope")
            try:
                stamp = datetime.fromisoformat(item["createdAt"])
                if stamp.tzinfo is None:
                    raise ValueError("timestamp without timezone")
            except (TypeError, ValueError, KeyError):
                older_page = False
                partial = True
                continue
            older_page &= stamp < window.start
            mid, body, sender = item.get("id"), item.get("body"), item.get("senderId")
            msg_type = item.get("type")
            is_text = msg_type == 1
            is_quote = msg_type == 49 and item.get("appMessageType") == 57
            if (
                window.start <= stamp < window.end
                and (is_text or is_quote)
                and item.get("direction") == "incoming"
                and item.get("recall") is None
                and not item.get("deleted")
                and sender
                and sender != bot_id
                and mid
                and isinstance(body, str)
                and body.strip()
            ):
                quote_text = ""
                if is_quote and isinstance(item.get("quote"), dict):
                    q = item["quote"]
                    if q.get("state") == "embedded" and isinstance(q.get("embeddedText"), str):
                        quote_text = " ".join(q["embeddedText"].strip().split())[:120]
                display = name_map.get(sender) or "群友"
                records[mid] = (stamp, display, body.strip(), quote_text)
        cursor = page.get("nextCursor")
        # The Native history API paginates from newest to oldest.
        if not cursor or older_page:
            break
        if cursor in cursors:
            partial = True
            break
        cursors.add(cursor)
    else:
        partial = True
    rows = []
    for stamp, display, body, quote_text in sorted(records.values()):
        row = {
            "time": stamp.astimezone(BEIJING).strftime("%H:%M"),
            "sender": display,
            "text": body,
        }
        if quote_text:
            row["quote"] = quote_text
        rows.append(row)
    return rows, partial


def read_report(file: Path) -> dict | None:
    return json.loads(file.read_text(encoding="utf-8")) if file.exists() else None


def save_report(file: Path, report: dict):
    file.parent.mkdir(parents=True, exist_ok=True)
    temp = file.with_suffix(".tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(file)


async def deliver(client, account: str, group: str, file: Path, text: str = ""):
    report = read_report(file)
    if report:
        if (report["account"], report["group"]) != (account, group):
            raise ValueError("report belongs to a different account or group")
        if report["status"] == "accepted":
            return
        receipt = await client.send_by_key(report["key"])
        if receipt.get("accountId") != account or receipt.get("destination") != group:
            raise ValueError("unexpected receipt scope")
    else:
        key = hashlib.sha256(f"ito-daily:{account}:{group}:{file.stem}".encode()).hexdigest()
        report = {"account": account, "group": group, "text": text, "key": key, "status": "submitted"}
        save_report(file, report)
        receipt = await client.send_text(group, text, key)
    if receipt.get("state") == "accepted":
        report["status"] = "accepted"
        report["receipt"] = receipt["id"]
        save_report(file, report)
